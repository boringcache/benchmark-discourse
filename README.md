# benchmark-discourse

Isolated Discourse benchmark runner for BoringCache vs GitHub Actions cache.

This repo exists separately from the central benchmarks publisher so Discourse can have:

- a pinned upstream source commit
- isolated GitHub Actions cache usage
- one per-repo BoringCache workspace name: `boringcache/benchmark-discourse`
- independent benchmark runs triggered by upstream sync commits, manual dispatches, and weekly fresh samples

## Source Model

- upstream app source lives in the pinned `upstream/` submodule
- the Discourse development Dockerfile source lives in the pinned `docker-upstream/` submodule
- workflows build `benchmark/discourse-dev.Dockerfile` with this benchmark repo as the Docker context
- image-factory workflows build selected `docker-upstream/image` targets from `discourse/discourse_docker`

Pinned upstream source:

- see committed `upstream/` submodule on `main`

Discourse uses Docker through the `discourse/discourse_docker` repo rather than keeping a Dockerfile in `discourse/discourse`. The benchmark Dockerfile follows the `image/discourse_dev` build shape, but copies the pinned `upstream/` app source into the build instead of cloning a floating branch during Docker build.

## Scenarios

- `cold`
- `warm1`

Fresh lane runs a no-prior-cache cold build plus one warm rerun on the same pinned source tree. Fresh samples run weekly and can also be dispatched manually. Rolling lane records the upstream commit build as-is after each upstream sync against the prior rolling cache and skips `warm1`.

The benchmark has three meaningful surfaces:

- `discourse-docker`: development Docker image shaped around the Discourse app source.
- `discourse-base-deps`, `discourse-base-web-only`, and `discourse-base-release`: selected `discourse_docker` base image targets.
- `discourse-test-release`: `discourse_docker` test-image release target.

Rolling dispatch runs the Docker GitHub Actions Cache/BoringCache pair and the image-factory Docker pair on every upstream sync commit. The retired dependency-directory package-CAS benchmark set has been removed.

BoringCache uses the outer BuildKit registry/OCI cache path only. It does not call BoringCache inside Dockerfile `RUN` steps, and upstream Dockerfile cache mounts stay native to BuildKit.

## Output

Each workflow uploads machine-readable JSON and Markdown summaries. Those artifacts are intended to be ingested by the central `boringcache/benchmarks` publisher later.

## Token Model

This repo uses split BoringCache tokens as the standard CI shape:

- `BORINGCACHE_RESTORE_TOKEN` for read-only restore and proxy access
- `BORINGCACHE_SAVE_TOKEN` for trusted write paths
- `BORINGCACHE_API_TOKEN` only where a single bearer variable is still required for compatibility
