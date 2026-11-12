"""Issue #2: a Firefox add-on older than the server failed with a bare
'Unknown action: pressKey' and nothing said which versions were involved."""
import threading


def _respond(server, manager, response):
    """Deliver a browser response the way /browser/response does; return what the tool gets."""
    holder = {}
    manager.http_pending_requests[response["requestId"]] = (threading.Event(), holder)
    manager.handle_response(response)
    return holder["response"]


def test_unknown_action_from_old_addon_says_to_update(server):
    manager = server.BrowserConnectionManager()
    result = _respond(server, manager, {"requestId": "1", "success": False,
                                        "error": "Unknown action: pressKey"})

    assert result["error"].startswith("Unknown action: pressKey")
    assert "too old to report its version" in result["error"]
    assert server.SERVER_VERSION in result["error"]
    assert "update the Firefox add-on" in result["error"]


def test_unknown_action_names_the_addon_version_when_known(server):
    manager = server.BrowserConnectionManager()
    result = _respond(server, manager, {"requestId": "2", "success": False, "extensionVersion": "1.3.0",
                                        "error": "Unknown action: getText"})

    assert "add-on is 1.3.0" in result["error"]


def test_version_is_recorded_and_kept_out_of_tool_results(server):
    manager = server.BrowserConnectionManager()
    result = _respond(server, manager, {"requestId": "3", "success": True, "extensionVersion": "1.4.3"})

    assert manager.extension_version == "1.4.3"
    assert "extensionVersion" not in result


def test_other_errors_are_unchanged(server):
    manager = server.BrowserConnectionManager()
    result = _respond(server, manager, {"requestId": "4", "success": False, "extensionVersion": "1.4.3",
                                        "error": "Element not found"})

    assert result["error"] == "Element not found"


def test_version_info_reports_both_sides(server):
    manager = server.BrowserConnectionManager()
    assert manager.version_info() == {"server_version": server.SERVER_VERSION, "extension_version": None}
    _respond(server, manager, {"requestId": "5", "success": True, "extensionVersion": "1.4.3"})
    assert manager.version_info()["extension_version"] == "1.4.3"


def test_safety_status_tool_reports_versions(server):
    server.connection_manager.extension_version = "1.4.3"
    handler = server.MCPHTTPHandler.__new__(server.MCPHTTPHandler)
    status = handler.execute_tool("browser_safety_status", {})

    assert status["server_version"] == server.SERVER_VERSION
    assert status["extension_version"] == "1.4.3"
