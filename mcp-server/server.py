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
        description="Get list of all open browser tabs.",
        input_schema={
            "type": "object",
            "properties": {}
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
    )
]


class BrowserConnectionManager:
    """Manages connections to browser extensions."""

    def __init__(self):
        self.browser_connections = {}
        self.pending_requests = {}
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

    async def send_command(self, command: BrowserCommand) -> Dict[str, Any]:
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
            result = await asyncio.wait_for(future, timeout=30.0)
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
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def do_OPTIONS(self):
        """Handle CORS preflight requests."""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        """Handle GET requests."""
        parsed = urlparse(self.path)

        if parsed.path == '/health':
            self.send_json_response({
                'status': 'ok',
                'timestamp': datetime.now().isoformat(),
                'version': '1.0.0',
                'browsers_connected': len(connection_manager.browser_connections)
            })

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

        else:
            self.send_json_response({'error': 'Not found'}, 404)

    def do_POST(self):
        """Handle POST requests."""
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
        logger.info(f"Executing tool: {tool_name} with args: {arguments}")

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
            'browser_click_and_wait': 'clickAndWait'
        }

        if tool_name not in tool_action_map:
            return {'success': False, 'error': f'Unknown tool: {tool_name}'}

        action = tool_action_map[tool_name]
        tab_id = arguments.pop('tab_id', None)

        # Check if we have a browser connection via WebSocket
        browser = connection_manager.get_active_browser()

        if browser:
            # Use async WebSocket communication
            command = BrowserCommand(
                action=action,
                tab_id=tab_id,
                data=arguments
            )

            # Run async command in event loop
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # We're in a sync context, need to handle differently
                    future = asyncio.run_coroutine_threadsafe(
                        connection_manager.send_command(command),
                        loop
                    )
                    result = future.result(timeout=30)
                else:
                    result = loop.run_until_complete(connection_manager.send_command(command))

                # Handle screenshot saving
                if action == 'screenshot' and result.get('success') and result.get('data'):
                    return self._save_screenshot(result, arguments)

                return result
            except Exception as e:
                logger.error(f"WebSocket command failed: {e}")
                # Fall through to HTTP method

        # No WebSocket connection - try HTTP polling with native host
        # The extension polls /browser/poll and we store commands there
        command_data = {
            'action': action,
            'tabId': tab_id,
            'data': arguments,
            'requestId': str(time.time())
        }

        # Store command for extension to poll
        self.server._pending_commands = getattr(self.server, '_pending_commands', [])
        self.server._pending_commands.append(command_data)

        # For screenshot specifically, we can return info about where to save
        if action == 'screenshot':
            filename = arguments.get('filename') or f'screenshot_{datetime.now().strftime("%Y%m%d_%H%M%S")}.png'
            filepath = SCREENSHOTS_DIR / filename
            return {
                'success': True,
                'message': 'Screenshot command queued',
                'save_path': str(filepath),
                'screenshots_dir': str(SCREENSHOTS_DIR),
                'action': action,
                'note': 'Screenshot will be saved when browser extension responds'
            }

        return {
            'success': True,
            'message': f'Command {action} queued for browser',
            'action': action
        }

    def _save_screenshot(self, result: Dict[str, Any], arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Save screenshot data to file."""
        try:
            data = result.get('data', '')
            save_to_file = arguments.get('save_to_file', True)
            filename = arguments.get('filename') or f'screenshot_{datetime.now().strftime("%Y%m%d_%H%M%S")}.png'

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


def run_http_server():
    """Run the HTTP server."""
    server = HTTPServer((HOST, HTTP_PORT), MCPHTTPHandler)
    logger.info(f"HTTP server starting on {HOST}:{HTTP_PORT}")
    server.serve_forever()


async def websocket_handler(websocket, path):
    """Handle WebSocket connections from browser extensions."""
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
    if not HAS_WEBSOCKETS:
        logger.warning("websockets module not installed, WebSocket server disabled")
        return

    server = await websockets.serve(websocket_handler, HOST, WS_PORT)
    logger.info(f"WebSocket server starting on {HOST}:{WS_PORT}")
    await server.wait_closed()


def main():
    """Main entry point."""
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║           ClaudeCodeBrowser MCP Server v1.0.0                ║
╠══════════════════════════════════════════════════════════════╣
║  HTTP Server:      http://{HOST}:{HTTP_PORT:<5}                       ║
║  WebSocket Server: ws://{HOST}:{WS_PORT:<5}                         ║
║  Screenshots:      {str(SCREENSHOTS_DIR):<40} ║
║  Logs:             {str(LOG_FILE):<40} ║
╚══════════════════════════════════════════════════════════════╝
    """)

    # Start HTTP server in a thread
    http_thread = threading.Thread(target=run_http_server, daemon=True)
    http_thread.start()

    # Run WebSocket server in the main async loop
    if HAS_WEBSOCKETS:
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
