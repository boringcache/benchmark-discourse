#!/usr/bin/env python3
"""Execute Discourse's upstream Bake targets individually through BoringCache."""

from __future__ import annotations

import argparse
import subprocess
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_IMAGE = ROOT / "docker-upstream/image"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("plan")
    parser.add_argument("--read-only", action="store_true")
    parser.add_argument("--mount-cache", action="store_true")
    parser.add_argument("--tool-cache-ccache", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def load_plan(plan_dir: Path) -> tuple[list[str], list[str]]:
    with (plan_dir / ".boringcache.toml").open("rb") as config_file:
        command = tomllib.load(config_file)["adapters"]["docker"]["command"]
    if command[:3] != ["docker", "buildx", "bake"]:
        raise SystemExit(f"{plan_dir} is not a Docker Bake plan")
    targets = [argument for argument in command[3:] if not argument.startswith("-")]
    if not targets:
        raise SystemExit(f"{plan_dir} does not declare any Bake targets")
    options = [argument for argument in command[3:] if argument.startswith("-")]
    return targets, options


def main() -> int:
    args = parse_args()
    plan_dir = (ROOT / "plans" / args.plan).resolve()
    if plan_dir.parent != (ROOT / "plans").resolve():
        raise SystemExit(f"Unknown plan: {args.plan}")

    boringcache_args: list[str] = []
    if args.read_only:
        boringcache_args.append("--read-only")
    if args.mount_cache:
        boringcache_args.append("--mount-cache")
    if args.tool_cache_ccache:
        boringcache_args.extend(("--tool-cache", "ccache"))
    if args.dry_run:
        boringcache_args.append("--dry-run")

    targets, plan_options = load_plan(plan_dir)
    for target in targets:
        command = [
            "boringcache",
            "docker",
            *boringcache_args,
            "--",
            "docker",
            "buildx",
            "bake",
            target,
            *(plan_options or ["--load"]),
        ]
        result = subprocess.run(command, cwd=UPSTREAM_IMAGE, check=False)
        if result.returncode != 0:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
