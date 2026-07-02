#!/usr/bin/env bash
# Deploy the runtime into the UE project's Content/Python (the repo is source of truth).
#   sync-runtime.sh          — copy runtime/ue_buttons + init_unreal.py into the project
# The editor auto-runs Content/Python/init_unreal.py at startup; with DEV_RELOAD on,
# dispatch hot-reloads handler modules, so most edits need only a re-sync, no restart.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT="${UE_PROJECT_DIR:-/mnt/c/Users/anvil/Documents/Unreal Projects/UEButtons}"
DEST="$PROJECT/Content/Python"

if [[ ! -d "$PROJECT" ]]; then
  echo "UE project not found at: $PROJECT" >&2
  echo "Set UE_PROJECT_DIR to override." >&2
  exit 1
fi

mkdir -p "$DEST/ue_buttons"
# runtime package
rm -rf "$DEST/ue_buttons"
cp -r "$REPO/runtime/ue_buttons" "$DEST/ue_buttons"
# bootstrap (only if the repo ships one; keep any hand-edited project init otherwise)
if [[ -f "$REPO/runtime/init_unreal.py" ]]; then
  cp "$REPO/runtime/init_unreal.py" "$DEST/init_unreal.py"
fi

echo "synced runtime → $DEST"
find "$DEST/ue_buttons" -name '*.py' | sed "s|$DEST/||"
