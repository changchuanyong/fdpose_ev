#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

exec "$HOME/venvs/ev-charging-d415-gpu/bin/python" -u -B apps/jetson_foundationpose_d415.py \
  --serial 349222063070 \
  --mesh assets/mesh/socket_mod.PLY \
  --geometry config/geometry/socket_openings_ply.json \
  --weights weights/best.pt \
  --output "artifacts/d415-live-$(date +%Y%m%d-%H%M%S)" \
  --show --frames 0 "$@"
