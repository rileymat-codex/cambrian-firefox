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
./mach package "$@"
if [[ -n "${CAMBRIAN_NATIVE_ARCHIVE:-}" ]]; then
  archive=$CAMBRIAN_NATIVE_ARCHIVE
else
  archive=$(find "$MOZ_OBJDIR/dist" -maxdepth 1 -type f \( -name 'firefox-*.tar.xz' -o -name 'firefox-*.tar.bz2' -o -name 'firefox-*.tar.gz' \) -printf '%T@ %p\n' | sort -nr | head -n1 | cut -d' ' -f2-)
fi
if [[ -z "$archive" ]]; then
  printf 'mach package produced no native release archive in %s/dist\n' "$MOZ_OBJDIR" >&2
  exit 1
fi
output=${CAMBRIAN_PACKAGE_OUTPUT:-$source_root/CambrianFirefox-157.0-ubuntu.tar.xz}
python3 "$source_root/cambrian/stage_package.py" "$archive" "$output" --source-root "$source_root" --objdir "$MOZ_OBJDIR" --mozconfig "$MOZCONFIG"
