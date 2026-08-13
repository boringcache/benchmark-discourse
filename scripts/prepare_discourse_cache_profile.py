#!/usr/bin/env python3
"""Apply one benchmark-only cache profile to Discourse's pinned Dockerfile."""

from __future__ import annotations

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "docker-upstream/image/base/Dockerfile"
PROFILES = ("baseline", "bundler", "ccache", "bundler-ccache")


class ProfileMismatch(RuntimeError):
    pass


def replace_once(source: str, before: str, after: str, description: str) -> str:
    matches = source.count(before)
    if matches != 1:
        raise ProfileMismatch(f"expected one {description}, found {matches}")
    return source.replace(before, after, 1)


def verify_bundler_cache(source: str) -> str:
    fragments = {
        "installed bundle cache mount": (
            "--mount=type=cache,id=discourse-bundle-${DISCOURSE_BRANCH},"
            "target=/home/discourse/.cache/bundle,sharing=locked,uid=1000,gid=1000"
        ),
        "pnpm home ownership": (
            "install -dm 0755 -o discourse -g discourse /home/discourse/.local/share/pnpm"
        ),
        "pnpm home cache mount": (
            "target=/home/discourse/.local/share/pnpm,sharing=locked,uid=1000,gid=1000"
        ),
        "installed bundle path": "bundle config --local path /home/discourse/.cache/bundle",
        "installed bundle materialization": (
            "cp -a /home/discourse/.cache/bundle/. /var/www/discourse/vendor/bundle/"
        ),
        "final image bundle path": "bundle config --local path ./vendor/bundle",
        "final image bundle repair install": (
            "sudo -u discourse bundle install --jobs $(nproc --ignore=1) &&\\\n"
            "    sudo -u discourse bundle check"
        ),
        "final image bundle check": "sudo -u discourse bundle check",
        "bundle cache before-install diagnostic": "Installed bundle cache before install:",
        "bundle cache after-install diagnostic": "Installed bundle cache after install:",
    }
    for description, fragment in fragments.items():
        matches = source.count(fragment)
        if matches != 1:
            raise ProfileMismatch(f"expected one {description}, found {matches}")
    return source


def add_ccache(source: str) -> str:
    source = replace_once(
        source,
        "    git \\\n"
        "    cmake \\\n",
        "    git \\\n"
        "    ccache \\\n"
        "    cmake \\\n",
        "builder package list",
    )
    return replace_once(
        source,
        "    libbrotli-dev\n\n"
        "FROM builder AS libheif-builder\n",
        "    libbrotli-dev\n\n"
        "# BoringCache v1.19.1 targets ccache 4.13.6's @-attribute syntax.\n"
        "# Keep Debian's compiler wrappers, but replace its older ccache binary.\n"
        "ARG CCACHE_VERSION=4.13.6\n"
        "COPY ccache /usr/bin/ccache\n"
        "RUN chmod 0755 /usr/bin/ccache &&\\\n"
        "    ccache --version | grep -F \"ccache version ${CCACHE_VERSION}\"\n\n"
        'ENV PATH="/usr/lib/ccache:${PATH}"\n\n'
        "FROM builder AS libheif-builder\n",
        "builder stage boundary",
    )


def render(source: str, profile: str) -> str:
    if profile == "baseline":
        return source
    if profile == "bundler":
        return verify_bundler_cache(source)
    if profile == "ccache":
        return add_ccache(source)
    if profile == "bundler-ccache":
        return add_ccache(verify_bundler_cache(source))
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
