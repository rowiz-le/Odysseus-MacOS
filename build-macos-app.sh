#!/usr/bin/env bash
set -euo pipefail

# Compatibility entry point. The canonical builder creates a portable app
# payload and first-launch environment under Application Support; the previous
# launcher baked this checkout's path and venv into the distributed app.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "Using the portable Odysseus macOS distribution builder."
exec "$ROOT_DIR/scripts/build_macos_distribution.sh" "$@"
