#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
MCP_MODE="${MCP_MODE:-mcp}"

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  echo ".venv is missing. Run scripts/setup.sh first."
  exit 1
fi

case "$MCP_MODE" in
  mcp|mcp-write)
    ;;
  *)
    echo "MCP_MODE must be 'mcp' or 'mcp-write'"
    exit 1
    ;;
esac

cd "$ROOT_DIR"

"$VENV_DIR/bin/python" - <<'PY'
import json
import os
import subprocess
import sys

root_dir = os.getcwd()
venv_python = os.path.join(root_dir, ".venv", "bin", "python")
mcp_mode = os.environ.get("MCP_MODE", "mcp")
cmd = [venv_python, "-m", "intelligence.cli", mcp_mode]

proc = subprocess.Popen(
    cmd,
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    cwd=root_dir,
)

assert proc.stdin is not None
assert proc.stdout is not None
assert proc.stderr is not None

def send(payload: dict) -> dict:
    proc.stdin.write(json.dumps(payload) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    if not line:
        stderr = proc.stderr.read()
        raise RuntimeError(f"MCP server closed unexpectedly:\n{stderr}")
    return json.loads(line)

try:
    initialize = send({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "ops-signals-mcp-smoke-test", "version": "1.0.0"},
        },
    })
    if "result" not in initialize:
        raise RuntimeError(f"initialize failed: {initialize}")

    tools = send({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
        "params": {},
    })
    if "result" not in tools or "tools" not in tools["result"]:
        raise RuntimeError(f"tools/list failed: {tools}")

    tool_names = [tool.get("name") for tool in tools["result"]["tools"]]
    if not tool_names:
        raise RuntimeError("tools/list returned no tools")

    print(f"MCP smoke test passed ({mcp_mode})")
    print(f"Tools: {', '.join(tool_names)}")
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
PY
