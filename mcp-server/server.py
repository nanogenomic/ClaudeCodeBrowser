#!/usr/bin/env python3
"""
ClaudeCodeBrowser MCP Server

A Model Context Protocol (MCP) compatible server that provides browser automation
capabilities to Claude Code and other AI assistants.

This server exposes tools for:
- Taking screenshots of web pages
- Clicking elements
- Typing text
- Scrolling
- Navigation
- Element inspection
- Page refresh/reload
- And more...

MIT License
Copyright (c) 2025 Andre Watson (nanogenomic), Ligandal Inc.
Author: dre@ligandal.com
"""

import asyncio
import json
import logging
import os
import secrets
import stat
import sys
import base64
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, asdict
from datetime import datetime

# Try to import websockets for WebSocket support
try:
    import websockets
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False

# HTTP server imports
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs
import threading
import socket

# Configure logging
LOG_DIR = Path.home() / '.claudecodebrowser' / 'logs'
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / 'mcp_server.log'

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('ClaudeCodeBrowser.MCPServer')

# Headless mode: CLAUDE_BROWSER_HEADLESS=1 or --headless flag
HEADLESS_MODE = os.environ.get('CLAUDE_BROWSER_HEADLESS', '0') == '1' or '--headless' in sys.argv

# The asyncio event loop owned by the main thread (started via asyncio.run in
# main()). Published so ThreadingHTTPServer worker threads can dispatch onto it
# with run_coroutine_threadsafe: asyncio.get_event_loop() raises in threads
# without a loop on Python 3.12+ (see issue #9).
MAIN_EVENT_LOOP: Optional[asyncio.AbstractEventLoop] = None

# How long a command waits for Playwright Firefox to finish booting before
# giving up. Launching takes ~15s while the HTTP port binds immediately.
HEADLESS_STARTUP_TIMEOUT = float(os.environ.get('CLAUDE_BROWSER_HEADLESS_STARTUP_TIMEOUT', '45'))

from safety import get_safety_guard

# API token for localhost HTTP authentication
_TOKEN_FILE = Path.home() / '.claudecodebrowser' / 'api_token'


def _load_or_create_api_token() -> str:
    """Load existing API token or generate a new one on first run."""
    if _TOKEN_FILE.exists():
        token = _TOKEN_FILE.read_text().strip()
        if token:
            return token
    token = secrets.token_hex(32)
    _TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    _TOKEN_FILE.write_text(token)
    _TOKEN_FILE.chmod(0o600)
    logger.info(f"Generated new API token saved to {_TOKEN_FILE}")
    return token


API_TOKEN = _load_or_create_api_token()

# Configuration
HOST = os.environ.get('CLAUDE_BROWSER_HOST', '127.0.0.1')
HTTP_PORT = int(os.environ.get('CLAUDE_BROWSER_HTTP_PORT', '8765'))
WS_PORT = int(os.environ.get('CLAUDE_BROWSER_WS_PORT', '8766'))

# Screenshots directory - configurable via environment variable
# Default to /tmp/claudecodebrowser/screenshots (accessible from any mount point)
# Can be overridden by setting CLAUDE_BROWSER_SCREENSHOTS_DIR
DEFAULT_SCREENSHOTS_DIR = Path('/tmp/claudecodebrowser/screenshots')
SCREENSHOTS_DIR = Path(os.environ.get('CLAUDE_BROWSER_SCREENSHOTS_DIR', str(DEFAULT_SCREENSHOTS_DIR)))
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)


def camelize_args(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Convert snake_case MCP argument keys to the camelCase the extension reads.

    The MCP tool schemas use snake_case (full_page, url_pattern, bypass_cache)
    but background.js/content.js read camelCase (fullPage, urlPattern,
    bypassCache). The headless Playwright backend keeps the original
    snake_case arguments.
    """
    def camel(key: str) -> str:
        head, *rest = key.split('_')
        return head + ''.join(part.title() for part in rest)
    return {camel(k): v for k, v in arguments.items()}


@dataclass
class BrowserCommand:
    """Represents a command to be sent to the browser."""
    action: str
    tab_id: Optional[int] = None
    data: Optional[Dict[str, Any]] = None
    request_id: Optional[str] = None


@dataclass
class MCPTool:
    """MCP Tool definition."""
    name: str
    description: str
    input_schema: Dict[str, Any]


# Define available MCP tools
MCP_TOOLS: List[MCPTool] = [
    MCPTool(
        name="browser_screenshot",
        description="Take a screenshot of the current browser tab or a specific tab. Returns base64 encoded PNG image.",
        input_schema={
            "type": "object",
            "properties": {
                "tab_id": {"type": "integer", "description": "Optional tab ID. If not specified, uses active tab."},
                "full_page": {"type": "boolean", "description": "Capture full page instead of visible area.", "default": False},
                "save_to_file": {"type": "boolean", "description": "Save screenshot to file.", "default": True},
                "filename": {"type": "string", "description": "Optional filename for saved screenshot."}
            }
        }
    ),
    MCPTool(
        name="browser_click",
        description="Click on an element in the browser. Can target by CSS selector, XPath, text content, or coordinates.",
        input_schema={
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector for the element to click."},
                "xpath": {"type": "string", "description": "XPath expression to find the element."},
                "text": {"type": "string", "description": "Text content to search for and click."},
                "x": {"type": "number", "description": "X coordinate to click."},
                "y": {"type": "number", "description": "Y coordinate to click."},
                "tab_id": {"type": "integer", "description": "Optional tab ID."},
                "double_click": {"type": "boolean", "description": "Perform double-click.", "default": False},
                "right_click": {"type": "boolean", "description": "Perform right-click.", "default": False}
            }
        }
    ),
    MCPTool(
        name="browser_type",
        description="Type text into an input field or editable element. Can target by selector, placeholder, name, or focus current element.",
        input_schema={
            "type": "object",
            "required": ["text"],
            "properties": {
                "text": {"type": "string", "description": "Text to type."},
                "selector": {"type": "string", "description": "CSS selector for the input element."},
                "placeholder": {"type": "string", "description": "Placeholder text to find the input."},
                "name": {"type": "string", "description": "Name attribute of the input."},
                "id": {"type": "string", "description": "ID of the input element."},
                "tab_id": {"type": "integer", "description": "Optional tab ID."},
                "clear": {"type": "boolean", "description": "Clear existing content first.", "default": False},
                "press_enter": {"type": "boolean", "description": "Press Enter after typing.", "default": False},
                "delay": {"type": "integer", "description": "Delay between keystrokes in ms.", "default": 50}
            }
        }
    ),
    MCPTool(
        name="browser_scroll",
        description="Scroll the page or a specific element.",
        input_schema={
            "type": "object",
            "properties": {
                "direction": {"type": "string", "enum": ["up", "down", "left", "right", "top", "bottom"], "description": "Scroll direction."},
                "amount": {"type": "integer", "description": "Scroll amount in pixels.", "default": 300},
                "selector": {"type": "string", "description": "CSS selector for scrollable element."},
                "to_element": {"type": "string", "description": "CSS selector of element to scroll into view."},
                "tab_id": {"type": "integer", "description": "Optional tab ID."}
            }
        }
    ),
    MCPTool(
        name="browser_navigate",
        description="Navigate to a URL in the browser.",
        input_schema={
            "type": "object",
            "required": ["url"],
            "properties": {
                "url": {"type": "string", "description": "URL to navigate to."},
                "tab_id": {"type": "integer", "description": "Optional tab ID. Creates new tab if not specified."},
                "new_tab": {"type": "boolean", "description": "Open URL in new tab.", "default": False}
            }
        }
    ),
    MCPTool(
        name="browser_get_page_info",
        description="Get information about the current page including URL, title, interactive elements, forms, and headings.",
        input_schema={
            "type": "object",
            "properties": {
                "tab_id": {"type": "integer", "description": "Optional tab ID."}
            }
        }
    ),
    MCPTool(
        name="browser_get_elements",
        description="Find and return information about elements matching a selector.",
        input_schema={
            "type": "object",
            "required": ["selector"],
            "properties": {
                "selector": {"type": "string", "description": "CSS selector to find elements."},
                "limit": {"type": "integer", "description": "Maximum elements to return.", "default": 50},
                "tab_id": {"type": "integer", "description": "Optional tab ID."}
            }
        }
    ),
    MCPTool(
        name="browser_wait_for_element",
        description="Wait for an element to appear on the page.",
        input_schema={
            "type": "object",
            "required": ["selector"],
            "properties": {
                "selector": {"type": "string", "description": "CSS selector for the element."},
                "timeout": {"type": "integer", "description": "Maximum wait time in ms.", "default": 10000},
                "visible": {"type": "boolean", "description": "Wait for element to be visible.", "default": True},
                "tab_id": {"type": "integer", "description": "Optional tab ID."}
            }
        }
    ),
    MCPTool(
        name="browser_highlight",
        description="Highlight an element on the page for visual debugging.",
        input_schema={
            "type": "object",
            "required": ["selector"],
            "properties": {
                "selector": {"type": "string", "description": "CSS selector for the element."},
                "duration": {"type": "integer", "description": "Highlight duration in ms.", "default": 3000},
                "label": {"type": "string", "description": "Label to show above the element."},
                "tab_id": {"type": "integer", "description": "Optional tab ID."}
            }
        }
    ),
    MCPTool(
        name="browser_execute_script",
        description="Execute JavaScript code in the browser context.",
        input_schema={
            "type": "object",
            "required": ["script"],
            "properties": {
                "script": {"type": "string", "description": "JavaScript code to execute."},
                "tab_id": {"type": "integer", "description": "Optional tab ID."}
            }
        }
    ),
    MCPTool(
        name="browser_get_tabs",
        description="Get list of open browser tabs (URL, title, active status, loading state, whether playing audio). Defaults to the current window and a max of 50 tabs to keep results small when many tabs are open — pass current_window_only=false to see every window, or url_pattern to filter.",
        input_schema={
            "type": "object",
            "properties": {
                "current_window_only": {"type": "boolean", "default": True, "description": "Only list tabs in the current window. Set false to include every open Firefox window."},
                "limit": {"type": "integer", "default": 50, "description": "Max tabs to return."},
                "url_pattern": {"type": "string", "description": "Regex to filter tabs by URL before applying limit."},
                "include_favicon": {"type": "boolean", "default": False, "description": "Include favIconUrl (often a large base64 data URI) per tab."}
            }
        }
    ),
    MCPTool(
        name="browser_get_tab_info",
        description="Get detailed information about a specific tab including page info from content script.",
        input_schema={
            "type": "object",
            "required": ["tab_id"],
            "properties": {
                "tab_id": {"type": "integer", "description": "ID of the tab to get info for."},
                "include_favicon": {"type": "boolean", "default": False,
                                    "description": "Include favIconUrl (often a large base64 data URI)."}
            }
        }
    ),
    MCPTool(
        name="browser_find_tabs",
        description="Find tabs by URL pattern, title, or other criteria.",
        input_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL prefix to match."},
                "url_pattern": {"type": "string", "description": "Regex pattern to match URLs."},
                "title": {"type": "string", "description": "Text to search for in tab titles (case-insensitive)."},
                "active": {"type": "boolean", "description": "Filter by active state."},
                "audible": {"type": "boolean", "description": "Filter by playing audio."}
            }
        }
    ),
    MCPTool(
        name="browser_screenshot_all_tabs",
        description="Take screenshots of all open tabs (or filtered by URL pattern). Cycles through tabs and restores original focus.",
        input_schema={
            "type": "object",
            "properties": {
                "url_pattern": {"type": "string", "description": "Regex pattern to filter which tabs to screenshot."},
                "include_data": {"type": "boolean", "description": "Include base64 image data in response (large).", "default": False}
            }
        }
    ),
    MCPTool(
        name="browser_create_tab",
        description="Create a new browser tab.",
        input_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to open in the new tab.", "default": "about:blank"},
                "active": {"type": "boolean", "description": "Make the new tab active.", "default": True}
            }
        }
    ),
    MCPTool(
        name="browser_close_tab",
        description="Close a browser tab.",
        input_schema={
            "type": "object",
            "required": ["tab_id"],
            "properties": {
                "tab_id": {"type": "integer", "description": "ID of the tab to close."}
            }
        }
    ),
    MCPTool(
        name="browser_focus_tab",
        description="Focus/activate a browser tab.",
        input_schema={
            "type": "object",
            "required": ["tab_id"],
            "properties": {
                "tab_id": {"type": "integer", "description": "ID of the tab to focus."}
            }
        }
    ),
    MCPTool(
        name="browser_get_value",
        description="Get the value of an input element.",
        input_schema={
            "type": "object",
            "required": ["selector"],
            "properties": {
                "selector": {"type": "string", "description": "CSS selector for the input element."},
                "tab_id": {"type": "integer", "description": "Optional tab ID."}
            }
        }
    ),
    MCPTool(
        name="browser_set_value",
        description="Set the value of an input element directly (without typing simulation).",
        input_schema={
            "type": "object",
            "required": ["selector", "value"],
            "properties": {
                "selector": {"type": "string", "description": "CSS selector for the input element."},
                "value": {"type": "string", "description": "Value to set."},
                "tab_id": {"type": "integer", "description": "Optional tab ID."}
            }
        }
    ),
    MCPTool(
        name="browser_select_option",
        description="Select an option in a dropdown/select element.",
        input_schema={
            "type": "object",
            "required": ["selector"],
            "properties": {
                "selector": {"type": "string", "description": "CSS selector for the select element."},
                "value": {"type": "string", "description": "Option value to select."},
                "text": {"type": "string", "description": "Option text to select."},
                "index": {"type": "integer", "description": "Option index to select."},
                "tab_id": {"type": "integer", "description": "Optional tab ID."}
            }
        }
    ),
    MCPTool(
        name="browser_hover",
        description="Hover over an element to trigger hover effects.",
        input_schema={
            "type": "object",
            "required": ["selector"],
            "properties": {
                "selector": {"type": "string", "description": "CSS selector for the element."},
                "tab_id": {"type": "integer", "description": "Optional tab ID."}
            }
        }
    ),
    MCPTool(
        name="browser_refresh",
        description="Refresh/reload the current page or a specific tab. Useful after deploying code changes.",
        input_schema={
            "type": "object",
            "properties": {
                "tab_id": {"type": "integer", "description": "Optional tab ID. If not specified, refreshes active tab."},
                "bypass_cache": {"type": "boolean", "description": "Hard refresh - bypass browser cache (like Ctrl+Shift+R).", "default": False},
                "wait_for_load": {"type": "boolean", "description": "Wait for page to fully load after refresh.", "default": True}
            }
        }
    ),
    MCPTool(
        name="browser_hard_refresh",
        description="Force refresh the page bypassing all caches (equivalent to Ctrl+Shift+R). Essential after server restarts.",
        input_schema={
            "type": "object",
            "properties": {
                "tab_id": {"type": "integer", "description": "Optional tab ID. If not specified, refreshes active tab."}
            }
        }
    ),
    MCPTool(
        name="browser_reload_all",
        description="Reload all open browser tabs. Optionally filter by URL pattern. Great for refreshing all dev server tabs after deployment.",
        input_schema={
            "type": "object",
            "properties": {
                "url_pattern": {"type": "string", "description": "Regex pattern to filter which tabs to reload (e.g., 'localhost' or 'ligandal\\.com')."},
                "bypass_cache": {"type": "boolean", "description": "Hard refresh all matching tabs.", "default": True}
            }
        }
    ),
    MCPTool(
        name="browser_reload_by_url",
        description="Reload all tabs matching a specific URL or pattern. Perfect for refreshing dev server tabs after launching a new server.",
        input_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL prefix to match (e.g., 'http://localhost:5000')."},
                "url_pattern": {"type": "string", "description": "Regex pattern to match URLs."},
                "bypass_cache": {"type": "boolean", "description": "Hard refresh matching tabs.", "default": True}
            }
        }
    ),
    # Dynamic content tools
    MCPTool(
        name="browser_wait_for_change",
        description="Wait for DOM changes on the page. Useful after clicking elements that trigger dynamic updates, AJAX calls, or animations.",
        input_schema={
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector of element to observe (default: body).", "default": "body"},
                "timeout": {"type": "integer", "description": "Max time to wait in ms.", "default": 10000},
                "change_type": {"type": "string", "enum": ["childList", "attributes", "text"], "description": "Type of change to wait for."},
                "subtree": {"type": "boolean", "description": "Observe child elements too.", "default": True},
                "tab_id": {"type": "integer", "description": "Optional tab ID."}
            }
        }
    ),
    MCPTool(
        name="browser_wait_for_network_idle",
        description="Wait for network requests (fetch/XHR) to settle. Perfect for waiting after actions that trigger API calls.",
        input_schema={
            "type": "object",
            "properties": {
                "timeout": {"type": "integer", "description": "Max time to wait in ms.", "default": 10000},
                "idle_time": {"type": "integer", "description": "How long network must be idle (ms).", "default": 500},
                "tab_id": {"type": "integer", "description": "Optional tab ID."}
            }
        }
    ),
    MCPTool(
        name="browser_observe_element",
        description="Start observing an element for changes. Call browser_stop_observing later to get accumulated changes.",
        input_schema={
            "type": "object",
            "required": ["selector"],
            "properties": {
                "selector": {"type": "string", "description": "CSS selector of element to observe."},
                "observer_id": {"type": "string", "description": "ID for this observer (to stop it later)."},
                "tab_id": {"type": "integer", "description": "Optional tab ID."}
            }
        }
    ),
    MCPTool(
        name="browser_stop_observing",
        description="Stop observing an element and get all accumulated changes since observation started.",
        input_schema={
            "type": "object",
            "required": ["observer_id"],
            "properties": {
                "observer_id": {"type": "string", "description": "ID of the observer to stop."},
                "tab_id": {"type": "integer", "description": "Optional tab ID."}
            }
        }
    ),
    MCPTool(
        name="browser_scroll_and_capture",
        description="Scroll through the entire page collecting information about visible elements at each viewport position. Use with browser_screenshot for full-page visual capture.",
        input_schema={
            "type": "object",
            "properties": {
                "scroll_step": {"type": "integer", "description": "Pixels to scroll each step (default: 80% of viewport)."},
                "delay": {"type": "integer", "description": "Delay between scrolls in ms.", "default": 500},
                "max_scrolls": {"type": "integer", "description": "Maximum number of scroll steps.", "default": 20},
                "restore": {"type": "boolean", "description": "Restore original scroll position after.", "default": True},
                "tab_id": {"type": "integer", "description": "Optional tab ID."}
            }
        }
    ),
    MCPTool(
        name="browser_click_and_wait",
        description="Click an element and wait for dynamic content to load. Combines click + wait for DOM changes. Perfect for buttons that open modals, load content, or trigger navigation.",
        input_schema={
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector for the element to click."},
                "xpath": {"type": "string", "description": "XPath expression to find the element."},
                "text": {"type": "string", "description": "Text content to search for and click."},
                "wait_timeout": {"type": "integer", "description": "Max time to wait for changes in ms.", "default": 5000},
                "wait_for_selector": {"type": "string", "description": "Wait for specific element to appear after click."},
                "wait_for_change": {"type": "boolean", "description": "Wait for any DOM change.", "default": True},
                "tab_id": {"type": "integer", "description": "Optional tab ID."}
            }
        }
    ),
    # Console and Network Logging Tools
    MCPTool(
        name="browser_start_logging",
        description="Start capturing console logs and network requests from the browser. Use this before performing actions you want to monitor. Logs are accumulated until you retrieve them.",
        input_schema={
            "type": "object",
            "properties": {
                "clear_existing": {"type": "boolean", "description": "Clear any existing logs before starting.", "default": False},
                "tab_id": {"type": "integer", "description": "Optional tab ID. If not specified, uses active tab."}
            }
        }
    ),
    MCPTool(
        name="browser_stop_logging",
        description="Stop capturing console logs and network requests. Logs are preserved and can still be retrieved.",
        input_schema={
            "type": "object",
            "properties": {
                "tab_id": {"type": "integer", "description": "Optional tab ID. If not specified, uses active tab."}
            }
        }
    ),
    MCPTool(
        name="browser_get_console_logs",
        description="Retrieve captured console logs (console.log, console.error, console.warn, etc.). Useful for debugging AI chat interfaces, seeing errors, and monitoring application state.",
        input_schema={
            "type": "object",
            "properties": {
                "level": {"type": "string", "enum": ["log", "warn", "error", "info", "debug"], "description": "Filter by log level."},
                "search": {"type": "string", "description": "Filter logs containing this text."},
                "limit": {"type": "integer", "description": "Maximum number of logs to return.", "default": 100},
                "tab_id": {"type": "integer", "description": "Optional tab ID. If not specified, uses active tab."}
            }
        }
    ),
    MCPTool(
        name="browser_get_network_logs",
        description="Retrieve captured network requests and responses (fetch/XHR). Perfect for debugging API calls, seeing request/response data, and monitoring AI chat communications.",
        input_schema={
            "type": "object",
            "properties": {
                "url_pattern": {"type": "string", "description": "Regex pattern to filter by URL."},
                "method": {"type": "string", "description": "Filter by HTTP method (GET, POST, etc.)."},
                "status": {"type": "integer", "description": "Filter by HTTP status code."},
                "errors_only": {"type": "boolean", "description": "Only return failed requests.", "default": False},
                "limit": {"type": "integer", "description": "Maximum number of logs to return.", "default": 100},
                "tab_id": {"type": "integer", "description": "Optional tab ID. If not specified, uses active tab."}
            }
        }
    ),
    MCPTool(
        name="browser_clear_logs",
        description="Clear all captured console and/or network logs.",
        input_schema={
            "type": "object",
            "properties": {
                "console": {"type": "boolean", "description": "Clear console logs.", "default": True},
                "network": {"type": "boolean", "description": "Clear network logs.", "default": True},
                "tab_id": {"type": "integer", "description": "Optional tab ID. If not specified, uses active tab."}
            }
        }
    ),
    MCPTool(
        name="browser_eval_chain",
        description=(
            "Execute a sequence of JavaScript expressions in the page, sharing state between steps. "
            "Each step can inspect the result of the previous one and branch conditionally. "
            "Console output (console.log/warn/error) is captured per step. "
            "Ideal for multi-turn inspection tasks without round-tripping per expression."
        ),
        input_schema={
            "type": "object",
            "required": ["steps"],
            "properties": {
                "steps": {
                    "type": "array",
                    "description": "Ordered list of JS expressions to evaluate. Each step receives the prior result as `$prev`.",
                    "items": {
                        "type": "object",
                        "required": ["script"],
                        "properties": {
                            "script": {"type": "string", "description": "JavaScript expression to evaluate."},
                            "label": {"type": "string", "description": "Human-readable label for this step."},
                            "capture_console": {"type": "boolean", "default": True, "description": "Capture console output for this step."},
                            "stop_on_error": {"type": "boolean", "default": True, "description": "Abort chain if this step throws."}
                        }
                    }
                },
                "tab_id": {"type": "integer", "description": "Optional tab ID."}
            }
        }
    ),
    MCPTool(
        name="browser_wait_and_act",
        description=(
            "Poll the page until a condition is met, then execute an action. "
            "Use for waiting on async UI state (e.g. 'wait until #result is visible, then click it')."
        ),
        input_schema={
            "type": "object",
            "required": ["condition", "action_script"],
            "properties": {
                "condition": {"type": "string", "description": "JS expression that returns truthy when ready."},
                "action_script": {"type": "string", "description": "JS to run once condition is met."},
                "poll_interval_ms": {"type": "integer", "default": 200, "description": "How often to check condition."},
                "timeout_ms": {"type": "integer", "default": 15000, "description": "Max wait time before giving up."},
                "tab_id": {"type": "integer", "description": "Optional tab ID."}
            }
        }
    ),
    # Navigation history
    MCPTool(
        name="browser_go_back",
        description="Navigate back in the tab's history (like the browser Back button).",
        input_schema={
            "type": "object",
            "properties": {
                "tab_id": {"type": "integer", "description": "Optional tab ID. If not specified, uses active tab."}
            }
        }
    ),
    MCPTool(
        name="browser_go_forward",
        description="Navigate forward in the tab's history (like the browser Forward button).",
        input_schema={
            "type": "object",
            "properties": {
                "tab_id": {"type": "integer", "description": "Optional tab ID. If not specified, uses active tab."}
            }
        }
    ),
    MCPTool(
        name="browser_press_key",
        description="Press a keyboard key (with optional modifiers) on the focused element or a specific element. Useful for Enter, Escape, Tab, arrow keys, and shortcuts.",
        input_schema={
            "type": "object",
            "required": ["key"],
            "properties": {
                "key": {"type": "string", "description": "Key to press, e.g. 'Enter', 'Escape', 'Tab', 'ArrowDown', 'a'."},
                "selector": {"type": "string", "description": "Optional CSS selector of element to focus first."},
                "ctrl": {"type": "boolean", "description": "Hold Ctrl.", "default": False},
                "shift": {"type": "boolean", "description": "Hold Shift.", "default": False},
                "alt": {"type": "boolean", "description": "Hold Alt.", "default": False},
                "meta": {"type": "boolean", "description": "Hold Meta/Cmd.", "default": False},
                "tab_id": {"type": "integer", "description": "Optional tab ID."}
            }
        }
    ),
    MCPTool(
        name="browser_get_text",
        description="Extract the visible text content of the page or a specific element. Lighter-weight than a screenshot for reading page content.",
        input_schema={
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "Optional CSS selector; defaults to the whole page body."},
                "max_length": {"type": "integer", "description": "Truncate the returned text to this many characters.", "default": 20000},
                "tab_id": {"type": "integer", "description": "Optional tab ID."}
            }
        }
    ),
    # Human approval, workflows, and page auditing
    MCPTool(
        name="browser_request_approval",
        description="Ask the human at the browser to approve or deny an action. Shows an Approve/Deny banner on the current page plus an OS notification, and waits for their decision. Use before doing anything the user might want to veto. Unavailable in headless mode (no human present).",
        input_schema={
            "type": "object",
            "required": ["message"],
            "properties": {
                "message": {"type": "string", "description": "What you are asking permission to do, in plain language."},
                "detail": {"type": "string", "description": "Optional extra context shown in smaller text."},
                "timeout": {"type": "integer", "description": "How long to wait for a decision in ms.", "default": 60000},
                "tab_id": {"type": "integer", "description": "Optional tab ID to show the banner in."}
            }
        }
    ),
    MCPTool(
        name="browser_run_workflow",
        description="Run a declarative multi-step browser workflow with per-step assertions — an end-to-end test runner for web apps. Each step calls a browser tool; optional assertions check the page afterwards (url_contains, text_contains, selector_exists). Failing steps capture a screenshot. Returns pass/fail per step.",
        input_schema={
            "type": "object",
            "required": ["steps"],
            "properties": {
                "steps": {
                    "type": "array",
                    "description": "Ordered workflow steps.",
                    "items": {
                        "type": "object",
                        "required": ["tool"],
                        "properties": {
                            "label": {"type": "string", "description": "Human-readable step name."},
                            "tool": {"type": "string", "description": "Browser tool to call, e.g. browser_navigate, browser_click, browser_type."},
                            "arguments": {"type": "object", "description": "Arguments for the tool."},
                            "assert": {
                                "type": "object",
                                "description": "Checks to run after the step succeeds.",
                                "properties": {
                                    "url_contains": {"type": "string", "description": "Current URL must contain this substring."},
                                    "text_contains": {"type": "string", "description": "Visible page text must contain this substring."},
                                    "selector_exists": {"type": "string", "description": "This CSS selector must match at least one element."}
                                }
                            }
                        }
                    }
                },
                "stop_on_failure": {"type": "boolean", "description": "Stop at the first failing step.", "default": True},
                "screenshot_on_failure": {"type": "boolean", "description": "Capture a screenshot when a step fails.", "default": True}
            }
        }
    ),
    MCPTool(
        name="browser_solve_captcha",
        description=(
            "Detect a captcha on the page and hand it to the human to solve, then continue. "
            "Detects reCAPTCHA, hCaptcha, Cloudflare Turnstile, and generic image captchas, "
            "shows a solve banner plus an OS notification, and waits until the challenge is "
            "completed (its response token appears) or the human clicks Done. This project "
            "does NOT auto-solve captchas or use solver services — a human completes the "
            "challenge. In headless mode there is no human, so it reports what it detected "
            "and that a human is required."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "timeout": {"type": "integer", "description": "How long to wait for the human to solve it, in ms.", "default": 180000},
                "detect_only": {"type": "boolean", "description": "Only report whether a captcha is present, without waiting.", "default": False},
                "tab_id": {"type": "integer", "description": "Optional tab ID."}
            }
        }
    ),
    MCPTool(
        name="browser_audit_page",
        description="Audit the current page for review and visual critique: heading structure, images missing alt text, unlabeled form inputs, empty links/buttons, meta/title info, viewport and element counts — plus a screenshot. One call gathers everything needed to critique a page's structure and accessibility basics.",
        input_schema={
            "type": "object",
            "properties": {
                "screenshot": {"type": "boolean", "description": "Also capture a screenshot.", "default": True},
                "full_page": {"type": "boolean", "description": "Make the screenshot full-page.", "default": False},
                "tab_id": {"type": "integer", "description": "Optional tab ID."}
            }
        }
    ),
    # Safety
    MCPTool(
        name="browser_safety_status",
        description="Show the active safety guard policy: read-only mode, script toggle, protected/blocked/allowed URL patterns, rate-limit state, and audit log location. Configured in ~/.claudecodebrowser/safety.json.",
        input_schema={
            "type": "object",
            "properties": {}
        }
    ),
    MCPTool(
        name="browser_inject_observer",
        description=(
            "Inject a MutationObserver into the page that captures DOM changes and console events "
            "into a buffer, readable via browser_get_console_logs. Useful for watching live UI updates."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "selector": {"type": "string", "default": "body", "description": "Root element to observe."},
                "observe_attributes": {"type": "boolean", "default": True},
                "observe_child_list": {"type": "boolean", "default": True},
                "observe_subtree": {"type": "boolean", "default": True},
                "tab_id": {"type": "integer"}
            }
        }
    )
]


class BrowserConnectionManager:
    """Manages connections to browser extensions."""

    def __init__(self):
        self.browser_connections = {}
        self.pending_requests = {}
        self.http_pending_requests = {}
        self.request_counter = 0

    def register_browser(self, browser_id: str, connection):
        """Register a new browser connection."""
        self.browser_connections[browser_id] = connection
        logger.info(f"Browser registered: {browser_id}")

    def unregister_browser(self, browser_id: str):
        """Unregister a browser connection."""
        if browser_id in self.browser_connections:
            del self.browser_connections[browser_id]
            logger.info(f"Browser unregistered: {browser_id}")

    def get_active_browser(self):
        """Get the first available browser connection."""
        if self.browser_connections:
            return list(self.browser_connections.values())[0]
        return None

    async def send_command(self, command: BrowserCommand,
                           timeout: float = 30.0) -> Dict[str, Any]:
        """Send a command to the browser and wait for response."""
        browser = self.get_active_browser()
        if not browser:
            return {"success": False, "error": "No browser connected"}

        self.request_counter += 1
        request_id = str(self.request_counter)
        command.request_id = request_id

        # Create a future for the response
        future = asyncio.get_event_loop().create_future()
        self.pending_requests[request_id] = future

        try:
            await browser.send(json.dumps(asdict(command)))
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            return {"success": False, "error": "Command timed out"}
        finally:
            self.pending_requests.pop(request_id, None)

    def handle_response(self, response: Dict[str, Any]):
        """Handle a response from the browser."""
        request_id = response.get('requestId')
        if request_id and request_id in self.pending_requests:
            future = self.pending_requests[request_id]
            if not future.done():
                future.set_result(response)
        # Also signal HTTP polling waiters
        if request_id and request_id in self.http_pending_requests:
            event, result_holder = self.http_pending_requests[request_id]
            result_holder['response'] = response
            event.set()


# Global connection manager
connection_manager = BrowserConnectionManager()


class MCPHTTPHandler(BaseHTTPRequestHandler):
    """HTTP request handler for MCP server."""

    def log_message(self, format, *args):
        logger.info(f"HTTP: {format % args}")

    def send_json_response(self, data: Dict[str, Any], status: int = 200):
        """Send a JSON response."""
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        # No CORS headers: all callers (stdio_wrapper, native host) are local processes
        # using urllib — not browser fetch. Omitting CORS blocks cross-origin requests.
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def _check_auth(self) -> bool:
        """Validate the X-API-Key header against the server token."""
        return self.headers.get('X-API-Key') == API_TOKEN

    def do_OPTIONS(self):
        """Reject CORS preflight: no cross-origin access is needed or allowed."""
        self.send_response(403)
        self.end_headers()

    def do_GET(self):
        """Handle GET requests."""
        parsed = urlparse(self.path)

        if parsed.path == '/health':
            # Health endpoint is unauthenticated so native host can probe without the token
            self.send_json_response({
                'status': 'ok',
                'timestamp': datetime.now().isoformat(),
                'version': '1.4.0',
                'browsers_connected': len(connection_manager.browser_connections)
            })

        elif not self._check_auth():
            self.send_json_response({'error': 'Unauthorized'}, 403)

        elif parsed.path == '/mcp/tools':
            # Return list of available MCP tools
            tools = [
                {
                    'name': tool.name,
                    'description': tool.description,
                    'inputSchema': tool.input_schema
                }
                for tool in MCP_TOOLS
            ]
            self.send_json_response({'tools': tools})

        elif parsed.path == '/screenshots':
            # List saved screenshots
            screenshots = []
            for f in SCREENSHOTS_DIR.glob('*.png'):
                screenshots.append({
                    'name': f.name,
                    'path': str(f),
                    'size': f.stat().st_size,
                    'created': datetime.fromtimestamp(f.stat().st_ctime).isoformat()
                })
            self.send_json_response({'screenshots': sorted(screenshots, key=lambda x: x['created'], reverse=True)})

        elif parsed.path == '/browser/poll':
            # Extension/native host polls for pending commands
            pending = getattr(self.server, '_pending_commands', [])
            if pending:
                # Return and clear the first pending command
                command = pending.pop(0)
                self.send_json_response({'command': command, 'has_more': len(pending) > 0})
            else:
                self.send_json_response({'command': None, 'has_more': False})

        else:
            self.send_json_response({'error': 'Not found'}, 404)

    def do_POST(self):
        """Handle POST requests."""
        if not self._check_auth():
            self.send_json_response({'error': 'Unauthorized'}, 403)
            return

        parsed = urlparse(self.path)
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else '{}'

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self.send_json_response({'error': 'Invalid JSON'}, 400)
            return

        if parsed.path == '/mcp/call':
            # Call an MCP tool
            tool_name = data.get('name')
            arguments = data.get('arguments', {})

            result = self.execute_tool(tool_name, arguments)
            self.send_json_response(result)

        elif parsed.path == '/browser/command':
            # Direct browser command (from native host)
            action = data.get('action')
            tab_id = data.get('tabId')
            command_data = data.get('data', {})

            # Store the command for the extension to poll
            # In production, this would use WebSocket
            result = {
                'success': True,
                'message': 'Command queued',
                'action': action
            }
            self.send_json_response(result)

        elif parsed.path == '/browser/response':
            # Response from browser extension
            connection_manager.handle_response(data)
            self.send_json_response({'success': True})

        else:
            self.send_json_response({'error': 'Not found'}, 404)

    def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute an MCP tool by sending command to browser via native host."""
        _SENSITIVE = {'text', 'script', 'value', 'password'}
        log_args = {k: ('***' if k in _SENSITIVE else v) for k, v in arguments.items()}
        logger.info(f"Executing tool: {tool_name} with args: {log_args}")

        # Safety guard: scheme/blocklist checks, read-only mode, script toggle,
        # protected-domain confirmation, rate limiting, audit logging.
        guard = get_safety_guard()
        denial = guard.check(tool_name, arguments)

        # Duo-style human approval: when a protected action needs confirmation
        # and a human is (potentially) at the browser, ask them directly with
        # an in-page Approve/Deny banner instead of bouncing a token back
        # through the agent. Headless mode has no human, so it keeps the
        # token flow.
        if (denial is not None and denial.get('confirmation_required')
                and denial.get('approval_mode', 'auto') in ('auto', 'human')
                and not HEADLESS_MODE):
            approval = self._request_human_approval(tool_name, arguments, denial)
            if approval.get('success') and approval.get('approved'):
                denial = guard.check(tool_name, dict(arguments), human_approved=True)
            elif approval.get('success') and approval.get('approved') is False:
                return {'success': False,
                        'safety_decision': 'human_denied',
                        'error': f'The user denied {tool_name} via the in-browser '
                                 f'approval prompt. Do not retry without asking them why.'}
            # Approval prompt could not be delivered (no browser connected,
            # timeout): fall through and return the token-based denial so the
            # agent can still use the confirm_token flow.

        if denial is not None:
            logger.warning(f"Safety guard blocked {tool_name}: {denial.get('safety_decision')}")
            return denial

        # Handled entirely server-side, no browser round-trip needed.
        if tool_name == 'browser_safety_status':
            return guard.status()
        if tool_name == 'browser_run_workflow':
            return self._run_workflow(arguments)
        if tool_name == 'browser_audit_page':
            return self._audit_page(arguments)

        # Map tool names to actions
        tool_action_map = {
            'browser_screenshot': 'screenshot',
            'browser_click': 'click',
            'browser_type': 'type',
            'browser_scroll': 'scroll',
            'browser_navigate': 'navigate',
            'browser_get_page_info': 'getPageInfo',
            'browser_get_elements': 'getElements',
            'browser_wait_for_element': 'waitForElement',
            'browser_highlight': 'highlight',
            'browser_execute_script': 'executeScript',
            'browser_get_tabs': 'getTabs',
            'browser_get_tab_info': 'getTabInfo',
            'browser_find_tabs': 'findTabs',
            'browser_screenshot_all_tabs': 'screenshotAllTabs',
            'browser_create_tab': 'createTab',
            'browser_close_tab': 'closeTab',
            'browser_focus_tab': 'focusTab',
            'browser_get_value': 'getValue',
            'browser_set_value': 'setValue',
            'browser_select_option': 'selectOption',
            'browser_hover': 'hover',
            'browser_refresh': 'refresh',
            'browser_hard_refresh': 'hardRefresh',
            'browser_reload_all': 'reloadAll',
            'browser_reload_by_url': 'reloadByUrl',
            # Dynamic content tools
            'browser_wait_for_change': 'waitForChange',
            'browser_wait_for_network_idle': 'waitForNetworkIdle',
            'browser_observe_element': 'observeElement',
            'browser_stop_observing': 'stopObserving',
            'browser_scroll_and_capture': 'scrollAndCapture',
            'browser_click_and_wait': 'clickAndWait',
            # Console and network logging tools
            'browser_start_logging': 'startLogging',
            'browser_stop_logging': 'stopLogging',
            'browser_get_console_logs': 'getConsoleLogs',
            'browser_get_network_logs': 'getNetworkLogs',
            'browser_clear_logs': 'clearLogs',
            # Multi-turn / conditional execution
            'browser_eval_chain': 'evalChain',
            'browser_wait_and_act': 'waitAndAct',
            'browser_inject_observer': 'injectObserver',
            # Navigation history and keyboard/text
            'browser_go_back': 'goBack',
            'browser_go_forward': 'goForward',
            'browser_press_key': 'pressKey',
            'browser_get_text': 'getText',
            # Human approval
            'browser_request_approval': 'requestApproval',
            # Captcha detection + human handoff
            'browser_solve_captcha': 'solveCaptcha'
        }

        if tool_name not in tool_action_map:
            return {'success': False, 'error': f'Unknown tool: {tool_name}'}

        action = tool_action_map[tool_name]
        tab_id = arguments.pop('tab_id', None)

        # Password guard: typing into <input type="password"> is refused by the
        # browser side unless the safety config explicitly allows it. The flag
        # travels with the command so the enforcement happens where the element
        # type is visible.
        if tool_name in ('browser_type', 'browser_set_value'):
            arguments['allow_password'] = bool(
                get_safety_guard().config.get('allow_password_typing', False))

        return self._dispatch_action(action, tab_id, arguments)

    def _dispatch_action(self, action: str, tab_id: Optional[int],
                         arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Send a browser action over whichever transport is available
        (WebSocket, headless Playwright, or native-host HTTP polling)."""
        guard = get_safety_guard()

        # Prompts that wait on a human (approval, captcha solving) can take far
        # longer than a normal command, so give the transport matching headroom.
        if action == 'requestApproval':
            wait_timeout = 90.0
        elif action == 'solveCaptcha':
            wait_timeout = 200.0
        else:
            wait_timeout = 30.0

        # Check if we have a browser connection via WebSocket
        browser = connection_manager.get_active_browser()

        if browser:
            # Use async WebSocket communication
            command = BrowserCommand(
                action=action,
                tab_id=tab_id,
                data=camelize_args(arguments)
            )

            # We run in a ThreadingHTTPServer worker thread, which owns no
            # event loop (asyncio.get_event_loop() raises here on Python
            # 3.12+), so hand the coroutine to the main thread's loop.
            loop = MAIN_EVENT_LOOP
            if loop is not None and loop.is_running():
                try:
                    future = asyncio.run_coroutine_threadsafe(
                        connection_manager.send_command(command, timeout=wait_timeout),
                        loop
                    )
                    result = future.result(timeout=wait_timeout + 5)

                    # Handle screenshot saving
                    if action == 'screenshot' and result.get('success') and result.get('data'):
                        return self._save_screenshot(result, arguments)

                    guard.note_url(result)
                    return result
                except Exception as e:
                    logger.error(f"WebSocket command failed: {e}")
                    # Fall through to HTTP method
            else:
                logger.warning("WebSocket browser registered but no event loop running; "
                               "falling back to HTTP polling")

        # Try headless Playwright backend if enabled and available
        if HEADLESS_MODE:
            from headless_backend import get_headless_browser
            # Launching Playwright Firefox takes ~15s, but the HTTP server
            # accepts requests as soon as the port binds. Rather than failing
            # the first call of a session, wait for the browser to boot.
            deadline = time.monotonic() + HEADLESS_STARTUP_TIMEOUT
            headless = get_headless_browser()
            while time.monotonic() < deadline:
                if (MAIN_EVENT_LOOP is not None and MAIN_EVENT_LOOP.is_running()
                        and headless is not None and headless.is_ready()):
                    break
                time.sleep(0.5)
                headless = get_headless_browser()

            if headless is None or not headless.is_ready():
                return {'success': False,
                        'error': f'Headless browser did not start within '
                                 f'{HEADLESS_STARTUP_TIMEOUT:.0f}s. Check the server log.'}
            # Worker threads own no event loop; dispatch onto the loop started
            # by run_with_headless() in the main thread (issue #9).
            loop = MAIN_EVENT_LOOP
            if loop is None or not loop.is_running():
                return {'success': False,
                        'error': 'Headless event loop not running yet. Wait a moment and retry.'}
            try:
                future = asyncio.run_coroutine_threadsafe(
                    headless.execute(action, tab_id, arguments), loop
                )
                result = future.result(timeout=35)
                guard.note_url(result)
                return result
            except Exception as e:
                logger.error(f"Headless backend failed: {e}")
                return {'success': False, 'error': f'Headless execution failed: {e}'}

        # No WebSocket connection — use HTTP polling with the native host.
        # ThreadingHTTPServer ensures /browser/poll and /browser/response are
        # served concurrently while this thread blocks waiting for the response.
        request_id = str(time.time())
        command_data = {
            'action': action,
            'tabId': tab_id,
            'data': camelize_args(arguments),
            'requestId': request_id
        }

        # Register a waiter before queuing so we never miss the response
        event = threading.Event()
        result_holder = {}
        connection_manager.http_pending_requests[request_id] = (event, result_holder)

        self.server._pending_commands = getattr(self.server, '_pending_commands', [])
        self.server._pending_commands.append(command_data)

        logger.info(f"Queued command {action} (requestId={request_id}), waiting for browser response...")

        if event.wait(timeout=wait_timeout):
            connection_manager.http_pending_requests.pop(request_id, None)
            response = result_holder.get('response', {})
            if action == 'screenshot' and response.get('success') and response.get('data'):
                return self._save_screenshot(response, arguments)
            guard.note_url(response)
            return response
        else:
            connection_manager.http_pending_requests.pop(request_id, None)
            logger.warning(f"Command {action} timed out after {wait_timeout:.0f}s")
            return {
                'success': False,
                'error': f'Command {action} timed out waiting for browser response after {wait_timeout:.0f}s',
                'action': action
            }

    def _request_human_approval(self, tool_name: str, arguments: Dict[str, Any],
                                denial: Dict[str, Any]) -> Dict[str, Any]:
        """Show the in-browser Approve/Deny prompt for a protected action."""
        _SENSITIVE = {'text', 'script', 'value', 'password'}
        shown_args = {k: ('***' if k in _SENSITIVE else v) for k, v in arguments.items()
                      if k != 'tab_id'}
        try:
            return self._dispatch_action('requestApproval', None, {
                'message': f"Claude wants to run {tool_name} on a protected site "
                           f"({denial.get('protected_url', 'unknown URL')}).",
                'detail': json.dumps(shown_args)[:500],
                'timeout': 60000
            })
        except Exception as e:
            logger.warning(f"Human approval request failed: {e}")
            return {'success': False, 'error': str(e)}

    def _run_workflow(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a declarative list of tool steps with assertions."""
        import re as _re
        steps = arguments.get('steps') or []
        stop_on_failure = arguments.get('stop_on_failure', True)
        screenshot_on_failure = arguments.get('screenshot_on_failure', True)
        known_tools = {t.name for t in MCP_TOOLS}

        results = []
        passed = 0
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                results.append({'label': f'step_{i+1}', 'success': False,
                                'error': 'Step must be an object'})
                break
            label = step.get('label') or f'step_{i+1}'
            tool = step.get('tool')
            entry = {'label': label, 'tool': tool}

            if tool not in known_tools or tool == 'browser_run_workflow':
                entry['success'] = False
                entry['error'] = f'Unknown or disallowed tool: {tool}'
            else:
                # Each step goes through execute_tool, so the safety guard
                # applies per step exactly as it would for a direct call.
                result = self.execute_tool(tool, dict(step.get('arguments') or {}))
                entry['success'] = bool(result.get('success'))
                entry['result'] = {k: v for k, v in result.items() if k != 'data'}

                assertion = step.get('assert') or {}
                if entry['success'] and assertion:
                    failures = self._check_assertions(assertion)
                    entry['assertions'] = {'passed': not failures, 'failures': failures}
                    if failures:
                        entry['success'] = False
                        entry['error'] = 'Assertions failed: ' + '; '.join(failures)

            if entry['success']:
                passed += 1
            elif screenshot_on_failure:
                safe_label = _re.sub(r'[^A-Za-z0-9_-]', '_', label)[:40]
                shot = self.execute_tool('browser_screenshot',
                                         {'filename': f'workflow_fail_{safe_label}.png'})
                if shot.get('filepath'):
                    entry['failure_screenshot'] = shot['filepath']

            results.append(entry)
            if not entry['success'] and stop_on_failure:
                break

        return {
            'success': passed == len(steps),
            'passed': passed,
            'failed': len(results) - passed,
            'total_steps': len(steps),
            'executed_steps': len(results),
            'steps': results
        }

    def _check_assertions(self, assertion: Dict[str, Any]) -> List[str]:
        """Evaluate a step's assertions against the live page; return failures."""
        failures = []

        url_contains = assertion.get('url_contains')
        if url_contains:
            info = self.execute_tool('browser_get_page_info', {})
            url = info.get('url', '') if info.get('success') else ''
            if url_contains not in url:
                failures.append(f"url_contains {url_contains!r} (actual URL: {url!r})")

        text_contains = assertion.get('text_contains')
        if text_contains:
            text_result = self.execute_tool('browser_get_text', {'max_length': 100000})
            text = text_result.get('text', '') if text_result.get('success') else ''
            if text_contains not in text:
                failures.append(f"text_contains {text_contains!r} not found on page")

        selector_exists = assertion.get('selector_exists')
        if selector_exists:
            el_result = self.execute_tool('browser_get_elements',
                                          {'selector': selector_exists, 'limit': 1})
            elements = el_result.get('elements') or []
            if not (el_result.get('success') and len(elements) > 0):
                failures.append(f"selector_exists {selector_exists!r} matched nothing")

        return failures

    # Structural/accessibility audit collected in one page pass. Kept to
    # read-only DOM inspection — the audit tool is classified as observation.
    _AUDIT_JS = r"""
(function() {
  const headings = Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,h6'))
    .slice(0, 60).map(h => ({level: h.tagName, text: (h.innerText || '').trim().slice(0, 120)}));
  const images = Array.from(document.querySelectorAll('img'));
  const imagesMissingAlt = images.filter(i => !i.hasAttribute('alt'))
    .slice(0, 30).map(i => (i.currentSrc || i.src || '').slice(0, 200));
  const inputs = Array.from(document.querySelectorAll('input:not([type=hidden]),select,textarea'));
  const unlabeled = inputs.filter(el => {
    if (el.labels && el.labels.length) return false;
    if (el.getAttribute('aria-label') || el.getAttribute('aria-labelledby')) return false;
    if (el.getAttribute('placeholder')) return false;
    return true;
  }).slice(0, 30).map(el => (el.name || el.id || el.type || el.tagName).slice(0, 80));
  const emptyLinks = Array.from(document.querySelectorAll('a')).filter(a =>
    !(a.innerText || '').trim() && !a.getAttribute('aria-label') && !a.querySelector('img[alt]')
  ).length;
  const emptyButtons = Array.from(document.querySelectorAll('button')).filter(b =>
    !(b.innerText || '').trim() && !b.getAttribute('aria-label')
  ).length;
  const meta = {};
  const desc = document.querySelector('meta[name=description]');
  if (desc) meta.description = (desc.content || '').slice(0, 300);
  const viewportTag = document.querySelector('meta[name=viewport]');
  meta.hasViewportTag = !!viewportTag;
  return {
    title: document.title,
    url: location.href,
    lang: document.documentElement.lang || null,
    meta: meta,
    headings: headings,
    headingCounts: headings.reduce((acc, h) => { acc[h.level] = (acc[h.level] || 0) + 1; return acc; }, {}),
    imageCount: images.length,
    imagesMissingAlt: imagesMissingAlt,
    formInputCount: inputs.length,
    unlabeledInputs: unlabeled,
    emptyLinks: emptyLinks,
    emptyButtons: emptyButtons,
    linkCount: document.querySelectorAll('a').length,
    viewport: {width: window.innerWidth, height: window.innerHeight,
               pageHeight: Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0)}
  };
})()
"""

    def _audit_page(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Collect page structure + optional screenshot for visual critique."""
        tab_id = arguments.get('tab_id')
        script_args = {'script': self._AUDIT_JS}
        # Dispatch directly: the audit is read-only inspection, so it stays
        # available even when browser_execute_script is policy-disabled.
        audit = self._dispatch_action('executeScript', tab_id, script_args)
        if not audit.get('success'):
            return {'success': False,
                    'error': f"Audit script failed: {audit.get('error', 'unknown')}"}

        response = {'success': True, 'audit': audit.get('result')}

        if arguments.get('screenshot', True):
            from datetime import datetime as _dt
            shot = self.execute_tool('browser_screenshot', {
                'filename': f"audit_{_dt.now().strftime('%Y%m%d_%H%M%S')}.png",
                'full_page': arguments.get('full_page', False),
                **({'tab_id': tab_id} if tab_id is not None else {})
            })
            response['screenshot'] = shot.get('filepath') if shot.get('success') else None

        return response

    def _save_screenshot(self, result: Dict[str, Any], arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Save screenshot data to file."""
        try:
            data = result.get('data', '')
            save_to_file = arguments.get('save_to_file', True)
            # Strip directory components to prevent path traversal
            filename = Path(arguments.get('filename') or f'screenshot_{datetime.now().strftime("%Y%m%d_%H%M%S")}.png').name

            if not save_to_file:
                return result

            # Handle base64 data URL
            if data.startswith('data:image'):
                header, encoded = data.split(',', 1)
                image_data = base64.b64decode(encoded)
            else:
                image_data = base64.b64decode(data)

            filepath = SCREENSHOTS_DIR / filename
            with open(filepath, 'wb') as f:
                f.write(image_data)

            logger.info(f"Screenshot saved to: {filepath}")

            return {
                'success': True,
                'filepath': str(filepath),
                'filename': filename,
                'size': len(image_data),
                'tab': result.get('tab', {}),
                'message': f'Screenshot saved to {filepath}'
            }
        except Exception as e:
            logger.error(f"Failed to save screenshot: {e}")
            return {
                'success': False,
                'error': f'Failed to save screenshot: {str(e)}',
                'original_result': result
            }


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """HTTP server that handles each request in a new thread.

    Required because execute_tool() blocks waiting for browser responses while
    /browser/poll and /browser/response must be served concurrently on the same port.
    """
    daemon_threads = True


def run_http_server():
    """Run the HTTP server."""
    server = ThreadingHTTPServer((HOST, HTTP_PORT), MCPHTTPHandler)
    logger.info(f"HTTP server starting on {HOST}:{HTTP_PORT}")
    server.serve_forever()


async def websocket_handler(websocket, path=None):
    """Handle WebSocket connections from browser extensions.

    path is optional: websockets>=14 no longer passes it to handlers.

    The first frame must be a JSON object carrying the API token; otherwise
    any local process could register as the browser and receive automation
    commands or forge responses.
    """
    try:
        first_frame = await asyncio.wait_for(websocket.recv(), timeout=10.0)
        auth = json.loads(first_frame)
        authorized = isinstance(auth, dict) and secrets.compare_digest(
            str(auth.get('token', '')), API_TOKEN)
    except Exception:
        authorized = False

    if not authorized:
        logger.warning("WebSocket connection refused: missing or invalid token")
        try:
            await websocket.close(1008, 'auth required')
        except Exception:
            pass
        return

    browser_id = f"browser_{id(websocket)}"
    connection_manager.register_browser(browser_id, websocket)

    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                logger.debug(f"Received from browser: {data}")

                if 'requestId' in data:
                    # This is a response to a command
                    connection_manager.handle_response(data)
                else:
                    # This is an event from the browser
                    logger.info(f"Browser event: {data.get('type', 'unknown')}")

            except json.JSONDecodeError:
                logger.error(f"Invalid JSON from browser: {message}")

    except websockets.exceptions.ConnectionClosed:
        logger.info(f"Browser disconnected: {browser_id}")
    finally:
        connection_manager.unregister_browser(browser_id)


async def run_websocket_server():
    """Run the WebSocket server."""
    global MAIN_EVENT_LOOP
    MAIN_EVENT_LOOP = asyncio.get_running_loop()

    if not HAS_WEBSOCKETS:
        logger.warning("websockets module not installed, WebSocket server disabled")
        return

    server = await websockets.serve(websocket_handler, HOST, WS_PORT)
    logger.info(f"WebSocket server starting on {HOST}:{WS_PORT}")
    await server.wait_closed()


async def run_with_headless():
    """Run WebSocket server alongside headless browser startup."""
    global MAIN_EVENT_LOOP
    from headless_backend import init_headless_browser
    # Publish this loop before awaiting anything slow, so HTTP worker threads
    # can dispatch onto it as soon as the browser is up.
    MAIN_EVENT_LOOP = asyncio.get_running_loop()
    headless = await init_headless_browser()
    logger.info("Headless browser ready")

    if HAS_WEBSOCKETS:
        await run_websocket_server()
    else:
        # No WebSocket but headless is running — just keep the event loop alive
        await asyncio.Event().wait()

    await headless.stop()


def main():
    """Main entry point."""
    mode_label = "HEADLESS (Playwright)" if HEADLESS_MODE else "EXTENSION (Firefox/native-host)"
    print(f"""
+--------------------------------------------------------------+
|           ClaudeCodeBrowser MCP Server v1.4.0                |
+--------------------------------------------------------------+
|  Mode:             {mode_label:<40} |
|  HTTP Server:      http://{HOST}:{HTTP_PORT:<5}                       |
|  WebSocket Server: ws://{HOST}:{WS_PORT:<5}                         |
|  Screenshots:      {str(SCREENSHOTS_DIR):<40} |
|  Logs:             {str(LOG_FILE):<40} |
+--------------------------------------------------------------+
    """)

    # Start HTTP server in a thread (always needed)
    http_thread = threading.Thread(target=run_http_server, daemon=True)
    http_thread.start()

    if HEADLESS_MODE:
        asyncio.run(run_with_headless())
    elif HAS_WEBSOCKETS:
        asyncio.run(run_websocket_server())
    else:
        # If no websockets, just keep the HTTP server running
        logger.info("Running HTTP server only (install websockets for WebSocket support)")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Server shutting down")


if __name__ == '__main__':
    main()
