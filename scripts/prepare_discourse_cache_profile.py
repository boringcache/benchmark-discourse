#!/usr/bin/env python3
"""Apply one benchmark-only cache profile to Discourse's pinned Dockerfile."""

from __future__ import annotations

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "docker-upstream/image/base/Dockerfile"
PROFILES = ("baseline", "bundler", "ccache")


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
        "ARG TARGETARCH\n"
        "ARG CCACHE_VERSION=4.13.6\n"
        "RUN case \"${TARGETARCH}\" in \\\n"
        "      amd64) ccache_arch=x86_64; ccache_sha=567b1b648411819590f918f045218c92da14418bdec3b30db94a3b4f5d77cf13 ;; \\\n"
        "      arm64) ccache_arch=aarch64; ccache_sha=fae67fb810e1f0d390409af6603355483572229e19183e68574cd0f851a6fb98 ;; \\\n"
        "      *) echo \"Unsupported ccache architecture: ${TARGETARCH}\" >&2; exit 2 ;; \\\n"
        "    esac &&\\\n"
        "    ccache_archive=\"ccache-${CCACHE_VERSION}-linux-${ccache_arch}-glibc.tar.gz\" &&\\\n"
        "    wget --tries=5 --timeout=30 --waitretry=2 \\\n"
        "      \"https://github.com/ccache/ccache/releases/download/v${CCACHE_VERSION}/${ccache_archive}\" \\\n"
        "      -O \"/tmp/${ccache_archive}\" &&\\\n"
        "    echo \"${ccache_sha}  /tmp/${ccache_archive}\" | sha256sum --check &&\\\n"
        "    tar xzf \"/tmp/${ccache_archive}\" -C /tmp &&\\\n"
        "    install -m 0755 \\\n"
        "      \"/tmp/ccache-${CCACHE_VERSION}-linux-${ccache_arch}-glibc/ccache\" \\\n"
        "      /usr/bin/ccache &&\\\n"
        "    rm -rf /tmp/ccache-* &&\\\n"
        "    ccache --version | grep -F \"ccache version ${CCACHE_VERSION}\"\n\n"
        'ENV PATH="/usr/lib/ccache:${PATH}"\n\n'
        "FROM builder AS libheif-builder\n",
        "builder stage boundary",
    )


def render(source: str, profile: str) -> str:
    if profile == "baseline":
        return source
    if profile == "bundler":
        return add_bundler_cache(source)
    if profile == "ccache":
        return add_ccache(source)
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
