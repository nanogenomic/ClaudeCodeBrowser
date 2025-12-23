# ClaudeCodeBrowser

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Firefox Add-on](https://img.shields.io/badge/Firefox-Add--on-FF7139?logo=firefox-browser)](https://addons.mozilla.org/firefox/)

A Firefox browser automation system for Claude Code that enables AI-powered interaction with web pages. Take screenshots, click elements, type text, navigate pages, and **force refresh browser tabs** when launching development servers.

**Author:** Andre Watson ([@nanogenomic](https://github.com/nanogenomic)) - dre@ligandal.com
**Organization:** [Ligandal Inc.](https://ligandal.com)
**License:** MIT
**Copyright:** 2025 Ligandal Inc.

## Features

- **Screenshots** - Capture visible area or full page screenshots
- **Click Automation** - Click elements by CSS selector, XPath, text, or coordinates
- **Typing** - Type text into inputs with simulated keystrokes
- **Page Navigation** - Navigate to URLs, create/close/focus tabs
- **Page Refresh** - Force refresh tabs after server restarts (bypass cache)
- **Element Inspection** - Find elements, get page info, highlight elements
- **JavaScript Execution** - Run arbitrary JS in browser context
- **MCP Integration** - Model Context Protocol server for Claude Code

## Overview

ClaudeCodeBrowser consists of four main components:

1. **Firefox WebExtension** - Runs in the browser to execute automation commands
2. **Native Messaging Host** - Bridge between the extension and local server
3. **MCP Server** - Model Context Protocol server exposing browser automation tools
4. **Browser Agent** - Python agent for high-level browser automation

## Architecture

### Dual-Server Design

ClaudeCodeBrowser uses a **dual-server architecture** for maximum reliability and flexibility:

| Server | Port | Protocol | Purpose |
|--------|------|----------|---------|
| **HTTP Server** | 8765 | HTTP REST | MCP tool calls, health checks, command polling, screenshot retrieval |
| **WebSocket Server** | 8766 | WebSocket | Real-time browser communication (reserved for future use) |

**Why Two Servers?**
- **HTTP (8765)**: Primary communication channel. Claude Code's MCP client sends tool requests here. The browser extension polls this server every 500ms for pending commands.
- **WebSocket (8766)**: Reserved for real-time bidirectional communication when instant responses are needed.

### Communication Flow

```
┌─────────────────┐     ┌─────────────────────────────────┐
│   Claude Code   │────▶│        MCP Server               │
│   (MCP Client)  │     │  ┌─────────┐  ┌──────────────┐ │
└─────────────────┘     │  │HTTP:8765│  │WebSocket:8766│ │
                        │  └────┬────┘  └──────────────┘ │
                        └───────┼────────────────────────┘
                                │
                                ▼
                        ┌───────────────┐
                        │ Command Queue │◀───────polling────┐
                        │  (In-Memory)  │                   │
                        └───────┬───────┘                   │
                                │                           │
                                ▼                           │
                        ┌───────────────┐          ┌────────┴────────┐
                        │ Native Host   │◀────────▶│Firefox Extension│
                        │   (stdio)     │          │(Background + CS)│
                        └───────────────┘          └────────┬────────┘
                                                            │
                                                            ▼
                                                   ┌─────────────────┐
                                                   │   Web Page      │
                                                   └─────────────────┘
```

### Request Flow (Step by Step)

1. **Claude Code → MCP Server**: Tool call via HTTP POST to `localhost:8765/mcp/call`
2. **MCP Server → Command Queue**: Command is queued with unique ID
3. **Browser Extension → MCP Server**: Extension polls `localhost:8765/browser/poll` every 500ms
4. **MCP Server → Extension**: Pending command returned to extension
5. **Extension → Web Page**: Command executed (screenshot, click, type, etc.)
6. **Extension → MCP Server**: Response posted to `localhost:8765/browser/response`
7. **MCP Server → Claude Code**: Result returned to original MCP call

### Native Host (Optional Path)

The native messaging host (`claudecodebrowser_host.py`) provides an alternative communication path:
- Used when the browser extension needs to communicate with the local file system
- Handles screenshot saving directly to disk at `/tmp/claudecodebrowser/screenshots/`
- Enables clipboard operations and file downloads

## Installation

### Prerequisites

**System Python websockets** (required for WebSocket server on port 8766):
```bash
sudo apt install python3-websockets
```

Without this, the server runs in HTTP-only mode and `browsers_connected` will always show 0.

### Quick Install

```bash
cd /mnt/backup/ClaudeCodeBrowser
./scripts/install.sh
```

### Manual Installation

1. **Install the MCP server and agent:**
   ```bash
   mkdir -p ~/.claudecodebrowser/{native-host,mcp-server,agent,screenshots,logs}
   cp native-host/* ~/.claudecodebrowser/native-host/
   cp mcp-server/* ~/.claudecodebrowser/mcp-server/
   cp agent/* ~/.claudecodebrowser/agent/
   chmod +x ~/.claudecodebrowser/**/*.py
   ```

2. **Install native messaging manifest for Firefox:**
   ```bash
   mkdir -p ~/.mozilla/native-messaging-hosts
   cp native-host/claudecodebrowser.json ~/.mozilla/native-messaging-hosts/
   # Update the path in the JSON file to point to your installation
   ```

3. **Install the Firefox extension:**
   - Open Firefox and go to `about:debugging`
   - Click "This Firefox"
   - Click "Load Temporary Add-on..."
   - Select `extension/manifest.json`

4. **Configure Claude Code MCP:**
   Add to `~/.claude/settings.json`:
   ```json
   {
     "mcpServers": {
       "claudecodebrowser": {
         "command": "python3",
         "args": ["/home/YOUR_USER/.claudecodebrowser/mcp-server/server.py"]
       }
     }
   }
   ```

## Usage

### Starting the MCP Server

```bash
~/.claudecodebrowser/start-server.sh
```

Or directly:
```bash
python3 ~/.claudecodebrowser/mcp-server/server.py
```

The server runs on:
- HTTP: http://127.0.0.1:8765
- WebSocket: ws://127.0.0.1:8766

### Using the Browser Agent

#### Interactive Mode
```bash
python3 ~/.claudecodebrowser/agent/browser_agent.py -i
```

#### Command Line
```bash
# Take a screenshot
browser-agent --screenshot

# Navigate to a URL
browser-agent --navigate https://example.com

# Get page info
browser-agent --info

# Check server status
browser-agent --check
```

#### Python API
```python
from browser_agent import BrowserAutomationAgent

agent = BrowserAutomationAgent(verbose=True)

# Navigate to a page
agent.navigate("https://example.com")

# Take a screenshot
agent.screenshot("example.png")

# Click an element
agent.click(selector="button.submit")

# Type text
agent.type_text("Hello, World!", selector="#search-input")

# Fill a form
agent.fill_form({
    "username": "myuser",
    "password": "mypass"
}, submit=True)
```

### Available MCP Tools

#### Core Navigation & Screenshots
| Tool | Description |
|------|-------------|
| `browser_screenshot` | Take a screenshot (visible area or full page) |
| `browser_navigate` | Navigate to a URL, optionally in new tab |
| `browser_refresh` | Refresh current page |
| `browser_hard_refresh` | Force refresh bypassing cache (Ctrl+Shift+R) |
| `browser_reload_all` | Reload all browser tabs |
| `browser_reload_by_url` | Reload tabs matching URL pattern |

#### Element Interaction
| Tool | Description |
|------|-------------|
| `browser_click` | Click element by selector, XPath, text, or coordinates |
| `browser_type` | Type text into an input field |
| `browser_scroll` | Scroll page or element (up/down/left/right/top/bottom) |
| `browser_hover` | Hover over an element to trigger hover effects |
| `browser_get_value` | Get the value of an input element |
| `browser_set_value` | Set input value directly (no typing simulation) |
| `browser_select_option` | Select an option in a dropdown |

#### Page Inspection
| Tool | Description |
|------|-------------|
| `browser_get_page_info` | Get URL, title, forms, headings, interactive elements |
| `browser_get_elements` | Find elements matching a CSS selector |
| `browser_highlight` | Highlight an element for visual debugging |
| `browser_execute_script` | Execute JavaScript in browser context |

#### Tab Management
| Tool | Description |
|------|-------------|
| `browser_get_tabs` | List all open browser tabs |
| `browser_create_tab` | Create a new tab |
| `browser_close_tab` | Close a tab by ID |
| `browser_focus_tab` | Focus/activate a tab by ID |

#### Waiting & Synchronization
| Tool | Description |
|------|-------------|
| `browser_wait_for_element` | Wait for element to appear on page |
| `browser_wait_for_change` | Wait for DOM changes (useful after clicks) |
| `browser_wait_for_network_idle` | Wait for fetch/XHR requests to settle |
| `browser_click_and_wait` | Click element and wait for DOM changes |

#### Advanced Observation
| Tool | Description |
|------|-------------|
| `browser_observe_element` | Start observing element for changes |
| `browser_stop_observing` | Stop observing and get accumulated changes |
| `browser_scroll_and_capture` | Scroll through page capturing element info |

#### Console & Network Logging
| Tool | Description |
|------|-------------|
| `browser_start_logging` | Start capturing console logs and network requests |
| `browser_stop_logging` | Stop capturing logs (logs are preserved) |
| `browser_get_console_logs` | Retrieve captured console.log/error/warn/info/debug |
| `browser_get_network_logs` | Retrieve captured fetch/XHR requests and responses |
| `browser_clear_logs` | Clear all captured logs |

### Console & Network Logging

Essential for debugging AI chat interfaces and monitoring API communications:

```bash
# Start logging before performing actions
browser-agent --start-logging

# Perform actions that you want to monitor...

# Get console logs (errors, warnings, debug output)
browser-agent --get-console-logs

# Get network logs (API requests and responses)
browser-agent --get-network-logs

# Filter console logs by level
browser-agent --get-console-logs --level error

# Filter network logs by URL pattern
browser-agent --get-network-logs --url-pattern "api/chat"

# Stop logging
browser-agent --stop-logging
```

#### Python API for Logging
```python
agent = BrowserAutomationAgent()

# Start logging
agent.start_logging(clear_existing=True)

# Perform actions...
agent.navigate("https://example.com/chat")
agent.type_text("Hello!", selector="#chat-input")
agent.click(selector="#send-button")

# Get console logs
console_logs = agent.get_console_logs(level="error")  # Filter by level
for log in console_logs['logs']:
    print(f"[{log['level']}] {log['message']}")

# Get network logs
network_logs = agent.get_network_logs(url_pattern="api/chat")
for req in network_logs['logs']:
    print(f"{req['method']} {req['url']} -> {req['status']}")
    print(f"Response: {req['responseBody'][:200]}...")

# Stop logging
agent.stop_logging()
```

#### Use Cases
- **Debug AI Chat Interfaces**: See console errors and API request/response data
- **Monitor API Communications**: Track all fetch/XHR requests with full bodies
- **Troubleshoot Errors**: Filter console logs by error level
- **Verify Integrations**: Confirm API calls are being made correctly

### Page Refresh Commands

Essential for development workflows - refresh browser tabs after server restarts:

```bash
# Refresh current tab
browser-agent --refresh

# Hard refresh (bypass cache) - like Ctrl+Shift+R
browser-agent --hard-refresh

# Reload all browser tabs
browser-agent --reload-all

# Reload all localhost tabs
browser-agent --reload-localhost

# Reload localhost on specific port
browser-agent --reload-localhost 5000

# Reload all dev server tabs (localhost, 127.0.0.1, *.local, *.dev)
browser-agent --reload-dev

# Reload tabs matching URL pattern
browser-agent --reload-url "ligandal"
```

#### Python API for Refresh
```python
agent = BrowserAutomationAgent()

# Refresh current page
agent.refresh()

# Hard refresh (bypass cache)
agent.hard_refresh()

# Reload all localhost tabs
agent.reload_localhost()

# Reload localhost:5000 specifically
agent.reload_localhost(port=5000)

# Reload all dev server tabs
agent.reload_dev_servers()

# Reload tabs matching pattern
agent.reload_by_url(url_pattern=r"localhost:500[0-9]")
```

### Tool Parameters

#### browser_click
```json
{
  "selector": "CSS selector",
  "xpath": "XPath expression",
  "text": "Text to find and click",
  "x": 100,
  "y": 200,
  "double_click": false,
  "right_click": false
}
```

#### browser_type
```json
{
  "text": "Text to type",
  "selector": "CSS selector",
  "placeholder": "Placeholder text",
  "name": "Input name",
  "clear": true,
  "press_enter": true,
  "delay": 50
}
```

#### browser_scroll
```json
{
  "direction": "down",
  "amount": 300,
  "to_element": "CSS selector"
}
```

## API Endpoints

### HTTP API (Port 8765)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Server health check |
| `/mcp/tools` | GET | List available MCP tools |
| `/mcp/call` | POST | Execute an MCP tool |
| `/screenshots` | GET | List saved screenshots |
| `/browser/command` | POST | Send direct browser command |
| `/browser/response` | POST | Receive browser response |

### Example API Calls

```bash
# Health check
curl http://localhost:8765/health

# List tools
curl http://localhost:8765/mcp/tools

# Take screenshot
curl -X POST http://localhost:8765/mcp/call \
  -H "Content-Type: application/json" \
  -d '{"name": "browser_screenshot", "arguments": {}}'

# Click element
curl -X POST http://localhost:8765/mcp/call \
  -H "Content-Type: application/json" \
  -d '{"name": "browser_click", "arguments": {"selector": "button.login"}}'
```

## File Locations

| Path | Description |
|------|-------------|
| `~/.claudecodebrowser/` | Main installation directory |
| `~/.claudecodebrowser/screenshots/` | Saved screenshots |
| `~/.claudecodebrowser/logs/` | Log files |
| `~/.mozilla/native-messaging-hosts/` | Firefox native messaging manifests |

## Troubleshooting

### Extension not loading
- Ensure manifest.json is valid JSON
- Check Firefox console for errors
- Verify the extension ID matches in native messaging manifest

### Native messaging not working
- Check that the path in `claudecodebrowser.json` is correct
- Ensure the host script is executable
- Check `~/.claudecodebrowser/logs/native_host.log`

### Server connection issues
- Verify the server is running: `curl http://localhost:8765/health`
- Check `~/.claudecodebrowser/logs/mcp_server.log`
- Ensure no firewall is blocking local connections

### Screenshots not saving
- Check write permissions for `~/.claudecodebrowser/screenshots/`
- Verify the browser has the page fully loaded

## Development

### Running in development mode

1. Start the MCP server with debug logging:
   ```bash
   python3 mcp-server/server.py
   ```

2. Load the extension temporarily in Firefox

3. Use the browser agent in verbose mode:
   ```bash
   python3 agent/browser_agent.py -i -v
   ```

### Extension debugging
- Open Firefox Developer Tools (F12)
- Go to the Console tab
- Filter by "ClaudeCodeBrowser"

## Security Considerations

- The server only binds to localhost (127.0.0.1) by default
- Native messaging is restricted to the specific extension ID
- Screenshots are stored locally in user's home directory
- No data is sent to external servers

## License

MIT License - Copyright (c) 2025 Andre Watson (nanogenomic), Ligandal Inc.

See [LICENSE](LICENSE) for full details.
