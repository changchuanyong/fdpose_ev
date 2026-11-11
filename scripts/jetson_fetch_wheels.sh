#!/usr/bin/env bash
# 从 NVIDIA Jetson 轮子源下载 torch / torchvision 轮子。
#
# 实测：该源在实验室直连时单连接只有 20–75 KB/s，且不支持 HTTP Range，
# 无法分块并行；经本机已运行的代理（如 Clash mixed-port 127.0.0.1:7897）可达 2 MB/s。
# 因此脚本支持 PROXY 环境变量，并按索引页给出的 sha256 校验完整性。
# 在 Jetson 上执行；只写 $HOME。
set -euo pipefail

WHEELS="${WHEELS:-$HOME/foundationpose-deploy/wheels}"
INDEX="${INDEX:-https://pypi.jetson-ai-lab.io/jp6/cu126}"
TORCH_VERSION="${TORCH_VERSION:-2.9.1}"
TORCHVISION_VERSION="${TORCHVISION_VERSION:-0.24.1}"
PROXY="${PROXY:-}"

log() { printf '[%s] %s\n' "$(date -Is)" "$*"; }
die() { log "ERROR: $*"; exit 1; }

CURL=(curl -fsSL --retry 5 --retry-delay 5 --retry-all-errors)
if [ -n "$PROXY" ]; then
  CURL+=(--proxy "$PROXY")
  log "using proxy $PROXY"
fi

fetch() {
  local proj="$1" pattern="$2"
  local page href url_part sha name out
  page="$("${CURL[@]}" "$INDEX/+simple/$proj/")" || die "index unreachable: $proj"
  href="$(printf '%s' "$page" | grep -oE 'href="[^"]*"' | sed -e 's/^href="//' -e 's/"$//' | grep -E "$pattern" | head -n 1)"
  [ -n "$href" ] || die "no wheel for $proj matching $pattern"
  url_part="${href%%#*}"
  sha="${href##*sha256=}"
  url_part="${url_part#../../}"
  name="$(basename "$url_part")"
  out="$WHEELS/$name"
  if [ -f "$out" ] && [ "$(sha256sum "$out" | cut -d' ' -f1)" = "$sha" ]; then
    log "cached $name"
    return
  fi
  log "downloading $name"
  rm -f "$out.tmp"
  "${CURL[@]}" -C - -o "$out.tmp" "$INDEX/$url_part" || die "download failed: $name"
  [ "$(sha256sum "$out.tmp" | cut -d' ' -f1)" = "$sha" ] || die "sha256 mismatch for $name"
  mv "$out.tmp" "$out"
  log "verified $name"
}

mkdir -p "$WHEELS"
fetch torch "torch-${TORCH_VERSION}-cp310-cp310-linux_aarch64\\.whl"
fetch torchvision "torchvision-${TORCHVISION_VERSION}-cp310-cp310-linux_aarch64\\.whl"
log "wheels ready in $WHEELS"
