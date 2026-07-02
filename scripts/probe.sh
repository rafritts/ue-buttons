#!/usr/bin/env bash
# Probe the UE Remote Control bridge. Usage:
#   probe.sh              — is the API alive?
#   probe.sh py 'CODE'    — run editor Python, print LogOutput
set -euo pipefail

HOST="${UE_RC_HOST:-localhost}"
BASE="http://$HOST:30010"

if [[ "${1:-}" == "py" ]]; then
  shift
  jq -n --arg cmd "$*" '{
    objectPath: "/Script/PythonScriptPlugin.Default__PythonScriptLibrary",
    functionName: "ExecutePythonCommandEx",
    parameters: { PythonCommand: $cmd, PythonCommandExecutionMode: "ExecuteStatement" }
  }' | curl -s -X PUT "$BASE/remote/object/call" \
         -H "Content-Type: application/json" -d @- \
     | jq -r '.LogOutput[]?.Output // empty'
else
  curl -s "$BASE/remote/info" | jq .
fi
