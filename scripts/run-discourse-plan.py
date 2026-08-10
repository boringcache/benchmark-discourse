#!/usr/bin/env python3
"""Execute one committed Discourse Bake plan through the selected cache provider."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("plan")
    parser.add_argument("--provider", choices=("actions-cache", "boringcache"), required=True)
    parser.add_argument("--cache-scope", required=True)
    parser.add_argument("--read-only", action="store_true")
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

    if args.provider == "actions-cache":
        if "--no-cache" not in command:
            command.extend(
                (
                    f"--set=*.cache-from=type=gha,scope={args.cache_scope}",
                    f"--set=*.cache-to=type=gha,scope={args.cache_scope},mode=max",
                )
            )
        return subprocess.run(command, cwd=plan_dir, check=False).returncode

    boringcache = [
        "boringcache",
        "docker",
        "--tag",
        args.cache_scope,
        "--fail-on-cache-error",
    ]
    if args.read_only:
        boringcache.append("--read-only")
    return subprocess.run(boringcache, cwd=plan_dir, check=False, env=os.environ.copy()).returncode


if __name__ == "__main__":
    raise SystemExit(main())
