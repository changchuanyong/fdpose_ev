#!/usr/bin/env bash
# FoundationPose 在 Jetson（JetPack 6.2 / L4T R36.5.2 / CUDA 12.6 / aarch64）上的部署脚本。
#
# 在 Jetson 本地执行，只写 $HOME，不安装或修改任何系统组件。
# 用法：
#   bash jetson_setup.sh repo    # 固定提交并应用补丁
#   bash jetson_setup.sh venv    # 创建 venv，装 torch/torchvision 与 requirements
#   bash jetson_setup.sh ext     # 构建 pytorch3d 与 nvdiffrast
#   bash jetson_setup.sh mycpp   # 构建 mycpp 扩展
#   bash jetson_setup.sh all     # 依次执行以上四步
#
# 依赖的前置文件（由 Windows 侧上传）：
#   $WORK/foundationpose-windows.patch
#   $WORK/config/runtime-jetson.txt
set -euo pipefail

REPO="${REPO:-$HOME/fdonpose/third_party/FoundationPose}"
VENV="${VENV:-$HOME/venvs/foundationpose}"
WORK="${WORK:-$HOME/foundationpose-deploy}"
PATCH="${PATCH:-$WORK/foundationpose-windows.patch}"
REQ="${REQ:-$WORK/config/runtime-jetson.txt}"
COMMIT="a1b694b83e633c2cb6115b9063d940a687759392"
TORCH_INDEX="${TORCH_INDEX:-https://pypi.jetson-ai-lab.io/jp6/cu126}"
TORCH_VERSION="${TORCH_VERSION:-2.9.1}"
TORCHVISION_VERSION="${TORCHVISION_VERSION:-0.24.1}"
# torch 2.9.1 Jetson 轮子的 libtorch_cuda.so 依赖 libcudss.so.0，而 JetPack 6.2 不自带 cuDSS。
CUDSS_VERSION="${CUDSS_VERSION:-0.8.0.10}"
# 可选下载代理，例如 http://127.0.0.1:7897（本机 Clash）。直连 jetson 轮子源只有 20–75 KB/s。
PROXY="${PROXY:-}"
PY="$VENV/bin/python"
STAGE="${1:-all}"

log() { printf '[%s] %s\n' "$(date -Is)" "$*"; }
die() { log "ERROR: $*"; exit 1; }
if [ -n "$PROXY" ]; then
  export http_proxy="$PROXY" https_proxy="$PROXY"
  log "using proxy $PROXY"
fi

stage_repo() {
  [ -f "$PATCH" ] || die "patch not found: $PATCH"
  if [ ! -d "$REPO/.git" ]; then
    log "cloning NVlabs/FoundationPose into $REPO"
    git clone https://github.com/NVlabs/FoundationPose.git "$REPO"
  fi
  log "checking out $COMMIT"
  git -C "$REPO" checkout --force "$COMMIT" >/dev/null 2>&1 \
    || { git -C "$REPO" fetch --all --quiet; git -C "$REPO" checkout --force "$COMMIT"; }
  [ "$(git -C "$REPO" rev-parse HEAD)" = "$COMMIT" ] || die "HEAD is not $COMMIT"
  git -C "$REPO" apply "$PATCH" || die "patch failed to apply"
  local changed
  changed="$(git -C "$REPO" diff --name-only | wc -l)"
  [ "$changed" -eq 5 ] || die "expected 5 patched files, got $changed"
  log "repo ready: $(git -C "$REPO" rev-parse --short HEAD) + patch (5 files)"
}

stage_venv() {
  [ -f "$REQ" ] || die "requirements not found: $REQ"
  if [ ! -x "$PY" ]; then
    log "creating venv $VENV"
    /usr/bin/python3.10 -m venv "$VENV"
  fi
  log "upgrading pip/setuptools/wheel"
  "$PY" -m pip install -q --upgrade pip setuptools wheel
  # Jetson 轮子源单连接很慢，优先用 jetson_fetch_wheels.sh 并行下载好的本地轮子。
  local torch_wheel torchvision_wheel
  torch_wheel="$(ls "$WORK"/wheels/torch-"$TORCH_VERSION"-cp310-cp310-linux_aarch64.whl 2>/dev/null | head -n 1)"
  torchvision_wheel="$(ls "$WORK"/wheels/torchvision-"$TORCHVISION_VERSION"-cp310-cp310-linux_aarch64.whl 2>/dev/null | head -n 1)"
  if [ -n "$torch_wheel" ] && [ -n "$torchvision_wheel" ]; then
    log "installing torch/torchvision from local wheels"
    "$PY" -m pip install "$torch_wheel" "$torchvision_wheel"
  else
    log "installing torch==$TORCH_VERSION torchvision==$TORCHVISION_VERSION from $TORCH_INDEX"
    "$PY" -m pip install "torch==$TORCH_VERSION" "torchvision==$TORCHVISION_VERSION" --index-url "$TORCH_INDEX"
  fi
  "$PY" -m pip install -q pybind11 ninja
  log "installing cuDSS $CUDSS_VERSION and linking it into torch/lib"
  "$PY" -m pip install -q "nvidia-cudss-cu12==$CUDSS_VERSION"
  local site="$VENV/lib/python3.10/site-packages"
  for lib in "$site"/nvidia/*/lib/libcudss*.so*; do
    [ -e "$lib" ] && ln -sf "$lib" "$site/torch/lib/$(basename "$lib")"
  done
  build_cusolver_shim "$site"
  log "installing requirements from $REQ"
  "$PY" -m pip install -r "$REQ"
  "$PY" -m pip freeze > "$WORK/logs/pip-freeze.txt"
  log "venv ready: $("$PY" -c 'import torch;print(torch.__version__)')"
}

# torch 2.9.1 的 Jetson 轮子按 CUDA 12.8/12.9 构建，libtorch_cuda_linalg.so 需要
# cusolverDnXsyevBatched*；JetPack 6.2 的 CUDA 12.6 没有这两个符号，dlopen 会失败。
# 这里只补这两个符号（FoundationPose 只用 inv/solve，不调用 batched eigh），
# 并用 .pth 在解释器启动时以 RTLD_GLOBAL 预加载，避免依赖 LD_LIBRARY_PATH。
build_cusolver_shim() {
  local site="$1"
  local dir="$WORK/shim"
  mkdir -p "$dir"
  cat > "$dir/jetpack_cusolver_compat.c" <<'EOS'
#include <stdio.h>
#include <stdlib.h>

void cusolverDnXsyevBatched(void) {
  fprintf(stderr, "cusolverDnXsyevBatched unavailable on JetPack 6.2 CUDA 12.6\n");
  abort();
}

int cusolverDnXsyevBatched_bufferSize(void) {
  return 1;
}
EOS
  cat > "$dir/jetpack_cusolver_compat.map" <<'EOS'
libcusolver.so.11 {
  global:
    cusolverDnXsyevBatched;
    cusolverDnXsyevBatched_bufferSize;
  local: *;
};
EOS
  log "building cuSolver compatibility shim"
  gcc -shared -fPIC -O2 -o "$site/libcusolver_jetpack_compat.so" \
    "$dir/jetpack_cusolver_compat.c" -Wl,--version-script="$dir/jetpack_cusolver_compat.map"
  cat > "$site/zz_jetpack_cusolver_preload.py" <<'EOS'
import ctypes
import os

_shim = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libcusolver_jetpack_compat.so")
if os.path.exists(_shim):
    try:
        ctypes.CDLL(_shim, mode=ctypes.RTLD_GLOBAL)
    except OSError:
        pass
EOS
  printf 'import zz_jetpack_cusolver_preload\n' > "$site/zz_jetpack_cusolver.pth"
}

stage_ext() {
  export CUDA_HOME="${CUDA_HOME:-/usr/local/cuda-12.6}"
  # venv/bin 必须在 PATH 前面，torch 的 BuildExtension 才能找到 pip 装的 ninja 并行编译。
  export PATH="$VENV/bin:$CUDA_HOME/bin:$PATH"
  export TORCH_CUDA_ARCH_LIST="${TORCH_CUDA_ARCH_LIST:-8.7}"
  export MAX_JOBS="${MAX_JOBS:-10}"
  [ -x "$CUDA_HOME/bin/nvcc" ] || die "nvcc not found under $CUDA_HOME"
  command -v ninja >/dev/null || die "ninja not on PATH (pip install ninja)"
  # 当前网络下 git://https 大传输会 GnuTLS 中断，改用 codeload tarball（可走 PROXY）。
  local src="$WORK/src"
  local p3d_sha="e4ad6e5687a360ccdc6ebd91348e8dbbac97bf31"
  local ndr_sha="253ac4fcea7de5f396371124af597e6cc957bfae"
  mkdir -p "$src"
  local curl_cmd=(curl -fsSL --retry 5 --retry-delay 5)
  if [ -n "$PROXY" ]; then curl_cmd+=(--proxy "$PROXY"); fi
  fetch_tarball() {
    local org="$1" name="$2" sha="$3"
    [ -d "$src/$name-$sha" ] && return 0
    log "downloading $org/$name@$sha"
    "${curl_cmd[@]}" -o "$src/$name.tar.gz" \
      "https://codeload.github.com/$org/$name/tar.gz/$sha" \
      || die "tarball download failed: $name"
    tar -xzf "$src/$name.tar.gz" -C "$src"
    rm -f "$src/$name.tar.gz"
  }
  fetch_tarball facebookresearch pytorch3d "$p3d_sha"
  fetch_tarball NVlabs nvdiffrast "$ndr_sha"
  log "building pytorch3d (CUDA_HOME=$CUDA_HOME arch=$TORCH_CUDA_ARCH_LIST MAX_JOBS=$MAX_JOBS)"
  "$PY" -m pip install --no-build-isolation "$src/pytorch3d-$p3d_sha"
  log "building nvdiffrast"
  "$PY" -m pip install --no-build-isolation "$src/nvdiffrast-$ndr_sha"
  log "extensions installed"
}

stage_mycpp() {
  log "building mycpp"
  rm -rf "$REPO/mycpp/build"
  mkdir -p "$REPO/mycpp/build"
  cmake -S "$REPO/mycpp" -B "$REPO/mycpp/build" \
    -DCMAKE_BUILD_TYPE=Release \
    -Dpybind11_DIR="$("$PY" -m pybind11 --cmakedir)"
  cmake --build "$REPO/mycpp/build" -j"$(nproc)"
  ls "$REPO"/mycpp/build/mycpp*.so >/dev/null || die "mycpp extension missing"
  log "mycpp ready: $(ls "$REPO"/mycpp/build/mycpp*.so)"
}

mkdir -p "$WORK/logs"
case "$STAGE" in
  repo)  stage_repo ;;
  venv)  stage_venv ;;
  ext)   stage_ext ;;
  mycpp) stage_mycpp ;;
  all)   stage_repo; stage_venv; stage_ext; stage_mycpp ;;
  *)     die "unknown stage: $STAGE (repo|venv|ext|mycpp|all)" ;;
esac
log "stage '$STAGE' done"
