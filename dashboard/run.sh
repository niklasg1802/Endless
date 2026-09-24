#!/usr/bin/env bash
# Run the Endless dashboard.
#
# Stdlib-only python; binds loopback by default and requires a token on every
# route. The token is generated on first run into dashboard/.token (0600) and
# printed in the startup banner.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export ENDLESS_MODELS_DIR="${ENDLESS_MODELS_DIR:-$(dirname "$HERE")/models}"
exec python3 "$HERE/app.py"
