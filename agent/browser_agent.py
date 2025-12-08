#!/usr/bin/env python3
"""
ClaudeCodeBrowser Agent

A specialized agent for browser automation that can be called from Claude Code.
This agent provides high-level browser automation capabilities using natural language.

MIT License
Copyright (c) 2025 Andre Watson (nanogenomic), Ligandal Inc.
Author: dre@ligandal.com
"""

import asyncio
import json
import os
import sys
import time
import base64
import argparse
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass
import urllib.request
import urllib.error

# Configuration
MCP_SERVER_URL = os.environ.get('CLAUDE_BROWSER_URL', 'http://127.0.0.1:8765')
SCREENSHOTS_DIR = Path.home() / '.claudecodebrowser' / 'screenshots'


@dataclass
class BrowserAction:
    """Represents a browser automation action."""
    action_type: str
    description: str
    parameters: Dict[str, Any]
    result: Optional[Dict[str, Any]] = None
    success: bool = False
    error: Optional[str] = None


class BrowserAutomationAgent:
    """
    Agent for browser automation tasks.

    This agent can interpret natural language commands and execute
    browser automation tasks through the MCP server.
    """

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.action_history: List[BrowserAction] = []
        self.current_page_info: Optional[Dict[str, Any]] = None

    def log(self, message: str):
        """Log a message if verbose mode is enabled."""
        if self.verbose:
            print(f"[BrowserAgent] {message}")

    def _make_request(self, endpoint: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Make an HTTP request to the MCP server."""
        url = f"{MCP_SERVER_URL}{endpoint}"

        try:
            if data:
                req = urllib.request.Request(
                    url,
                    data=json.dumps(data).encode('utf-8'),
                    headers={'Content-Type': 'application/json'}
                )
            else:
                req = urllib.request.Request(url)

            with urllib.request.urlopen(req, timeout=30) as response:
                return json.loads(response.read().decode('utf-8'))

        except urllib.error.URLError as e:
            return {'success': False, 'error': f'Connection failed: {str(e)}'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def call_tool(self, tool_name: str, **kwargs) -> Dict[str, Any]:
        """Call an MCP tool."""
        self.log(f"Calling tool: {tool_name}")
        self.log(f"Arguments: {kwargs}")

        result = self._make_request('/mcp/call', {
            'name': tool_name,
            'arguments': kwargs
        })

        action = BrowserAction(
            action_type=tool_name,
            description=f"Called {tool_name}",
            parameters=kwargs,
            result=result,
            success=result.get('success', False),
            error=result.get('error')
        )
        self.action_history.append(action)

        if self.verbose:
            if result.get('success'):
                self.log(f"Success: {result}")
            else:
                self.log(f"Error: {result.get('error')}")

        return result

    def check_server(self) -> bool:
        """Check if the MCP server is running."""
        result = self._make_request('/health')
        return result.get('status') == 'ok'

    # High-level actions

    def screenshot(self, filename: Optional[str] = None, full_page: bool = False) -> Dict[str, Any]:
        """Take a screenshot of the current page."""
        return self.call_tool(
            'browser_screenshot',
            filename=filename,
            full_page=full_page,
            save_to_file=True
        )

    def navigate(self, url: str, new_tab: bool = False) -> Dict[str, Any]:
        """Navigate to a URL."""
        return self.call_tool('browser_navigate', url=url, new_tab=new_tab)

    def click(self,
              selector: Optional[str] = None,
              text: Optional[str] = None,
              xpath: Optional[str] = None,
              x: Optional[int] = None,
              y: Optional[int] = None,
              double_click: bool = False,
              right_click: bool = False) -> Dict[str, Any]:
        """Click on an element."""
        kwargs = {}
        if selector:
            kwargs['selector'] = selector
        if text:
            kwargs['text'] = text
        if xpath:
            kwargs['xpath'] = xpath
        if x is not None and y is not None:
            kwargs['x'] = x
            kwargs['y'] = y
        kwargs['double_click'] = double_click
        kwargs['right_click'] = right_click

        return self.call_tool('browser_click', **kwargs)

    def type_text(self,
                  text: str,
                  selector: Optional[str] = None,
                  placeholder: Optional[str] = None,
                  name: Optional[str] = None,
                  element_id: Optional[str] = None,
                  clear: bool = False,
                  press_enter: bool = False) -> Dict[str, Any]:
        """Type text into an element."""
        kwargs = {'text': text, 'clear': clear, 'press_enter': press_enter}
        if selector:
            kwargs['selector'] = selector
        if placeholder:
            kwargs['placeholder'] = placeholder
        if name:
            kwargs['name'] = name
        if element_id:
            kwargs['id'] = element_id

        return self.call_tool('browser_type', **kwargs)

    def scroll(self,
               direction: str = 'down',
               amount: int = 300,
               to_element: Optional[str] = None) -> Dict[str, Any]:
        """Scroll the page."""
        kwargs = {'direction': direction, 'amount': amount}
        if to_element:
            kwargs['to_element'] = to_element

        return self.call_tool('browser_scroll', **kwargs)

    def get_page_info(self) -> Dict[str, Any]:
        """Get information about the current page."""
        result = self.call_tool('browser_get_page_info')
        if result.get('success'):
            self.current_page_info = result
        return result

    def get_elements(self, selector: str, limit: int = 50) -> Dict[str, Any]:
        """Get elements matching a selector."""
        return self.call_tool('browser_get_elements', selector=selector, limit=limit)

    def wait_for_element(self, selector: str, timeout: int = 10000, visible: bool = True) -> Dict[str, Any]:
        """Wait for an element to appear."""
        return self.call_tool('browser_wait_for_element', selector=selector, timeout=timeout, visible=visible)

    def highlight(self, selector: str, duration: int = 3000, label: Optional[str] = None) -> Dict[str, Any]:
        """Highlight an element."""
        kwargs = {'selector': selector, 'duration': duration}
        if label:
            kwargs['label'] = label
        return self.call_tool('browser_highlight', **kwargs)

    def execute_script(self, script: str) -> Dict[str, Any]:
        """Execute JavaScript in the browser."""
        return self.call_tool('browser_execute_script', script=script)

    def get_tabs(self) -> Dict[str, Any]:
        """Get list of browser tabs."""
        return self.call_tool('browser_get_tabs')

    def new_tab(self, url: str = 'about:blank') -> Dict[str, Any]:
        """Create a new tab."""
        return self.call_tool('browser_create_tab', url=url)

    def close_tab(self, tab_id: int) -> Dict[str, Any]:
        """Close a tab."""
        return self.call_tool('browser_close_tab', tab_id=tab_id)

    def focus_tab(self, tab_id: int) -> Dict[str, Any]:
        """Focus a tab."""
        return self.call_tool('browser_focus_tab', tab_id=tab_id)

    def get_value(self, selector: str) -> Dict[str, Any]:
        """Get the value of an input element."""
        return self.call_tool('browser_get_value', selector=selector)

    def set_value(self, selector: str, value: str) -> Dict[str, Any]:
        """Set the value of an input element."""
        return self.call_tool('browser_set_value', selector=selector, value=value)

    def select_option(self, selector: str, value: Optional[str] = None, text: Optional[str] = None, index: Optional[int] = None) -> Dict[str, Any]:
        """Select an option in a dropdown."""
        kwargs = {'selector': selector}
        if value:
            kwargs['value'] = value
        if text:
            kwargs['text'] = text
        if index is not None:
            kwargs['index'] = index
        return self.call_tool('browser_select_option', **kwargs)

    def hover(self, selector: str) -> Dict[str, Any]:
        """Hover over an element."""
        return self.call_tool('browser_hover', selector=selector)

    # Refresh/Reload functionality

    def refresh(self, bypass_cache: bool = False, wait_for_load: bool = True) -> Dict[str, Any]:
        """Refresh the current page."""
        return self.call_tool('browser_refresh', bypass_cache=bypass_cache, wait_for_load=wait_for_load)

    def hard_refresh(self) -> Dict[str, Any]:
        """Force refresh bypassing cache (like Ctrl+Shift+R)."""
        return self.call_tool('browser_hard_refresh')

    def reload_all(self, url_pattern: Optional[str] = None, bypass_cache: bool = True) -> Dict[str, Any]:
        """Reload all browser tabs, optionally filtered by URL pattern."""
        kwargs = {'bypass_cache': bypass_cache}
        if url_pattern:
            kwargs['url_pattern'] = url_pattern
        return self.call_tool('browser_reload_all', **kwargs)

    def reload_by_url(self, url: Optional[str] = None, url_pattern: Optional[str] = None, bypass_cache: bool = True) -> Dict[str, Any]:
        """Reload all tabs matching a specific URL or pattern."""
        kwargs = {'bypass_cache': bypass_cache}
        if url:
            kwargs['url'] = url
        if url_pattern:
            kwargs['url_pattern'] = url_pattern
        return self.call_tool('browser_reload_by_url', **kwargs)

    def reload_localhost(self, port: Optional[int] = None) -> Dict[str, Any]:
        """Reload all localhost tabs. Optionally filter by port number."""
        if port:
            return self.reload_by_url(url=f'http://localhost:{port}')
        return self.reload_by_url(url_pattern=r'https?://localhost')

    def reload_dev_servers(self) -> Dict[str, Any]:
        """Reload all common dev server tabs (localhost, 127.0.0.1, dev domains)."""
        return self.reload_by_url(url_pattern=r'https?://(localhost|127\.0\.0\.1|.*\.local|.*\.dev)')

    # Workflow helpers

    def fill_form(self, fields: Dict[str, str], submit: bool = False, submit_selector: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Fill a form with the given field values.

        Args:
            fields: Dictionary mapping field selectors/names to values
            submit: Whether to submit the form after filling
            submit_selector: CSS selector for the submit button
        """
        results = []

        for field, value in fields.items():
            # Try different strategies to find the field
            if field.startswith('#') or field.startswith('.') or field.startswith('['):
                result = self.type_text(value, selector=field, clear=True)
            elif '=' in field:
                result = self.type_text(value, selector=f'[{field}]', clear=True)
            else:
                # Try by name, then by placeholder
                result = self.type_text(value, name=field, clear=True)
                if not result.get('success'):
                    result = self.type_text(value, placeholder=field, clear=True)

            results.append(result)

        if submit:
            if submit_selector:
                results.append(self.click(selector=submit_selector))
            else:
                # Try common submit selectors
                for selector in ['button[type="submit"]', 'input[type="submit"]', 'button:contains("Submit")', '.submit-btn']:
                    result = self.click(selector=selector)
                    if result.get('success'):
                        results.append(result)
                        break

        return results

    def search(self, query: str, search_selector: str = 'input[type="search"], input[name="q"], #search') -> Dict[str, Any]:
        """Perform a search on the current page."""
        self.type_text(query, selector=search_selector, clear=True)
        return self.type_text('', selector=search_selector, press_enter=True)

    def login(self, username: str, password: str,
              username_selector: str = '#username, input[name="username"], input[type="email"]',
              password_selector: str = '#password, input[name="password"], input[type="password"]',
              submit_selector: Optional[str] = None) -> List[Dict[str, Any]]:
        """Perform a login."""
        results = [
            self.type_text(username, selector=username_selector, clear=True),
            self.type_text(password, selector=password_selector, clear=True)
        ]

        if submit_selector:
            results.append(self.click(selector=submit_selector))
        else:
            results.append(self.type_text('', selector=password_selector, press_enter=True))

        return results

    def extract_text(self, selector: str) -> Optional[str]:
        """Extract text content from elements matching selector."""
        result = self.execute_script(f"""
            const elements = document.querySelectorAll('{selector}');
            return Array.from(elements).map(el => el.textContent.trim()).filter(t => t).join('\\n');
        """)
        if result.get('success'):
            return result.get('result')
        return None

    def extract_links(self, selector: str = 'a[href]') -> List[Dict[str, str]]:
        """Extract links from the page."""
        result = self.execute_script(f"""
            const links = document.querySelectorAll('{selector}');
            return Array.from(links).map(a => ({{
                text: a.textContent.trim(),
                href: a.href
            }})).filter(l => l.href);
        """)
        if result.get('success') and result.get('result'):
            return result['result']
        return []


def interactive_mode(agent: BrowserAutomationAgent):
    """Run the agent in interactive mode."""
    print("""
╔══════════════════════════════════════════════════════════════╗
║          ClaudeCodeBrowser Interactive Agent                 ║
╠══════════════════════════════════════════════════════════════╣
║  Commands:                                                   ║
║    screenshot [filename]  - Take a screenshot                ║
║    navigate <url>         - Go to a URL                      ║
║    click <selector>       - Click an element                 ║
║    type <text>            - Type text                        ║
║    scroll <direction>     - Scroll the page                  ║
║    refresh                - Refresh current page             ║
║    hardrefresh            - Force refresh (bypass cache)     ║
║    reloadall [pattern]    - Reload all/matching tabs         ║
║    info                   - Get page information             ║
║    tabs                   - List browser tabs                ║
║    help                   - Show all commands                ║
║    exit                   - Exit interactive mode            ║
╚══════════════════════════════════════════════════════════════╝
    """)

    while True:
        try:
            cmd = input("\n> ").strip()
            if not cmd:
                continue

            parts = cmd.split(maxsplit=1)
            command = parts[0].lower()
            args = parts[1] if len(parts) > 1 else ''

            if command == 'exit' or command == 'quit':
                print("Goodbye!")
                break

            elif command == 'screenshot':
                result = agent.screenshot(filename=args if args else None)
                print(json.dumps(result, indent=2))

            elif command == 'navigate' or command == 'goto' or command == 'go':
                if not args:
                    print("Usage: navigate <url>")
                    continue
                result = agent.navigate(args)
                print(json.dumps(result, indent=2))

            elif command == 'click':
                if not args:
                    print("Usage: click <selector>")
                    continue
                result = agent.click(selector=args)
                print(json.dumps(result, indent=2))

            elif command == 'type':
                if not args:
                    print("Usage: type <text>")
                    continue
                result = agent.type_text(args)
                print(json.dumps(result, indent=2))

            elif command == 'scroll':
                direction = args if args else 'down'
                result = agent.scroll(direction=direction)
                print(json.dumps(result, indent=2))

            elif command == 'refresh' or command == 'reload':
                result = agent.refresh()
                print(json.dumps(result, indent=2))

            elif command == 'hardrefresh' or command == 'hard-refresh' or command == 'force-refresh':
                result = agent.hard_refresh()
                print(json.dumps(result, indent=2))

            elif command == 'reloadall' or command == 'reload-all':
                result = agent.reload_all(url_pattern=args if args else None)
                print(json.dumps(result, indent=2))

            elif command == 'reloadlocal' or command == 'reload-localhost':
                port = int(args) if args and args.isdigit() else None
                result = agent.reload_localhost(port=port)
                print(json.dumps(result, indent=2))

            elif command == 'reloaddev' or command == 'reload-dev':
                result = agent.reload_dev_servers()
                print(json.dumps(result, indent=2))

            elif command == 'info' or command == 'pageinfo':
                result = agent.get_page_info()
                print(json.dumps(result, indent=2))

            elif command == 'tabs':
                result = agent.get_tabs()
                print(json.dumps(result, indent=2))

            elif command == 'elements':
                if not args:
                    print("Usage: elements <selector>")
                    continue
                result = agent.get_elements(args)
                print(json.dumps(result, indent=2))

            elif command == 'highlight':
                if not args:
                    print("Usage: highlight <selector>")
                    continue
                result = agent.highlight(args)
                print(json.dumps(result, indent=2))

            elif command == 'exec' or command == 'js':
                if not args:
                    print("Usage: exec <javascript>")
                    continue
                result = agent.execute_script(args)
                print(json.dumps(result, indent=2))

            elif command == 'help':
                print("""
Available commands:
  screenshot [filename]    - Take a screenshot
  navigate/goto <url>      - Navigate to a URL
  click <selector>         - Click on an element
  type <text>              - Type text into focused element
  scroll [up|down|left|right|top|bottom]  - Scroll the page
  refresh                  - Refresh current page
  hardrefresh              - Force refresh (bypass cache, like Ctrl+Shift+R)
  reloadall [pattern]      - Reload all tabs (optionally matching pattern)
  reloadlocal [port]       - Reload all localhost tabs
  reloaddev                - Reload all dev server tabs
  info                     - Get page information
  tabs                     - List browser tabs
  elements <selector>      - Find elements
  highlight <selector>     - Highlight an element
  exec <js>                - Execute JavaScript
  help                     - Show this help
  exit                     - Exit interactive mode
                """)

            else:
                print(f"Unknown command: {command}. Type 'help' for available commands.")

        except KeyboardInterrupt:
            print("\nInterrupted. Type 'exit' to quit.")
        except Exception as e:
            print(f"Error: {e}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='ClaudeCodeBrowser Agent')
    parser.add_argument('--interactive', '-i', action='store_true', help='Run in interactive mode')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--check', action='store_true', help='Check if MCP server is running')
    parser.add_argument('--command', '-c', help='Execute a single command')
    parser.add_argument('--screenshot', '-s', nargs='?', const='screenshot.png', help='Take a screenshot')
    parser.add_argument('--navigate', '-n', help='Navigate to URL')
    parser.add_argument('--info', action='store_true', help='Get page info')
    parser.add_argument('--refresh', '-r', action='store_true', help='Refresh current page')
    parser.add_argument('--hard-refresh', '-R', action='store_true', help='Hard refresh (bypass cache)')
    parser.add_argument('--reload-all', action='store_true', help='Reload all browser tabs')
    parser.add_argument('--reload-localhost', nargs='?', const=True, help='Reload localhost tabs (optionally specify port)')
    parser.add_argument('--reload-dev', action='store_true', help='Reload all dev server tabs')
    parser.add_argument('--reload-url', help='Reload tabs matching URL pattern')

    args = parser.parse_args()

    agent = BrowserAutomationAgent(verbose=args.verbose)

    if args.check:
        if agent.check_server():
            print("MCP server is running")
            sys.exit(0)
        else:
            print("MCP server is not available")
            sys.exit(1)

    if args.screenshot:
        result = agent.screenshot(filename=args.screenshot)
        print(json.dumps(result, indent=2))

    elif args.navigate:
        result = agent.navigate(args.navigate)
        print(json.dumps(result, indent=2))

    elif args.info:
        result = agent.get_page_info()
        print(json.dumps(result, indent=2))

    elif args.refresh:
        result = agent.refresh()
        print(json.dumps(result, indent=2))

    elif args.hard_refresh:
        result = agent.hard_refresh()
        print(json.dumps(result, indent=2))

    elif args.reload_all:
        result = agent.reload_all()
        print(json.dumps(result, indent=2))

    elif args.reload_localhost:
        port = int(args.reload_localhost) if isinstance(args.reload_localhost, str) and args.reload_localhost.isdigit() else None
        result = agent.reload_localhost(port=port)
        print(json.dumps(result, indent=2))

    elif args.reload_dev:
        result = agent.reload_dev_servers()
        print(json.dumps(result, indent=2))

    elif args.reload_url:
        result = agent.reload_by_url(url_pattern=args.reload_url)
        print(json.dumps(result, indent=2))

    elif args.command:
        # Parse and execute a command string
        parts = args.command.split(maxsplit=1)
        cmd = parts[0]
        cmd_args = parts[1] if len(parts) > 1 else ''

        method = getattr(agent, cmd, None)
        if method and callable(method):
            result = method(cmd_args) if cmd_args else method()
            print(json.dumps(result, indent=2))
        else:
            print(f"Unknown command: {cmd}")

    elif args.interactive:
        if not agent.check_server():
            print("Warning: MCP server is not available. Start the server first.")
        interactive_mode(agent)

    else:
        # Default: show help
        parser.print_help()


if __name__ == '__main__':
    main()
