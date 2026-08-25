#!/usr/bin/env bash
# Runs the sidebar with its dependencies provided by nix, without building it first.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec nix-shell -p gtk3 gtk-layer-shell webkitgtk_4_1 gobject-introspection \
    wl-clipboard xclip hunspell hunspellDicts.en_US \
    "python3.withPackages(ps: [ps.pygobject3 ps.pycairo ps.xlib])" \
    --run "exec python3 '$HERE/linux-sidebar' $(printf '%q ' "$@")"
