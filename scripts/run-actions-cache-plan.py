#!/usr/bin/env python3
"""Execute the committed Discourse Bake graph with GitHub Actions Cache."""

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
    parser.add_argument("--cache-scope", required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def load_command(plan_dir: Path) -> list[str]:
    with (plan_dir / ".boringcache.toml").open("rb") as config_file:
        command = tomllib.load(config_file)["adapters"]["docker"]["command"]
    if command[:3] != ["docker", "buildx", "bake"]:
        raise SystemExit(f"{plan_dir} is not a Docker Bake plan")
    return command


def main() -> int:
    args = parse_args()
    plan_dir = (ROOT / "plans" / args.plan).resolve()
    if plan_dir.parent != (ROOT / "plans").resolve():
        raise SystemExit(f"Unknown plan: {args.plan}")
    command = load_command(plan_dir)

    command.extend(
        (
            f"--set=*.cache-from=type=gha,scope={args.cache_scope}",
            f"--set=*.cache-to=type=gha,scope={args.cache_scope},mode=max",
        )
    )
    if args.dry_run:
        command.append("--print")
    return subprocess.run(command, cwd=UPSTREAM_IMAGE, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
