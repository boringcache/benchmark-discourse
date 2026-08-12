#!/usr/bin/env python3
"""Verify that committed plans still project Discourse's upstream base job."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

from prepare_discourse_cache_profile import ProfileMismatch, render


ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_WORKFLOW = ROOT / "docker-upstream/.github/workflows/build.yml"
UPSTREAM_DOCKERFILE = ROOT / "docker-upstream/image/base/Dockerfile"
PLANS = {
    "fresh-amd64": ("fresh", "amd64"),
    "fresh-arm64": ("fresh", "arm64"),
    "rolling-amd64": ("rolling", "amd64"),
    "rolling-arm64": ("rolling", "arm64"),
}


class RecipeMismatch(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RecipeMismatch(message)


def expected_command(arch: str) -> list[str]:
    return [
        "docker",
        "buildx",
        "bake",
        "base-runtime-deps",
        "base-slim",
        "base-web-only",
        "base-release",
        f"test-release-{arch}",
        "--set=base-runtime-deps-*.no-cache=true",
        "--load",
    ]


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
        ):
            require(fragment in workflow, f"upstream base job changed: {fragment}")

        for name, (lane, arch) in PLANS.items():
            path = ROOT / "plans" / name / ".boringcache.toml"
            with path.open("rb") as config_file:
                adapter = tomllib.load(config_file)["adapters"]["docker"]
            require(adapter["command"] == expected_command(arch), f"{name} command drifted")
            require(adapter["tag"] == f"discourse-image-factory-{lane}-{arch}", f"{name} tag drifted")
            require(adapter["no-platform"] is True, f"{name} must keep one explicit cache cohort")
            require(adapter["no-git"] is True, f"{name} must use its declared lane and architecture")

        with (ROOT / ".boringcache.toml").open("rb") as config_file:
            root_adapter = tomllib.load(config_file)["adapters"]["docker"]
        require(
            root_adapter["command"] == expected_command("amd64"),
            "root default plan drifted",
        )
        require(
            root_adapter["tag"] == "discourse-image-factory-rolling-amd64",
            "root default tag drifted",
        )

        action = (ROOT / ".github/actions/discourse-image-factory/action.yml").read_text()
        rolling = (ROOT / ".github/workflows/discourse-image-factory.yml").read_text()
        fresh = (ROOT / ".github/workflows/discourse-image-factory-fresh.yml").read_text()
        require("discourse-dev.Dockerfile" not in action + rolling + fresh, "custom Dockerfile returned")
        dockerfile = UPSTREAM_DOCKERFILE.read_text()
        require(render(dockerfile, "baseline") == dockerfile, "baseline cache profile must leave upstream unchanged")
        bundler_profile = render(dockerfile, "bundler")
        require(
            "--mount=type=cache,id=discourse-bundler-${DISCOURSE_BRANCH},target=/home/discourse/.bundle/cache,sharing=locked,uid=1000,gid=1000"
            in bundler_profile,
            "Bundler cache profile does not mount Bundler's user cache",
        )
        require(
            "BUNDLE_GLOBAL_GEM_CACHE=true BUNDLE_USER_CACHE=/home/discourse/.bundle/cache bundle install"
            in bundler_profile,
            "Bundler cache profile does not enable the global gem cache",
        )
        require("discourse-ccache" not in bundler_profile, "paused ccache experiment returned")
        require(
            'PLAN: ${{ format(\'{0}-{1}\', inputs.cache_lane, inputs.arch) }}' in action,
            "composite action does not select the committed lane and architecture plan",
        )
        require(
            'select-boringcache-plan.py "$PLAN" --cache-tag "$CACHE_SCOPE"' in action,
            "composite action does not materialize the selected cache cohort",
        )
        require("docker run --rm -e RUBY_ONLY=1" in action, "upstream test invocation is missing")
        require(action.count("boringcache docker") == 1, "BoringCache path must use one CLI-owned Docker lifecycle")
        require("https://install.boringcache.com/install.sh" in action, "BoringCache path must use the public installer")
        require("CLI_VERSION: ${{ inputs.cli_version }}" in action, "CLI canary input is not forwarded")
        require(
            "BORINGCACHE_MANAGED_BUILDKIT_IMAGE: ${{ inputs.buildkit_image }}" in action,
            "BuildKit canary input is not forwarded",
        )
        require("working-directory: docker-upstream/image" in action, "CLI must run the upstream Bake plan")
        require('args+=(--read-only)' in action, "warm builds must restore without publishing")
        require('args+=(--mount-cache)' in action, "Bundler experiment must enable mount-cache offload")
        require('[[ "$CACHE_PROFILE" == "bundler" ]]' in action, "mount-cache offload must stay scoped to Bundler")
        require("--tool-cache ccache" not in action + rolling, "unsupported Docker ccache composition returned")
        require("run-actions-cache-plan.py" in action, "GitHub Actions comparison path is missing")
        require("publish_images" not in action + rolling + fresh, "benchmark image publication returned")
        require("git -C upstream rev-parse HEAD" in action, "rolling cache does not use the pinned Discourse source")
        require("git ls-remote" not in action, "benchmark execution must not race a moving upstream branch")
        require(
            "a68d4b8707fd653697e8b6b27b336d093dbed5e4" in action,
            "historical runs must enforce the Mozilla signing-key boundary",
        )
        require(
            "must be a full immutable commit SHA" in action,
            "historical source overrides must reject moving refs",
        )
        require(
            'cache_scope="${BENCHMARK_ID}${profile_slug}-rolling-${ref_slug}-${ARCH}"' in action,
            "rolling cache scope must stay stable across upstream commits",
        )
        require("${#cache_scope} > 80" in action, "long cache scopes must leave room for Bake target names")
        require(
            'cache_scope="${BENCHMARK_ID}-rolling-${ref_slug}-${ARCH}-${tests_passed_sha}"' not in action,
            "rolling cache scope must not turn every upstream commit into a cold cohort",
        )
        require(
            action.index("Prepare clean Discourse sources") < action.index("Prepare the benchmark cache profile"),
            "source cleanup would erase the benchmark cache profile",
        )
        require("bundler_cache_experiment" in rolling, "Bundler workflow-dispatch lane is missing")
        require("cache_profile: bundler" in rolling, "Bundler lane does not select the Bundler profile")
        require(
            "origin/tests-passed" in (ROOT / "upstream/script/docker_test.rb").read_text(),
            "upstream image specs no longer select the tests-passed branch",
        )
        gitmodules = (ROOT / ".gitmodules").read_text()
        require("branch = tests-passed" in gitmodules, "source sync must follow Discourse tests-passed")
        sync = (ROOT / ".github/workflows/sync.yml").read_text()
        require(
            "git -C upstream fetch --depth=1 origin refs/heads/tests-passed" in sync,
            "source sync must fetch Discourse tests-passed explicitly",
        )
        require(
            "git -C upstream checkout --detach FETCH_HEAD" in sync,
            "source sync must pin the fetched Discourse source",
        )
        require(
            "git submodule update --init --remote --checkout docker-upstream" in sync,
            "source sync must update the Docker recipe from its configured remote",
        )
        runner = (ROOT / "scripts/run-actions-cache-plan.py").read_text()
        require('cwd=UPSTREAM_IMAGE' in runner, "plans must run from upstream's image directory")
        require('"boringcache"' not in runner, "comparison helper must not own the BoringCache lifecycle")
        require("type=gha" in runner, "comparison helper must retain GitHub Actions Cache")
        selector = (ROOT / "scripts/select-boringcache-plan.py").read_text()
        require('destination = UPSTREAM_IMAGE / ".boringcache.toml"' in selector, "selected plan must reach the Action working directory")
        require("destination.write_text(updated)" in selector, "selected plan must be materialized before the Action runs")
        require('"boringcache"' not in selector, "plan selection must not invoke the BoringCache product")
    except (KeyError, OSError, ProfileMismatch, RecipeMismatch, tomllib.TOMLDecodeError) as error:
        print(f"Discourse recipe mismatch: {error}", file=sys.stderr)
        return 1

    print("Verified Discourse amd64/arm64 Bake graph against the pinned upstream base job.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
