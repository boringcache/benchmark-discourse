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
    parser.add_argument("--ccache-tag", required=True)
    return parser.parse_args()


def replace_adapter_tag(text: str, adapter: str, tag: str, source: Path) -> str:
    lines = text.splitlines(keepends=True)
    section = f"[adapters.{adapter}]"
    in_section = False
    replacements = 0

    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_section = stripped == section
            continue
        if in_section and stripped.startswith("tag = "):
            ending = "\n" if line.endswith("\n") else ""
            lines[index] = f'tag = "{tag}"{ending}'
            replacements += 1

    if replacements != 1:
        raise SystemExit(f"Plan must declare exactly one {adapter} tag: {source}")
    return "".join(lines)


def main() -> int:
    args = parse_args()
    for label, tag in (("cache", args.cache_tag), ("ccache", args.ccache_tag)):
        if CACHE_TAG.fullmatch(tag) is None:
            raise SystemExit(f"Invalid {label} tag: {tag}")
    if args.cache_tag == args.ccache_tag:
        raise SystemExit("Docker and ccache tags must be distinct")

    plan_dir = (ROOT / "plans" / args.plan).resolve()
    if plan_dir.parent != (ROOT / "plans").resolve():
        raise SystemExit(f"Unknown plan: {args.plan}")

    source = plan_dir / ".boringcache.toml"
    text = source.read_text()
    updated = replace_adapter_tag(text, "docker", args.cache_tag, source)
    updated = replace_adapter_tag(updated, "ccache", args.ccache_tag, source)

    destination = UPSTREAM_IMAGE / ".boringcache.toml"
    if destination.exists():
        raise SystemExit(f"Refusing to overwrite {destination}")
    destination.write_text(updated)

    with destination.open("rb") as config_file:
        adapters = tomllib.load(config_file)["adapters"]
    materialized_tags = {
        "docker": adapters["docker"]["tag"],
        "ccache": adapters["ccache"]["tag"],
    }
    expected_tags = {"docker": args.cache_tag, "ccache": args.ccache_tag}
    if materialized_tags != expected_tags:
        raise SystemExit(f"Materialized the wrong cache tags: {materialized_tags}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
