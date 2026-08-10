# BoringCache Discourse benchmark

This benchmark executes Discourse Docker's pinned upstream `base` job: the
amd64/arm64 Bake graph, image specs, and trusted-event digest publication.

The root [`.boringcache.toml`](.boringcache.toml) is the local entry point.
Every upstream Bake step has an executable committed plan under [`plans/`](plans/);
the workflows only select those plans and add the compared cache provider.
[`scripts/verify-upstream-recipe.py`](scripts/verify-upstream-recipe.py) checks
the commands, architecture matrix, test invocation, and publish graph against
the pinned `discourse/discourse_docker` workflow before a benchmark runs.
