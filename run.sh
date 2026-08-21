#!/usr/bin/env bash
# Runs the sidebar with its GTK3 and layer-shell dependencies provided by nix.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec nix-shell -p gtk3 gtk-layer-shell gobject-introspection wl-clipboard xclip \
    "python3.withPackages(ps: [ps.pygobject3 ps.pycairo])" \
    --run "exec python3 '$HERE/sidebar_scratchpad.py' $(printf '%q ' "$@")"
