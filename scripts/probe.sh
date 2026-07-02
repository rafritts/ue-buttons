#!/usr/bin/env bash
# Probe the UE Remote Control bridge. Usage:
#   probe.sh              — is the API alive?
#   probe.sh py 'CODE'    — run editor Python, print LogOutput
set -euo pipefail

HOST="${UE_RC_HOST:-localhost}"
BASE="http://$HOST:30010"

if [[ "${1:-}" == "py" ]]; then
  shift
  python3 - "$@" <<'EOF'
import json, sys, urllib.request, os
cmd = " ".join(sys.argv[1:])
body = json.dumps({
    "objectPath": "/Script/PythonScriptPlugin.Default__PythonScriptLibrary",
    "functionName": "ExecutePythonCommandEx",
    "parameters": {"PythonCommand": cmd, "PythonCommandExecutionMode": "ExecuteStatement"},
}).encode()
base = "http://%s:30010" % os.environ.get("UE_RC_HOST", "localhost")
req = urllib.request.Request(base + "/remote/object/call", data=body,
                             headers={"Content-Type": "application/json"}, method="PUT")
resp = json.load(urllib.request.urlopen(req, timeout=30))
for line in resp.get("LogOutput", []):
    print(line.get("Output", ""), end="")
if not resp.get("ReturnValue", True):
    sys.exit(1)
EOF
else
  curl -s "$BASE/remote/info" | python3 -m json.tool | head -5
fi
