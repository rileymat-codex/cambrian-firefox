#!/usr/bin/env bash
set -euo pipefail
source_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
export MOZCONFIG="${MOZCONFIG:-$source_root/cambrian/mozconfig}"
export MOZ_OBJDIR="${MOZ_OBJDIR:-$source_root/obj-cambrian-firefox}"
mozbuild_root=${MOZBUILD_ROOT:-${HOME:?HOME must be set}/.mozbuild}
export PATH="$mozbuild_root/cargo/bin:$PATH"
export RUSTUP_HOME="${RUSTUP_HOME:-$mozbuild_root/rustup-home}"
export CARGO_HOME="${CARGO_HOME:-$mozbuild_root/cargo}"
cd "$source_root"
exec ./mach build "$@"
