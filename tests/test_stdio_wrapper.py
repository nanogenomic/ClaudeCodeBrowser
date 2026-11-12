"""Tests for mcp-server/stdio_wrapper.py (the MCP stdio entry point)."""
import json
import os
import subprocess
import sys
from pathlib import Path

MCP_DIR = Path(__file__).resolve().parent.parent / "mcp-server"

# Runs the wrapper's real message loop over real pipes, with the HTTP server
# replaced by an echo so the test needs no browser.
_ECHO_WRAPPER = f"""
import sys
sys.path.insert(0, {str(MCP_DIR)!r})
import stdio_wrapper as w
w.start_http_server = lambda: True
w.call_tool = lambda name, arguments: {{"echo": arguments}}
w.main()
"""


def _call_through_wrapper(arguments, stdio_encoding):
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": "browser_type", "arguments": arguments}}
    env = {**os.environ, "PYTHONIOENCODING": stdio_encoding}
    env.pop("PYTHONUTF8", None)
    proc = subprocess.run(
        [sys.executable, "-c", _ECHO_WRAPPER],
        input=(json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"),
        capture_output=True, env=env, timeout=30, check=True,
    )
    response = json.loads(proc.stdout.decode("utf-8").splitlines()[0])
    return json.loads(response["result"]["content"][0]["text"])["echo"]


def test_non_ascii_arguments_survive_a_non_utf8_console():
    # MCP clients send UTF-8; Windows pipes default to the ANSI code page (cp1252),
    # which turned "Nächster" into "NÃ¤chster" (issue #5).
    text = "Nächster Schritt, Größe 62×71 – Schließen"
    assert _call_through_wrapper({"text": text}, "cp1252") == {"text": text}
