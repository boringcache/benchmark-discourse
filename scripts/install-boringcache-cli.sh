#!/usr/bin/env bash
set -euo pipefail

version="${1:-v1.18.1}"
case "$(uname -m)" in
  x86_64|amd64) asset="boringcache-linux-amd64" ;;
  aarch64|arm64) asset="boringcache-linux-arm64" ;;
  *) echo "Unsupported BoringCache CLI architecture: $(uname -m)" >&2; exit 1 ;;
esac

install_dir="${HOME}/.local/bin"
download_dir="$(mktemp -d)"
trap 'rm -rf "$download_dir"' EXIT
release_url="https://github.com/boringcache/cli/releases/download/${version}"

mkdir -p "$install_dir"
curl -fsSL "${release_url}/${asset}" -o "${download_dir}/${asset}"
curl -fsSL "${release_url}/SHA256SUMS" -o "${download_dir}/SHA256SUMS"
(
  cd "$download_dir"
  grep "  ${asset}$" SHA256SUMS | sha256sum -c -
)
install -m 0755 "${download_dir}/${asset}" "${install_dir}/boringcache"

if [[ -n "${GITHUB_PATH:-}" ]]; then
  echo "$install_dir" >> "$GITHUB_PATH"
fi
"${install_dir}/boringcache" --version
