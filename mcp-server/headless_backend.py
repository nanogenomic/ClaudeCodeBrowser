#!/usr/bin/env python3
"""
Headless browser backend for ClaudeCodeBrowser.

Uses Playwright to drive Firefox (or Chromium) without a display.
Activated when CLAUDE_BROWSER_HEADLESS=1 or --headless is passed.

Install: pip install playwright && playwright install firefox
"""

import asyncio
import base64
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger('ClaudeCodeBrowser.Headless')

SCREENSHOTS_DIR = Path(os.environ.get(
    'CLAUDE_BROWSER_SCREENSHOTS_DIR',
    '/tmp/claudecodebrowser/screenshots'
))
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

# Firefox vs Chromium: default Firefox to match the visible-mode extension
BROWSER_TYPE = os.environ.get('CLAUDE_BROWSER_ENGINE', 'firefox')


class HeadlessBrowser:
    """Playwright-backed headless browser. One persistent context per server lifetime."""

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._lock = asyncio.Lock()

    async def start(self):
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise RuntimeError(
                "playwright not installed. Run: pip install playwright && playwright install firefox"
            )

        self._playwright = await async_playwright().start()
        launcher = getattr(self._playwright, BROWSER_TYPE)
        self._browser = await launcher.launch(headless=True)
        self._context = await self._browser.new_context(
            viewport={'width': 1280, 'height': 800}
        )
        self._page = await self._context.new_page()

        # Wire up persistent console + network logging to stderr
        self._page.on('console', lambda m: logger.debug(f"[browser:console:{m.type}] {m.text}"))
        self._page.on('pageerror', lambda e: logger.warning(f"[browser:pageerror] {e}"))
        self._page.on('request', lambda r: logger.debug(f"[browser:request] {r.method} {r.url}"))
        self._page.on('response', lambda r: logger.debug(f"[browser:response] {r.status} {r.url}"))

        logger.info(f"Headless {BROWSER_TYPE} started")

    async def stop(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("Headless browser stopped")

    async def _get_page(self, tab_id: Optional[int] = None):
        """Return the active page (tab_id ignored for now; multi-tab support TODO)."""
        if self._page is None:
            raise RuntimeError("Headless browser not started")
        return self._page

    async def execute(self, action: str, tab_id: Optional[int], arguments: Dict[str, Any]) -> Dict[str, Any]:
        async with self._lock:
            try:
                return await self._dispatch(action, tab_id, arguments)
            except Exception as e:
                logger.error(f"Headless {action} failed: {e}")
                return {'success': False, 'error': str(e)}

    async def _dispatch(self, action: str, tab_id, args: Dict[str, Any]) -> Dict[str, Any]:
        page = await self._get_page(tab_id)

        if action == 'navigate':
            url = args.get('url', '')
            await page.goto(url, wait_until='domcontentloaded', timeout=30000)
            return {'success': True, 'url': page.url, 'title': await page.title()}

        elif action == 'screenshot':
            from datetime import datetime
            filename = Path(args.get('filename') or f'screenshot_{datetime.now().strftime("%Y%m%d_%H%M%S")}.png').name
            filepath = SCREENSHOTS_DIR / filename
            await page.screenshot(path=str(filepath), full_page=args.get('full_page', False))
            data = filepath.read_bytes()
            return {
                'success': True,
                'filepath': str(filepath),
                'filename': filename,
                'size': len(data),
                'message': f'Screenshot saved to {filepath}'
            }

        elif action == 'click':
            selector = args.get('selector')
            x, y = args.get('x'), args.get('y')
            if selector:
                await page.click(selector, timeout=10000)
            elif x is not None and y is not None:
                await page.mouse.click(float(x), float(y))
            else:
                return {'success': False, 'error': 'click requires selector or x+y coordinates'}
            return {'success': True}

        elif action == 'type':
            selector = args.get('selector')
            text = args.get('text', '')
            if selector:
                await page.fill(selector, text)
            else:
                await page.keyboard.type(text)
            return {'success': True}

        elif action == 'scroll':
            x = args.get('x', 0)
            y = args.get('y', 0)
            delta_x = args.get('deltaX', 0)
            delta_y = args.get('deltaY', 300)
            await page.mouse.wheel(float(delta_x), float(delta_y))
            return {'success': True}

        elif action == 'getPageInfo':
            return {
                'success': True,
                'url': page.url,
                'title': await page.title(),
            }

        elif action == 'getElements':
            selector = args.get('selector', 'a, button, input, select, textarea')
            elements = await page.query_selector_all(selector)
            results = []
            for el in elements[:50]:
                try:
                    tag = await el.evaluate('e => e.tagName.toLowerCase()')
                    text = (await el.inner_text())[:100]
                    box = await el.bounding_box()
                    results.append({'tag': tag, 'text': text, 'box': box})
                except Exception:
                    pass
            return {'success': True, 'elements': results}

        elif action == 'executeScript':
            script = args.get('script', '')
            result = await page.evaluate(script)
            return {'success': True, 'result': result}

        elif action == 'waitForElement':
            selector = args.get('selector', '')
            timeout = args.get('timeout', 10000)
            await page.wait_for_selector(selector, timeout=timeout)
            return {'success': True}

        elif action == 'waitForNetworkIdle':
            timeout = args.get('timeout', 10000)
            await page.wait_for_load_state('networkidle', timeout=timeout)
            return {'success': True}

        elif action == 'getTabs':
            pages = self._context.pages
            tabs = [{'id': i, 'url': p.url, 'title': await p.title()} for i, p in enumerate(pages)]
            return {'success': True, 'tabs': tabs}

        elif action == 'createTab':
            url = args.get('url', 'about:blank')
            new_page = await self._context.new_page()
            if url != 'about:blank':
                await new_page.goto(url)
            self._page = new_page
            return {'success': True, 'url': new_page.url}

        elif action == 'getValue':
            selector = args.get('selector', '')
            value = await page.eval_on_selector(selector, 'el => el.value')
            return {'success': True, 'value': value}

        elif action == 'setValue':
            selector = args.get('selector', '')
            value = args.get('value', '')
            await page.fill(selector, value)
            return {'success': True}

        elif action == 'hover':
            selector = args.get('selector', '')
            await page.hover(selector)
            return {'success': True}

        elif action == 'refresh':
            await page.reload()
            return {'success': True}

        elif action == 'highlight':
            selector = args.get('selector', '')
            await page.eval_on_selector(
                selector,
                "el => { el.style.outline = '3px solid red'; setTimeout(() => el.style.outline = '', 2000); }"
            )
            return {'success': True}

        elif action == 'evalChain':
            steps = args.get('steps', [])
            results = []
            prev = None
            for i, step in enumerate(steps):
                script = step.get('script', '')
                label = step.get('label', f'step_{i}')
                capture = step.get('capture_console', True)
                stop_on_error = step.get('stop_on_error', True)

                console_msgs = []
                if capture:
                    page.on('console', lambda m: console_msgs.append({'type': m.type, 'text': m.text}))

                try:
                    # Inject $prev into execution context
                    wrapped = f"(function($prev) {{ return ({script}); }})({json.dumps(prev)})"
                    result = await page.evaluate(wrapped)
                    prev = result
                    results.append({'label': label, 'result': result, 'console': console_msgs, 'error': None})
                except Exception as e:
                    results.append({'label': label, 'result': None, 'console': console_msgs, 'error': str(e)})
                    if stop_on_error:
                        break
                finally:
                    if capture:
                        page.remove_listener('console', lambda m: None)

            return {'success': True, 'steps': results, 'final': prev}

        elif action == 'waitAndAct':
            condition = args.get('condition', 'true')
            action_script = args.get('action_script', '')
            poll_ms = args.get('poll_interval_ms', 200)
            timeout_ms = args.get('timeout_ms', 15000)
            elapsed = 0
            while elapsed < timeout_ms:
                try:
                    ready = await page.evaluate(condition)
                    if ready:
                        result = await page.evaluate(action_script)
                        return {'success': True, 'result': result, 'elapsed_ms': elapsed}
                except Exception:
                    pass
                await asyncio.sleep(poll_ms / 1000)
                elapsed += poll_ms
            return {'success': False, 'error': f'Condition not met within {timeout_ms}ms'}

        elif action == 'injectObserver':
            selector = args.get('selector', 'body')
            observe_attrs = args.get('observe_attributes', True)
            observe_children = args.get('observe_child_list', True)
            observe_subtree = args.get('observe_subtree', True)
            script = f"""
                (function() {{
                    if (window.__ccb_observer) window.__ccb_observer.disconnect();
                    window.__ccb_mutations = window.__ccb_mutations || [];
                    const target = document.querySelector({json.dumps(selector)}) || document.body;
                    window.__ccb_observer = new MutationObserver(mutations => {{
                        mutations.forEach(m => window.__ccb_mutations.push({{
                            type: m.type,
                            target: m.target.tagName + (m.target.id ? '#' + m.target.id : ''),
                            addedNodes: m.addedNodes.length,
                            removedNodes: m.removedNodes.length,
                            attributeName: m.attributeName,
                            ts: Date.now()
                        }}));
                    }});
                    window.__ccb_observer.observe(target, {{
                        attributes: {'true' if observe_attrs else 'false'},
                        childList: {'true' if observe_children else 'false'},
                        subtree: {'true' if observe_subtree else 'false'}
                    }});
                    return 'observer installed on ' + target.tagName;
                }})()
            """
            result = await page.evaluate(script)
            return {'success': True, 'message': result}

        else:
            return {'success': False, 'error': f'Unsupported headless action: {action}'}


# Module-level singleton
_headless_browser: Optional[HeadlessBrowser] = None


def get_headless_browser() -> Optional[HeadlessBrowser]:
    return _headless_browser


async def init_headless_browser() -> HeadlessBrowser:
    global _headless_browser
    _headless_browser = HeadlessBrowser()
    await _headless_browser.start()
    return _headless_browser
