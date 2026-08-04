#!/usr/bin/env bash

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PROJECT_ROOT

export VIRTUAL_ENV="$PROJECT_ROOT/.venv"
export PATH="$VIRTUAL_ENV/bin:$PATH"

export XDG_CACHE_HOME="$PROJECT_ROOT/.cache"
export PIP_CACHE_DIR="$PROJECT_ROOT/.cache/pip"
export UV_CACHE_DIR="$PROJECT_ROOT/.cache/uv"
export UV_PYTHON_INSTALL_DIR="$PROJECT_ROOT/.cache/uv/python"
export COREPACK_HOME="$PROJECT_ROOT/.cache/corepack"
export PNPM_HOME="$PROJECT_ROOT/.cache/pnpm/home"
export PNPM_STORE_DIR="$PROJECT_ROOT/.cache/pnpm/store"
export HF_HOME="$PROJECT_ROOT/.cache/huggingface"
export HUGGINGFACE_HUB_CACHE="$PROJECT_ROOT/.cache/huggingface/hub"
export TRANSFORMERS_CACHE="$PROJECT_ROOT/.cache/huggingface/transformers"
export TORCH_HOME="$PROJECT_ROOT/.cache/torch"
export TRITON_CACHE_DIR="$PROJECT_ROOT/.cache/triton"
export NGC_CLI_HOME="$PROJECT_ROOT/.cache/ngc"
export TMPDIR="$PROJECT_ROOT/.cache/tmp"

export NIM_LLM_CACHE="$PROJECT_ROOT/.cache/nim/nemotron-nano-9b-v2"
export NIM_VLM_CACHE="$PROJECT_ROOT/.cache/nim/cosmos3-nano-reasoner"
export TENSORRT_CACHE="$PROJECT_ROOT/.cache/tensorrt"

# Keep a hard 5 GiB VRAM reserve for other workloads sharing this GPU.
export VSS_GPU_RESERVED_MEMORY_MIB="${VSS_GPU_RESERVED_MEMORY_MIB:-5120}"
