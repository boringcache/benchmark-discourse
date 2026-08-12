#!/usr/bin/env python3
"""Apply one benchmark-only cache profile to Discourse's pinned Dockerfile."""

from __future__ import annotations

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "docker-upstream/image/base/Dockerfile"
PROFILES = ("baseline", "bundler")


class ProfileMismatch(RuntimeError):
    pass


def replace_once(source: str, before: str, after: str, description: str) -> str:
    matches = source.count(before)
    if matches != 1:
        raise ProfileMismatch(f"expected one {description}, found {matches}")
    return source.replace(before, after, 1)


def add_bundler_cache(source: str) -> str:
    return replace_once(
        source,
        "RUN cd /var/www/discourse &&\\\n"
        "    sudo -u discourse bundle config --local deployment true &&\\\n"
        "    sudo -u discourse bundle config --local path ./vendor/bundle &&\\\n"
        "    sudo -u discourse bundle config --local without test development &&\\\n"
        "    sudo -u discourse bundle install --jobs $(nproc --ignore=1) &&\\\n",
        "RUN --mount=type=cache,id=discourse-bundler-${DISCOURSE_BRANCH},target=/home/discourse/.bundle/cache,sharing=locked,uid=1000,gid=1000 \\\n"
        "    cd /var/www/discourse &&\\\n"
        "    sudo -u discourse bundle config --local deployment true &&\\\n"
        "    sudo -u discourse bundle config --local path ./vendor/bundle &&\\\n"
        "    sudo -u discourse bundle config --local without test development &&\\\n"
        "    sudo -u discourse env BUNDLE_GLOBAL_GEM_CACHE=true BUNDLE_USER_CACHE=/home/discourse/.bundle/cache bundle install --jobs $(nproc --ignore=1) &&\\\n"
        "    sudo -u discourse du -sh /home/discourse/.bundle/cache &&\\\n",
        "Bundler install command",
    )


def render(source: str, profile: str) -> str:
    if profile == "baseline":
        return source
    if profile == "bundler":
        return add_bundler_cache(source)
    raise ProfileMismatch(f"unknown cache profile: {profile}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("profile", choices=PROFILES)
    parser.add_argument("--dockerfile", type=Path, default=DOCKERFILE)
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = args.dockerfile.read_text()
    try:
        rendered = render(source, args.profile)
    except ProfileMismatch as error:
        raise SystemExit(f"Discourse cache profile mismatch: {error}") from error
    if not args.check:
        args.dockerfile.write_text(rendered)
    print(f"Prepared Discourse cache profile: {args.profile}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
