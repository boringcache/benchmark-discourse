#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
scope="${1:-}"

if [[ ! "$scope" =~ ^[a-z0-9][a-z0-9._-]+$ ]]; then
  echo "Expected a lowercase benchmark cache scope, got: ${scope:-<empty>}" >&2
  exit 1
fi

config_path="${repo_root}/.boringcache.toml"
grep -Fq 'tag = "discourse-docker-local"' "$config_path" || {
  echo "Missing expected local Docker tag in ${config_path}" >&2
  exit 1
}
sed -i "s/tag = \"discourse-docker-local\"/tag = \"${scope}-docker\"/" "$config_path"
echo "Scoped the BoringCache Docker tag to ${scope}."
