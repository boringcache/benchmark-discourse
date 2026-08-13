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


def expected_command() -> list[str]:
    return [
        "docker",
        "buildx",
        "bake",
        "base-runtime-deps",
        "base-slim-main",
        "base-slim-stable",
        "base-web-only-main",
        "base-web-only-stable",
        "base-release-main",
        "base-release-stable",
        "test-release",
    ]


def expected_runtime_deps_command() -> list[str]:
    return [
        "docker",
        "buildx",
        "bake",
        "base-runtime-deps",
        "--set=base-runtime-deps.no-cache=true",
        "--load",
    ]


def main() -> int:
    try:
        workflow = UPSTREAM_WORKFLOW.read_text()
        for fragment in (
            "arch: [amd64, arm64]",
            "docker buildx bake base-runtime-deps -f docker-bake.hcl -f docker-bake.cache.hcl --load",
            "docker buildx bake base-slim-main -f docker-bake.hcl -f docker-bake.cache.hcl",
            "docker buildx bake base-web-only-main -f docker-bake.hcl -f docker-bake.cache.hcl --load",
            "docker buildx bake base-release-main -f docker-bake.hcl -f docker-bake.cache.hcl --load",
            "docker buildx bake test-release -f docker-bake.hcl -f docker-bake.cache.hcl --load",
        ):
            require(fragment in workflow, f"upstream base job changed: {fragment}")

        for name, (lane, arch) in PLANS.items():
            path = ROOT / "plans" / name / ".boringcache.toml"
            with path.open("rb") as config_file:
                adapters = tomllib.load(config_file)["adapters"]
            adapter = adapters["docker"]
            ccache = adapters["ccache"]
            require(adapter["command"] == expected_command(), f"{name} command drifted")
            require(adapter["tag"] == f"discourse-image-factory-{lane}-{arch}", f"{name} tag drifted")
            require(adapter["no-platform"] is True, f"{name} must keep one explicit cache cohort")
            require(adapter["no-git"] is True, f"{name} must use its declared lane and architecture")
            require(ccache["tag"] == f"discourse-ccache-{lane}-{arch}", f"{name} ccache tag drifted")
            require(ccache["no-platform"] is True, f"{name} ccache must use the Docker platform cohort")
            require(ccache["no-git"] is True, f"{name} ccache must use its declared lane")
            require(ccache["fail-on-cache-error"] is True, f"{name} ccache must fail closed")

        runtime_deps_path = ROOT / "plans" / "rolling-amd64-runtime-deps" / ".boringcache.toml"
        with runtime_deps_path.open("rb") as config_file:
            runtime_deps_adapters = tomllib.load(config_file)["adapters"]
        require(
            runtime_deps_adapters["docker"]["command"] == expected_runtime_deps_command(),
            "ccache experiment must isolate the forced-no-cache runtime-deps target",
        )
        require(
            runtime_deps_adapters["docker"]["tag"] == "discourse-runtime-deps-rolling-amd64",
            "runtime-deps Docker tag drifted",
        )
        require(
            runtime_deps_adapters["ccache"]["tag"] == "discourse-ccache-runtime-deps-rolling-amd64",
            "runtime-deps ccache tag drifted",
        )

        with (ROOT / ".boringcache.toml").open("rb") as config_file:
            root_adapters = tomllib.load(config_file)["adapters"]
        root_adapter = root_adapters["docker"]
        require(
            root_adapter["command"] == expected_command(),
            "root default plan drifted",
        )
        require(
            root_adapter["tag"] == "discourse-image-factory-rolling-amd64",
            "root default tag drifted",
        )
        require(
            root_adapters["ccache"]["tag"] == "discourse-ccache-rolling-amd64",
            "root ccache tag drifted",
        )

        action = (ROOT / ".github/actions/discourse-image-factory/action.yml").read_text()
        rolling = (ROOT / ".github/workflows/discourse-image-factory.yml").read_text()
        fresh = (ROOT / ".github/workflows/discourse-image-factory-fresh.yml").read_text()
        require("discourse-dev.Dockerfile" not in action + rolling + fresh, "custom Dockerfile returned")
        dockerfile = UPSTREAM_DOCKERFILE.read_text()
        require(render(dockerfile, "baseline") == dockerfile, "baseline cache profile must leave upstream unchanged")
        bundler_profile = render(dockerfile, "bundler")
        require(bundler_profile == dockerfile, "Bundler profile must use the fork's committed cache mount")
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
        require(
            bundler_profile.count("target=/home/discourse/.local/share/pnpm/store") == 1,
            "base image must cache the upstream pnpm install",
        )
        test_dockerfile = (ROOT / "docker-upstream/image/discourse_test/Dockerfile").read_text()
        require(
            "--mount=type=cache,id=discourse-bundler-main,target=/home/discourse/.bundle/cache"
            in test_dockerfile,
            "test image must share the main Bundler cache mount",
        )
        require(
            "BUNDLE_GLOBAL_GEM_CACHE=true BUNDLE_USER_CACHE=/home/discourse/.bundle/cache bundle install"
            in test_dockerfile,
            "test image must use Bundler's mounted global cache",
        )
        require(
            "target=/home/discourse/.local/share/pnpm/store" in test_dockerfile,
            "test image must cache the upstream pnpm install",
        )
        ccache_profile = render(dockerfile, "ccache")
        require("    ccache \\\n" in ccache_profile, "ccache profile does not install ccache")
        require("ARG CCACHE_VERSION=4.13.6" in ccache_profile, "ccache profile must use the CLI-tested version")
        require("COPY ccache /usr/bin/ccache" in ccache_profile, "ccache profile must use the staged release")
        require("/usr/bin/ccache" in ccache_profile, "released ccache must replace Debian's older binary")
        require(
            'ENV PATH="/usr/lib/ccache:${PATH}"' in ccache_profile,
            "ccache profile does not select Debian's compiler wrappers",
        )
        require("CCACHE_REMOTE_STORAGE" not in ccache_profile, "the Dockerfile must not own BoringCache's ccache endpoint")
        require(
            ccache_profile.count("BUNDLE_GLOBAL_GEM_CACHE=true") == 1,
            "ccache control must retain the fork's native Bundler mount without enabling remote offload",
        )
        combined_profile = render(dockerfile, "bundler-ccache")
        require(
            "BUNDLE_GLOBAL_GEM_CACHE=true BUNDLE_USER_CACHE=/home/discourse/.bundle/cache bundle install"
            in combined_profile,
            "combined profile does not enable the Bundler mount cache",
        )
        require("COPY ccache /usr/bin/ccache" in combined_profile, "combined profile does not stage ccache")
        require(
            'ENV PATH="/usr/lib/ccache:${PATH}"' in combined_profile,
            "combined profile does not select ccache's compiler wrappers",
        )
        require(
            'PLAN: ${{ format(\'{0}-{1}\', inputs.cache_lane, inputs.arch) }}' in action,
            "composite action does not select the committed lane and architecture plan",
        )
        require('PLAN_VARIANT: ${{ inputs.plan_variant }}' in action, "composite action does not select focused plans")
        require(
            action.count('ARCH: ${{ inputs.arch }}') == 4,
            "composite action must pin architecture-sensitive scope, build, and report steps",
        )
        require(
            '--ccache-tag "${CACHE_SCOPE}-compiler"' in action,
            "composite action does not materialize an isolated ccache cohort",
        )
        require("docker run --rm" in action, "upstream test invocation is missing")
        require(
            "timeout --foreground --signal=TERM --kill-after=1m 45m" in action,
            "upstream image specs must not hang a benchmark lane indefinitely",
        )
        require(
            '-e COMMIT_HASH="$DISCOURSE_SOURCE_SHA"' in action,
            "upstream image specs must test the reported Discourse source",
        )
        boringcache_runner = (ROOT / "scripts/run-boringcache-plan.py").read_text()
        require(
            boringcache_runner.count('"boringcache",') == 1,
            "BoringCache target runner must use one CLI-owned Docker lifecycle per target",
        )
        require("https://install.boringcache.com/install.sh" in action, "BoringCache path must use the public installer")
        require("CLI_VERSION: ${{ inputs.cli_version }}" in action, "CLI canary input is not forwarded")
        require(
            "BORINGCACHE_MANAGED_BUILDKIT_IMAGE: ${{ inputs.buildkit_image }}" in action,
            "BuildKit canary input is not forwarded",
        )
        require("run-boringcache-plan.py" in action, "CLI must run the upstream Bake targets")
        require('args+=(--read-only)' in action, "warm builds must restore without publishing")
        require('args+=(--mount-cache)' in action, "Bundler experiment must enable mount-cache offload")
        require(
            '[[ "$CACHE_PROFILE" == "bundler" || "$CACHE_PROFILE" == "bundler-ccache" ]]' in action,
            "mount-cache offload must stay scoped to Bundler profiles",
        )
        require(
            'boringcache_args.extend(("--tool-cache", "ccache"))' in boringcache_runner,
            "ccache experiment must use the released Docker tool-cache surface",
        )
        require(
            '[[ "$CACHE_PROFILE" == "ccache" || "$CACHE_PROFILE" == "bundler-ccache" ]]' in action,
            "Docker ccache must stay scoped to ccache profiles",
        )
        require(
            action.index("Capture image-factory timing") < action.index("Run upstream's image specs"),
            "image-factory timing must not include the upstream specs",
        )
        require("continue-on-error: true" in action, "benchmark evidence must survive an upstream spec timeout")
        require(
            "Stage the CLI-compatible ccache binary" in action,
            "ccache profile must stage its compatible binary on the native runner",
        )
        require(
            action.index("Stage the CLI-compatible ccache binary") < action.index("Start image-factory timing"),
            "ccache tool setup must stay outside build timing",
        )
        require("Smoke test the runtime-deps image" in action, "focused ccache builds must smoke test their output")
        require("if: inputs.run_specs == 'true'" in action, "focused builds must be able to skip unrelated image specs")
        require("run-actions-cache-plan.py" in action, "GitHub Actions comparison path is missing")
        require("publish_images" not in action + rolling + fresh, "benchmark image publication returned")
        require("git -C upstream rev-parse HEAD" in action, "rolling cache does not use the pinned Discourse source")
        require(
            action.count('DISCOURSE_REF: ${{ inputs.discourse_ref }}') == 3,
            "checkout and both cache providers must receive the exact Discourse source",
        )
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
        require("bundler_cache_experiment" in rolling, "full cache-stack workflow-dispatch lane is missing")
        require(
            rolling.count("cache_profile: bundler-ccache") == 4,
            "seed and roll must both select mount cache plus ccache on amd64 and arm64",
        )
        require(
            "report_strategy: boringcache-bundler-ccache" in rolling,
            "combined lane does not retain its own result",
        )
        require("ccache_experiment" in rolling, "ccache workflow-dispatch lane is missing")
        require("cache_profile: ccache" in rolling, "ccache lane does not select the ccache profile")
        require("plan_variant: runtime-deps" in rolling, "ccache lane must isolate runtime-deps")
        require('run_specs: "false"' in rolling, "runtime-deps lane must not invoke the absent test image")
        require("report_strategy: boringcache-ccache" in rolling, "ccache lane does not retain its own result")
        require(
            "origin/tests-passed" in (ROOT / "upstream/script/docker_test.rb").read_text(),
            "upstream image specs no longer select the tests-passed branch",
        )

        ccache_stage = (ROOT / "scripts" / "stage-ccache-binary.sh").read_text()
        require('version="4.13.6"' in ccache_stage, "staged ccache version drifted")
        require(
            "567b1b648411819590f918f045218c92da14418bdec3b30db94a3b4f5d77cf13" in ccache_stage,
            "amd64 ccache release must be checksum verified",
        )
        require(
            "fae67fb810e1f0d390409af6603355483572229e19183e68574cd0f851a6fb98" in ccache_stage,
            "arm64 ccache release must be checksum verified",
        )
        gitmodules = (ROOT / ".gitmodules").read_text()
        require("branch = tests-passed" in gitmodules, "source sync must follow Discourse tests-passed")
        require(
            "url = https://github.com/boringcache/discourse_docker.git" in gitmodules,
            "Docker recipes must come from the controlled BoringCache fork",
        )
        require(
            "branch = agent/benchmark-cache-controls" in gitmodules,
            "Docker recipe sync must follow the benchmark controls branch",
        )
        require("ARG DISCOURSE_REF" in dockerfile, "forked Dockerfile must accept an immutable Discourse ref")
        require(
            "git -C /var/www/discourse checkout --detach FETCH_HEAD" in dockerfile,
            "forked Dockerfile must build the requested Discourse commit",
        )
        bake = (ROOT / "docker-upstream/image/docker-bake.hcl").read_text()
        require('variable "DISCOURSE_REF"' in bake, "Bake must expose the immutable Discourse ref")
        require('variable "DATESTAMP"' in bake, "Bake must retain PR #1088's daily native-cache boundary")
        require("ARG DATESTAMP" in dockerfile, "Dockerfile must retain PR #1088's daily cache boundary")
        require(
            (ROOT / "docker-upstream/image/docker-bake.cache.hcl").exists(),
            "fork must include PR #1088's per-target cache-read composition",
        )
        require(
            (ROOT / "docker-upstream/image/docker-bake.cache-write.hcl").exists(),
            "fork must include PR #1088's per-target cache-write composition",
        )
        require(
            '"DISCOURSE_REF" = branch == "main" ? DISCOURSE_REF : ""' in bake,
            "Bake must pin main targets without changing stable targets",
        )

        seeded = rolling
        require("eedf0ac2344c37d66a2c9ab05dc8a83bf3efd9bb" in seeded, "seeded workflow lost its older ref")
        require("763655f6faf47b088afee1a59e2d97cec5886c97" in seeded, "seeded workflow lost its rolling ref")
        require(
            'git -C upstream diff --quiet "$SEED_REF" "$ROLLING_REF" -- Gemfile Gemfile.lock package.json pnpm-lock.yaml'
            in seeded,
            "seeded workflow must reject dependency-changing roll-forward refs",
        )
        require("cache_lane: fresh" in seeded, "seed and roll must share one run-scoped cache cohort")
        require("phase: warm" in seeded, "roll-forward jobs must restore read-only on fresh runners")
        require("BORINGCACHE_SAVE_TOKEN: \"\"" in seeded, "roll-forward jobs must not publish into the seed")
        require("ubuntu-24.04-arm" in seeded, "cache stack must cover upstream's native arm64 runner")
        require(
            seeded.count("strategy: actions-cache") >= 2,
            "seed and roll must retain the GitHub Actions comparison",
        )
        require(
            seeded.count("report_strategy: boringcache-bundler-ccache") == 4,
            "seed and roll must retain the full BoringCache cache stack on amd64 and arm64",
        )
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
        require("for target in targets" in runner, "GHA must build PR #1088 targets individually")
        require("if not args.read_only" in runner, "GHA roll-forward must not republish cache")
        require(
            "for target in targets" in boringcache_runner,
            "BoringCache must build PR #1088 targets individually",
        )
        selector = (ROOT / "scripts/select-boringcache-plan.py").read_text()
        require('destination = UPSTREAM_IMAGE / ".boringcache.toml"' in selector, "selected plan must reach the Action working directory")
        require("destination.write_text(updated)" in selector, "selected plan must be materialized before the Action runs")
        require('replace_adapter_tag(updated, "ccache", args.ccache_tag, source)' in selector, "selected plan must isolate ccache tags")
        require('"boringcache"' not in selector, "plan selection must not invoke the BoringCache product")
    except (KeyError, OSError, ProfileMismatch, RecipeMismatch, tomllib.TOMLDecodeError) as error:
        print(f"Discourse recipe mismatch: {error}", file=sys.stderr)
        return 1

    print("Verified Discourse amd64/arm64 Bake graph against the pinned upstream base job.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
