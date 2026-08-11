#!/usr/bin/env python3
"""Verify that committed plans still project Discourse's upstream base job."""

from __future__ import annotations

import os
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_WORKFLOW = ROOT / "docker-upstream/.github/workflows/build.yml"
PLANS = {
    "base-runtime-deps": ["base-runtime-deps", "--no-cache", "--load"],
    "base-slim": ["base-slim", "--load"],
    "base-web-only": ["base-web-only", "--load"],
    "base-release": ["base-release", "--load"],
    "test-release-amd64": ["test-release-amd64", "--load"],
    "test-release-arm64": ["test-release-arm64", "--load"],
    "publish-test": [
        "test",
        "--set=*.tags=ghcr.io/boringcache/discourse-benchmark-test",
        "--set=*.output=type=registry,push-by-digest=true",
        "--metadata-file=/tmp/test.json",
    ],
    "publish-dev": [
        "dev",
        "--set=*.tags=ghcr.io/boringcache/discourse-benchmark-dev",
        "--set=*.output=type=registry,push-by-digest=true",
        "--allow=fs.read=../templates",
        "--metadata-file=/tmp/dev.json",
    ],
    "publish-base": [
        "base",
        "--set=*.tags=ghcr.io/boringcache/discourse-benchmark-base",
        "--set=*.output=type=registry,push-by-digest=true",
        "--metadata-file=/tmp/base.json",
    ],
}


class RecipeMismatch(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RecipeMismatch(message)


def expected_command(arguments: list[str]) -> list[str]:
    return ["docker", "buildx", "bake", *arguments]


def main() -> int:
    try:
        workflow = UPSTREAM_WORKFLOW.read_text()
        for fragment in (
            "arch: [amd64, arm64]",
            "docker buildx bake base-runtime-deps --no-cache --load",
            "docker buildx bake base-slim --load",
            "docker buildx bake base-web-only --load",
            "docker buildx bake base-release --load",
            "docker buildx bake test-release-${{ matrix.arch }} --load",
            "docker buildx bake test --set=\"*.tags=${TEST_IMAGE}\" --set=\"*.output=type=registry,push-by-digest=true\" --metadata-file=/tmp/test.json",
            "docker buildx bake dev --set=\"*.tags=${DEV_IMAGE}\" --set=\"*.output=type=registry,push-by-digest=true\" --allow=fs.read=../templates --metadata-file=/tmp/dev.json",
            "docker buildx bake base --set=\"*.tags=${BASE_IMAGE}\" --set=\"*.output=type=registry,push-by-digest=true\" --metadata-file=/tmp/base.json",
        ):
            require(fragment in workflow, f"upstream base job changed: {fragment}")

        for name, arguments in PLANS.items():
            path = ROOT / "plans" / name / ".boringcache.toml"
            with path.open("rb") as config_file:
                adapter = tomllib.load(config_file)["adapters"]["docker"]
            require(adapter["command"] == expected_command(arguments), f"{name} command drifted")
            require(adapter["no-platform"] is True, f"{name} must keep one explicit cache cohort")
            require(adapter["no-git"] is True, f"{name} must not derive an ambient Git suffix")

        with (ROOT / ".boringcache.toml").open("rb") as config_file:
            root_adapter = tomllib.load(config_file)["adapters"]["docker"]
        require(
            root_adapter["command"] == expected_command(PLANS["base-runtime-deps"]),
            "root default plan drifted",
        )

        action = (ROOT / ".github/actions/discourse-image-factory/action.yml").read_text()
        rolling = (ROOT / ".github/workflows/discourse-image-factory.yml").read_text()
        fresh = (ROOT / ".github/workflows/discourse-image-factory-fresh.yml").read_text()
        require("discourse-dev.Dockerfile" not in action + rolling + fresh, "custom Dockerfile returned")
        for name in PLANS:
            if name.startswith("test-release-"):
                continue
            require(f'"{name}"' in action, f"composite action does not select {name}")
        require(
            '"test-release-${{ inputs.arch }}"' in action,
            "composite action does not select the architecture-specific test plan",
        )
        require("docker run --rm -e RUBY_ONLY=1" in action, "upstream test invocation is missing")
        require("git -C upstream rev-parse HEAD" in action, "rolling cache does not use the pinned Discourse source")
        require("git ls-remote" not in action, "benchmark execution must not race a moving upstream branch")
        require(
            'cache_scope="${BENCHMARK_ID}-rolling-${ref_slug}-${ARCH}"' in action,
            "rolling cache scope must stay stable across upstream commits",
        )
        require(
            'cache_scope="${BENCHMARK_ID}-rolling-${ref_slug}-${ARCH}-${tests_passed_sha}"' not in action,
            "rolling cache scope must not turn every upstream commit into a cold cohort",
        )
        require(
            "origin/tests-passed" in (ROOT / "upstream/script/docker_test.rb").read_text(),
            "upstream image specs no longer select the tests-passed branch",
        )
        gitmodules = (ROOT / ".gitmodules").read_text()
        require("branch = tests-passed" in gitmodules, "source sync must follow Discourse tests-passed")
        sync = (ROOT / ".github/workflows/sync.yml").read_text()
        require(
            "git submodule update --init --remote --checkout upstream docker-upstream" in sync,
            "source sync must pin the configured upstream branches exactly",
        )
        require("scope-boringcache-run.sh" not in action + rolling + fresh, "workflows must not rewrite plans")
        runner = (ROOT / "scripts/run-discourse-plan.py").read_text()
        require('cwd=UPSTREAM_IMAGE' in runner, "plans must run from upstream's image directory")
        require("shutil.copyfile" in runner, "BoringCache must consume the selected plan from upstream's image directory")
        require(
            os.access(ROOT / "scripts/install-boringcache-cli.sh", os.X_OK),
            "CLI installer must be executable",
        )
    except (KeyError, OSError, RecipeMismatch, tomllib.TOMLDecodeError) as error:
        print(f"Discourse recipe mismatch: {error}", file=sys.stderr)
        return 1

    print("Verified Discourse amd64/arm64 Bake graph against the pinned upstream base job.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
