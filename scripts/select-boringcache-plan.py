#!/usr/bin/env python3
"""Materialize one committed Discourse plan with its isolated cache cohort."""

from __future__ import annotations

import argparse
import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_IMAGE = ROOT / "docker-upstream/image"
CACHE_TAG = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,127}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("plan")
    parser.add_argument("--cache-tag", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if CACHE_TAG.fullmatch(args.cache_tag) is None:
        raise SystemExit(f"Invalid cache tag: {args.cache_tag}")

    plan_dir = (ROOT / "plans" / args.plan).resolve()
    if plan_dir.parent != (ROOT / "plans").resolve():
        raise SystemExit(f"Unknown plan: {args.plan}")

    source = plan_dir / ".boringcache.toml"
    text = source.read_text()
    updated, replacements = re.subn(
        r'^tag = "[^"]+"$',
        f'tag = "{args.cache_tag}"',
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if replacements != 1:
        raise SystemExit(f"Plan must declare exactly one Docker tag: {source}")

    destination = UPSTREAM_IMAGE / ".boringcache.toml"
    if destination.exists():
        raise SystemExit(f"Refusing to overwrite {destination}")
    destination.write_text(updated)

    with destination.open("rb") as config_file:
        materialized_tag = tomllib.load(config_file)["adapters"]["docker"]["tag"]
    if materialized_tag != args.cache_tag:
        raise SystemExit(f"Materialized the wrong cache tag: {materialized_tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
