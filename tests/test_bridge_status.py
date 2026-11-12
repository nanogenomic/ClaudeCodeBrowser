"""Issue #1: when the bridge to Firefox was down, every call waited 30 s and
returned a bare 'timed out', with nothing saying why."""
import sys
import time
import types

import pytest


@pytest.fixture
def handler(server, monkeypatch):
    """A request handler that can dispatch tools without a real HTTP socket."""
    monkeypatch.setattr(server, "connection_manager", server.BrowserConnectionManager())
    h = server.MCPHTTPHandler.__new__(server.MCPHTTPHandler)
    h.server = types.SimpleNamespace()
    return h


def test_no_browser_ever_connected_fails_after_a_short_grace(server, handler):
    # A freshly started server waits POLL_STALE_SECONDS for the first poll.
    start = time.monotonic()
    result = handler.execute_tool("browser_get_tabs", {})

    assert time.monotonic() - start < server.POLL_STALE_SECONDS + 2
    assert result["success"] is False
    assert "No browser connected" in result["error"]
    assert "Firefox" in result["error"]


def test_browser_that_stopped_polling_fails_fast(server, handler):
    server.connection_manager.last_poll = time.monotonic() - 60
    start = time.monotonic()
    result = handler.execute_tool("browser_get_tabs", {})

    assert time.monotonic() - start < 2
    assert "No browser connected" in result["error"]
    assert "60 s" in result["error"]


def test_connected_browser_that_does_not_answer_says_so(server, handler, monkeypatch):
    monkeypatch.setattr(server, "DEFAULT_BROWSER_WAIT", 0.2)
    server.connection_manager.note_poll()
    result = handler.execute_tool("browser_get_tabs", {})

    assert result["success"] is False
    assert "connected but did not answer" in result["error"]


def test_status_reports_connection(server, handler):
    assert handler.execute_tool("browser_safety_status", {})["browser_connected"] is False
    server.connection_manager.note_poll()
    assert handler.execute_tool("browser_safety_status", {})["browser_connected"] is True


def test_wrapper_waits_longer_than_the_server(server):
    # Otherwise the wrapper's own HTTP timeout fires first and the agent gets a
    # bare 'timed out' instead of the server's explanation (and human prompts
    # like solve_captcha are cut off).
    sys.path.insert(0, str(server.Path(server.__file__).parent))
    import stdio_wrapper

    longest = max([server.DEFAULT_BROWSER_WAIT, *server.HUMAN_PROMPT_WAITS.values()])
    assert stdio_wrapper.TOOL_CALL_TIMEOUT > longest


def test_first_poll_during_the_grace_period_is_used(server, handler, monkeypatch):
    import threading
    monkeypatch.setattr(server, "DEFAULT_BROWSER_WAIT", 0.2)
    threading.Timer(0.5, server.connection_manager.note_poll).start()
    result = handler.execute_tool("browser_get_tabs", {})

    assert "No browser connected" not in result["error"]
