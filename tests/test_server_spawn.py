"""Issue #26: on Windows the native host could not restart a crashed server.

The child inherited the native host's stdin, i.e. Firefox's native-messaging
pipe, while another thread was blocked reading it. The new python.exe then hung
while setting up its own stdio (right after `import io`), before running any of
server.py. Restarts from the wrapper inherit Claude Code's MCP pipe the same way.
"""
import subprocess
import sys

import pytest


class Spawned(Exception):
    """Raised by the fake Popen to stop after the spawn under test."""


@pytest.fixture
def capture_popen(monkeypatch):
    calls = []

    def fake_popen(args, **kwargs):
        calls.append(kwargs)
        raise Spawned
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    return calls


def test_native_host_starts_the_server_without_its_stdin(native_host, capture_popen, monkeypatch):
    monkeypatch.setattr(native_host, "restart_attempts", 0)
    native_host.start_mcp_server()  # logs and returns False after our Spawned

    assert capture_popen, "server was not spawned"
    assert capture_popen[0].get("stdin") is subprocess.DEVNULL


def test_wrapper_starts_the_server_without_its_stdin(server, capture_popen, monkeypatch):
    sys.path.insert(0, str(server.Path(server.__file__).parent))
    import stdio_wrapper

    def no_server(*args, **kwargs):
        raise OSError("no server yet")
    monkeypatch.setattr(stdio_wrapper.urllib.request, "urlopen", no_server)
    with pytest.raises(Spawned):
        stdio_wrapper.start_http_server()

    assert capture_popen[0].get("stdin") is subprocess.DEVNULL
