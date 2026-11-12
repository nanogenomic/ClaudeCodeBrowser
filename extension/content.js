/**
 * ClaudeCodeBrowser - Content Script
 * Runs in web pages to handle DOM interactions, clicks, typing, and element inspection
 *
 * MIT License
 * Copyright (c) 2025 Andre Watson (nanogenomic), Ligandal Inc.
 * Author: dre@ligandal.com
 */

(function() {
  'use strict';

  // Prevent multiple injections
  if (window.__claudeCodeBrowserInjected) return;
  window.__claudeCodeBrowserInjected = true;

  let highlightOverlay = null;
  let inspectorMode = false;

  // ============================================
  // Console and Network Logging Infrastructure
  // ============================================

  // Logging state
  let loggingEnabled = false;
  let consoleLogs = [];
  let networkLogs = [];
  const MAX_LOG_ENTRIES = 500;

  // Original console methods (saved for restoration)
  const originalConsole = {
    log: console.log.bind(console),
    warn: console.warn.bind(console),
    error: console.error.bind(console),
    info: console.info.bind(console),
    debug: console.debug.bind(console)
  };

  // Console interceptor
  function interceptConsole() {
    ['log', 'warn', 'error', 'info', 'debug'].forEach(method => {
      console[method] = function(...args) {
        if (loggingEnabled) {
          const entry = {
            level: method,
            timestamp: new Date().toISOString(),
            message: args.map(arg => {
              try {
                if (typeof arg === 'object') {
                  return JSON.stringify(arg, null, 2);
                }
                return String(arg);
              } catch (e) {
                return String(arg);
              }
            }).join(' '),
            url: window.location.href
          };
          consoleLogs.push(entry);
          if (consoleLogs.length > MAX_LOG_ENTRIES) {
            consoleLogs.shift();
          }
        }
        originalConsole[method].apply(console, args);
      };
    });
  }

  // Restore original console
  function restoreConsole() {
    Object.keys(originalConsole).forEach(method => {
      console[method] = originalConsole[method];
    });
  }

  // Interception availability: Firefox's content-script sandbox makes some
  // page globals (notably window.fetch) read-only. A refused override must
  // cost only that one capability, never abort this whole script — an
  // aborted init means the message listener below never registers and every
  // DOM tool fails with "Receiving end does not exist".
  const interception = { fetch: false, xhr: false, console: false };

  // Network request interceptor (fetch)
  const originalFetch = window.fetch;
  const fetchInterceptor = async function(...args) {
    const startTime = Date.now();
    const [resource, init] = args;
    const url = typeof resource === 'string' ? resource : resource.url;
    const method = init?.method || 'GET';

    const logEntry = {
      type: 'fetch',
      method: method,
      url: url,
      requestHeaders: init?.headers || {},
      requestBody: init?.body ? String(init.body).substring(0, 1000) : null,
      startTime: new Date().toISOString(),
      pageUrl: window.location.href
    };

    try {
      const response = await originalFetch.apply(this, args);
      const endTime = Date.now();

      if (loggingEnabled) {
        logEntry.status = response.status;
        logEntry.statusText = response.statusText;
        logEntry.duration = endTime - startTime;
        logEntry.responseHeaders = Object.fromEntries(response.headers.entries());

        // Clone response to read body without consuming it
        const clone = response.clone();
        try {
          const contentType = response.headers.get('content-type') || '';
          if (contentType.includes('application/json')) {
            const body = await clone.json();
            logEntry.responseBody = JSON.stringify(body, null, 2).substring(0, 5000);
          } else if (contentType.includes('text/')) {
            logEntry.responseBody = (await clone.text()).substring(0, 5000);
          } else {
            logEntry.responseBody = '[Binary data]';
          }
        } catch (e) {
          logEntry.responseBody = '[Could not read response]';
        }

        networkLogs.push(logEntry);
        if (networkLogs.length > MAX_LOG_ENTRIES) {
          networkLogs.shift();
        }
      }

      return response;
    } catch (error) {
      if (loggingEnabled) {
        logEntry.error = error.message;
        logEntry.duration = Date.now() - startTime;
        networkLogs.push(logEntry);
        if (networkLogs.length > MAX_LOG_ENTRIES) {
          networkLogs.shift();
        }
      }
      throw error;
    }
  };

  try {
    window.fetch = fetchInterceptor;
    interception.fetch = true;
  } catch (e) {
    // "fetch" is read-only in Firefox's sandbox — network logging for fetch
    // is unavailable, everything else keeps working
  }

  // XHR interceptor
  const originalXHROpen = XMLHttpRequest.prototype.open;
  const originalXHRSend = XMLHttpRequest.prototype.send;

  const xhrOpenInterceptor = function(method, url, ...rest) {
    this._logData = {
      type: 'xhr',
      method: method,
      url: url,
      pageUrl: window.location.href
    };
    return originalXHROpen.apply(this, [method, url, ...rest]);
  };

  const xhrSendInterceptor = function(body) {
    if (loggingEnabled && this._logData) {
      const startTime = Date.now();
      this._logData.startTime = new Date().toISOString();
      this._logData.requestBody = body ? String(body).substring(0, 1000) : null;

      this.addEventListener('load', () => {
        this._logData.status = this.status;
        this._logData.statusText = this.statusText;
        this._logData.duration = Date.now() - startTime;
        this._logData.responseBody = this.responseText?.substring(0, 5000);
        networkLogs.push({ ...this._logData });
        if (networkLogs.length > MAX_LOG_ENTRIES) {
          networkLogs.shift();
        }
      });

      this.addEventListener('error', () => {
        this._logData.error = 'Network error';
        this._logData.duration = Date.now() - startTime;
        networkLogs.push({ ...this._logData });
        if (networkLogs.length > MAX_LOG_ENTRIES) {
          networkLogs.shift();
        }
      });
    }
    return originalXHRSend.apply(this, [body]);
  };

  try {
    XMLHttpRequest.prototype.open = xhrOpenInterceptor;
    XMLHttpRequest.prototype.send = xhrSendInterceptor;
    interception.xhr = true;
  } catch (e) {
    // XHR prototype not writable in this sandbox — skip XHR logging
  }

  // Initialize console interception (always intercepts, but only logs when enabled)
  try {
    interceptConsole();
    interception.console = true;
  } catch (e) {
    // console not writable in this sandbox — skip console logging
  }

  // Logging control functions
  function startLogging(options = {}) {
    loggingEnabled = true;
    if (options.clearExisting) {
      consoleLogs = [];
      networkLogs = [];
    }
    return {
      success: true,
      message: 'Logging started',
      consoleLogsCount: consoleLogs.length,
      networkLogsCount: networkLogs.length
    };
  }

  function stopLogging() {
    loggingEnabled = false;
    return {
      success: true,
      message: 'Logging stopped',
      consoleLogsCount: consoleLogs.length,
      networkLogsCount: networkLogs.length
    };
  }

  function getConsoleLogs(options = {}) {
    let logs = [...consoleLogs];

    // Filter by level if specified
    if (options.level) {
      logs = logs.filter(log => log.level === options.level);
    }

    // Filter by search term
    if (options.search) {
      const searchLower = options.search.toLowerCase();
      logs = logs.filter(log => log.message.toLowerCase().includes(searchLower));
    }

    // Limit results
    const limit = options.limit || 100;
    if (logs.length > limit) {
      logs = logs.slice(-limit);
    }

    return {
      success: true,
      logs: logs,
      totalCount: consoleLogs.length,
      returnedCount: logs.length,
      loggingEnabled: loggingEnabled,
      interceptionAvailable: interception.console
    };
  }

  function getNetworkLogs(options = {}) {
    let logs = [...networkLogs];

    // Filter by URL pattern
    if (options.urlPattern) {
      const pattern = new RegExp(options.urlPattern, 'i');
      logs = logs.filter(log => pattern.test(log.url));
    }

    // Filter by method
    if (options.method) {
      logs = logs.filter(log => log.method.toUpperCase() === options.method.toUpperCase());
    }

    // Filter by status
    if (options.status) {
      logs = logs.filter(log => log.status === options.status);
    }

    // Filter errors only
    if (options.errorsOnly) {
      logs = logs.filter(log => log.error || (log.status && log.status >= 400));
    }

    // Limit results
    const limit = options.limit || 100;
    if (logs.length > limit) {
      logs = logs.slice(-limit);
    }

    return {
      success: true,
      logs: logs,
      totalCount: networkLogs.length,
      returnedCount: logs.length,
      loggingEnabled: loggingEnabled,
      interceptionAvailable: interception.fetch || interception.xhr,
      interception: { fetch: interception.fetch, xhr: interception.xhr }
    };
  }

  function clearLogs(options = {}) {
    if (options.console !== false) {
      consoleLogs = [];
    }
    if (options.network !== false) {
      networkLogs = [];
    }
    return {
      success: true,
      message: 'Logs cleared'
    };
  }

  // Message listener
  browser.runtime.onMessage.addListener((message, sender, sendResponse) => {
    handleMessage(message)
      .then(sendResponse)
      .catch(error => sendResponse({ success: false, error: error.message }));
    return true; // Keep channel open for async
  });

  async function handleMessage(message) {
    switch (message.action) {
      case "click":
        return performClick(message);
      case "type":
        return performType(message);
      case "scroll":
        return performScroll(message);
      case "getPageInfo":
        return getPageInfo();
      case "getElements":
        return getElements(message);
      case "highlight":
        return highlightElement(message);
      case "waitForElement":
        return waitForElement(message);
      case "waitForChange":
        return waitForChange(message);
      case "waitForNetworkIdle":
        return waitForNetworkIdle(message);
      case "observeElement":
        return observeElement(message);
      case "stopObserving":
        return stopObserving(message);
      case "scrollAndCapture":
        return scrollAndCapture(message);
      case "clickAndWait":
        return clickAndWait(message);
      case "captureFullPage":
        return captureFullPage(message);
      case "inspectElement":
        return inspectElement(message);
      case "getValue":
        return getValue(message);
      case "setValue":
        return setValue(message);
      case "getAttribute":
        return getAttribute(message);
      case "focus":
        return focusElement(message);
      case "hover":
        return hoverElement(message);
      case "selectOption":
        return selectOption(message);
      case "getComputedStyles":
        return getComputedStyles(message);
      case "pressKey":
        return pressKey(message);
      case "getText":
        return getText(message);
      case "requestApproval":
        return requestApproval(message);
      case "solveCaptcha":
        return solveCaptcha(message);
      case "getBoundingRect":
        return getBoundingRect(message);
      // Console and network logging actions
      case "startLogging":
        return startLogging(message);
      case "stopLogging":
        return stopLogging();
      case "getConsoleLogs":
        return getConsoleLogs(message);
      case "getNetworkLogs":
        return getNetworkLogs(message);
      case "clearLogs":
        return clearLogs(message);
      default:
        throw new Error(`Unknown action: ${message.action}`);
    }
  }

  // Credential guard: typing into password fields is refused unless the
  // safety config explicitly allows it. Credentials belong in the browser's
  // own password manager (autofill), so they never pass through the AI.
  function assertNotPasswordField(element, options) {
    const isPassword = element.tagName === 'INPUT' &&
      (element.type === 'password' ||
       element.getAttribute('autocomplete') === 'current-password' ||
       element.getAttribute('autocomplete') === 'new-password');
    if (isPassword && options.allowPassword !== true) {
      throw new Error(
        'Refused: target is a password field. Use the browser’s own ' +
        'password manager (autofill) for credentials, or set ' +
        '"allow_password_typing": true in ~/.claudecodebrowser/safety.json ' +
        'if you really want automated password entry.'
      );
    }
  }

  // Human approval banner: Approve/Deny prompt rendered on the page,
  // resolved by a real click from the person at the browser
  function requestApproval(options) {
    return new Promise((resolve) => {
      const existing = document.getElementById('__ccb_approval_banner');
      if (existing) existing.remove();

      const banner = document.createElement('div');
      banner.id = '__ccb_approval_banner';
      banner.style.cssText = [
        'position:fixed', 'top:0', 'left:0', 'right:0', 'z-index:2147483647',
        'background:#1a1a2e', 'color:#fff', 'padding:14px 20px',
        'font:14px/1.5 system-ui,sans-serif', 'display:flex',
        'align-items:center', 'gap:16px', 'box-shadow:0 2px 12px rgba(0,0,0,.4)',
        'border-bottom:3px solid #e94560'
      ].join(';');

      const textWrap = document.createElement('div');
      textWrap.style.cssText = 'flex:1;min-width:0';
      const title = document.createElement('div');
      title.style.cssText = 'font-weight:600';
      title.textContent = '⚠️ Claude requests approval: ' + (options.message || 'Perform an action');
      textWrap.appendChild(title);
      if (options.detail) {
        const detail = document.createElement('div');
        detail.style.cssText = 'font-size:12px;opacity:.75;overflow:hidden;text-overflow:ellipsis;white-space:nowrap';
        detail.textContent = options.detail;
        textWrap.appendChild(detail);
      }

      function makeButton(label, bg) {
        const b = document.createElement('button');
        b.textContent = label;
        b.style.cssText = 'padding:8px 18px;border:none;border-radius:6px;cursor:pointer;' +
          'font:600 13px system-ui,sans-serif;color:#fff;background:' + bg;
        return b;
      }
      const approveBtn = makeButton('Approve', '#16a34a');
      const denyBtn = makeButton('Deny', '#dc2626');

      banner.appendChild(textWrap);
      banner.appendChild(approveBtn);
      banner.appendChild(denyBtn);
      (document.body || document.documentElement).appendChild(banner);

      const timeoutMs = options.timeout || 60000;
      let settled = false;
      function finish(approved, timedOut) {
        if (settled) return;
        settled = true;
        banner.remove();
        resolve({
          success: true,
          approved: approved,
          timedOut: !!timedOut,
          decidedAt: new Date().toISOString()
        });
      }

      approveBtn.addEventListener('click', () => finish(true, false));
      denyBtn.addEventListener('click', () => finish(false, false));
      setTimeout(() => finish(false, true), timeoutMs);
    });
  }

  // Captcha detection. Returns the widgets found and, where the challenge
  // exposes a response token, whether it has already been solved.
  function detectCaptcha() {
    const widgets = [];

    function hasResponseToken(name) {
      const el = document.querySelector(`textarea[name="${name}"], input[name="${name}"]`);
      return !!(el && el.value && el.value.length > 0);
    }

    // Google reCAPTCHA (v2 checkbox / invisible / v3)
    if (document.querySelector('.g-recaptcha, iframe[src*="recaptcha"], #g-recaptcha-response')) {
      widgets.push({
        type: 'recaptcha',
        solved: hasResponseToken('g-recaptcha-response') ||
                !!document.querySelector('.recaptcha-checkbox-checked')
      });
    }
    // hCaptcha
    if (document.querySelector('.h-captcha, iframe[src*="hcaptcha"], textarea[name="h-captcha-response"]')) {
      widgets.push({ type: 'hcaptcha', solved: hasResponseToken('h-captcha-response') });
    }
    // Cloudflare Turnstile
    if (document.querySelector('.cf-turnstile, iframe[src*="challenges.cloudflare.com"], input[name="cf-turnstile-response"]')) {
      widgets.push({ type: 'turnstile', solved: hasResponseToken('cf-turnstile-response') });
    }
    // Generic image/text captcha (no reliable machine-readable completion)
    if (widgets.length === 0 &&
        document.querySelector('img[src*="captcha" i], input[name*="captcha" i], [id*="captcha" i], [class*="captcha" i]')) {
      widgets.push({ type: 'generic', solved: null });
    }

    return { present: widgets.length > 0, widgets };
  }

  // Detect a captcha and hand it to the human to solve, then continue.
  // NOTE: this does not auto-solve or use any solver service — the person at
  // the browser completes the challenge; we detect completion or a Done click.
  function solveCaptcha(options = {}) {
    const detection = detectCaptcha();
    if (options.detectOnly) {
      return { success: true, ...detection };
    }
    if (!detection.present) {
      return { success: true, present: false, message: 'No captcha detected on the page.' };
    }
    if (detection.widgets.every(w => w.solved === true)) {
      return { success: true, present: true, solved: true,
               message: 'Captcha already solved.', widgets: detection.widgets };
    }

    return new Promise((resolve) => {
      const existing = document.getElementById('__ccb_captcha_banner');
      if (existing) existing.remove();

      const types = detection.widgets.map(w => w.type).join(', ');
      const banner = document.createElement('div');
      banner.id = '__ccb_captcha_banner';
      banner.style.cssText = [
        'position:fixed', 'top:0', 'left:0', 'right:0', 'z-index:2147483647',
        'background:#0f3460', 'color:#fff', 'padding:14px 20px',
        'font:14px/1.5 system-ui,sans-serif', 'display:flex',
        'align-items:center', 'gap:16px', 'box-shadow:0 2px 12px rgba(0,0,0,.4)',
        'border-bottom:3px solid #ffd166'
      ].join(';');

      const textWrap = document.createElement('div');
      textWrap.style.cssText = 'flex:1;min-width:0';
      const title = document.createElement('div');
      title.style.cssText = 'font-weight:600';
      title.textContent = '🧩 Please solve the captcha (' + types + '), then it continues automatically.';
      const detail = document.createElement('div');
      detail.style.cssText = 'font-size:12px;opacity:.8';
      detail.textContent = 'Claude paused and is waiting for you. Click Done if it does not continue on its own.';
      textWrap.appendChild(title);
      textWrap.appendChild(detail);

      const doneBtn = document.createElement('button');
      doneBtn.textContent = 'Done';
      doneBtn.style.cssText = 'padding:8px 18px;border:none;border-radius:6px;cursor:pointer;' +
        'font:600 13px system-ui,sans-serif;color:#0f3460;background:#ffd166';
      const cancelBtn = document.createElement('button');
      cancelBtn.textContent = 'Cancel';
      cancelBtn.style.cssText = 'padding:8px 14px;border:1px solid #ffffff55;border-radius:6px;' +
        'cursor:pointer;font:600 13px system-ui,sans-serif;color:#fff;background:transparent';

      banner.appendChild(textWrap);
      banner.appendChild(doneBtn);
      banner.appendChild(cancelBtn);
      (document.body || document.documentElement).appendChild(banner);

      const timeoutMs = options.timeout || 180000;
      const start = Date.now();
      let settled = false;

      function finish(payload) {
        if (settled) return;
        settled = true;
        clearInterval(poll);
        banner.remove();
        resolve({ success: true, present: true, elapsedMs: Date.now() - start, ...payload });
      }

      // Auto-detect completion for token-based widgets
      const poll = setInterval(() => {
        const now = detectCaptcha();
        const tokened = now.widgets.filter(w => w.solved !== null);
        if (tokened.length && tokened.every(w => w.solved === true)) {
          finish({ solved: true, resolvedBy: 'token', widgets: now.widgets });
        } else if (Date.now() - start > timeoutMs) {
          finish({ solved: false, timedOut: true, widgets: now.widgets });
        }
      }, 1000);

      doneBtn.addEventListener('click', () =>
        finish({ solved: true, resolvedBy: 'human', widgets: detectCaptcha().widgets }));
      cancelBtn.addEventListener('click', () =>
        finish({ solved: false, cancelled: true }));
    });
  }

  // Find element by various selectors
  function findElement(options) {
    let element = null;

    if (options.selector) {
      element = document.querySelector(options.selector);
    } else if (options.xpath) {
      const result = document.evaluate(
        options.xpath,
        document,
        null,
        XPathResult.FIRST_ORDERED_NODE_TYPE,
        null
      );
      element = result.singleNodeValue;
    } else if (options.text) {
      // Find by text content
      const xpath = `//*[contains(text(), "${options.text}")]`;
      const result = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
      element = result.singleNodeValue;
    } else if (options.x !== undefined && options.y !== undefined) {
      element = document.elementFromPoint(options.x, options.y);
    } else if (options.id) {
      element = document.getElementById(options.id);
    } else if (options.name) {
      element = document.querySelector(`[name="${options.name}"]`);
    } else if (options.ariaLabel) {
      element = document.querySelector(`[aria-label="${options.ariaLabel}"]`);
    } else if (options.placeholder) {
      element = document.querySelector(`[placeholder="${options.placeholder}"]`);
    } else if (options.role) {
      element = document.querySelector(`[role="${options.role}"]`);
    }

    return element;
  }

  // Click functionality
  async function performClick(options) {
    const element = findElement(options);

    if (!element) {
      throw new Error(`Element not found with options: ${JSON.stringify(options)}`);
    }

    // Scroll element into view
    element.scrollIntoView({ behavior: 'smooth', block: 'center' });
    await sleep(100);

    // Get element position
    const rect = element.getBoundingClientRect();
    const x = rect.left + rect.width / 2;
    const y = rect.top + rect.height / 2;

    // Create and dispatch events
    if (options.rightClick) {
      const contextEvent = new MouseEvent('contextmenu', {
        bubbles: true,
        cancelable: true,
        view: window,
        clientX: x,
        clientY: y
      });
      element.dispatchEvent(contextEvent);
    } else if (options.doubleClick) {
      const dblClickEvent = new MouseEvent('dblclick', {
        bubbles: true,
        cancelable: true,
        view: window,
        clientX: x,
        clientY: y
      });
      element.dispatchEvent(dblClickEvent);
    } else {
      // Regular click
      const mouseDown = new MouseEvent('mousedown', {
        bubbles: true,
        cancelable: true,
        view: window,
        clientX: x,
        clientY: y
      });
      const mouseUp = new MouseEvent('mouseup', {
        bubbles: true,
        cancelable: true,
        view: window,
        clientX: x,
        clientY: y
      });
      const click = new MouseEvent('click', {
        bubbles: true,
        cancelable: true,
        view: window,
        clientX: x,
        clientY: y
      });

      element.dispatchEvent(mouseDown);
      await sleep(50);
      element.dispatchEvent(mouseUp);
      // A dispatched click also runs the default action (toggle a checkbox,
      // open <details>, follow a link), so no extra element.click() here:
      // that fired every click twice and flipped toggles straight back.
      element.dispatchEvent(click);
    }

    return {
      clicked: true,
      element: getElementInfo(element),
      position: { x, y }
    };
  }

  // Type functionality
  async function performType(options) {
    let element = findElement(options);

    if (!element && options.focusFirst === false) {
      // Type into currently focused element
      element = document.activeElement;
    }

    if (!element) {
      throw new Error(`Element not found with options: ${JSON.stringify(options)}`);
    }

    assertNotPasswordField(element, options);

    // Focus the element
    element.focus();
    element.scrollIntoView({ behavior: 'smooth', block: 'center' });
    await sleep(100);

    const text = options.text || '';

    if (options.clear) {
      // Clear existing content
      if (element.tagName === 'INPUT' || element.tagName === 'TEXTAREA') {
        element.value = '';
      } else if (element.isContentEditable) {
        element.textContent = '';
      }
      element.dispatchEvent(new Event('input', { bubbles: true }));
    }

    if (options.instant) {
      // Instant input (no typing simulation)
      if (element.tagName === 'INPUT' || element.tagName === 'TEXTAREA') {
        element.value = options.clear ? text : element.value + text;
      } else if (element.isContentEditable) {
        element.textContent = options.clear ? text : element.textContent + text;
      }
      element.dispatchEvent(new Event('input', { bubbles: true }));
      element.dispatchEvent(new Event('change', { bubbles: true }));
    } else {
      // Simulate typing character by character
      for (const char of text) {
        const keyDown = new KeyboardEvent('keydown', {
          key: char,
          code: `Key${char.toUpperCase()}`,
          bubbles: true
        });
        const keyPress = new KeyboardEvent('keypress', {
          key: char,
          code: `Key${char.toUpperCase()}`,
          bubbles: true
        });
        const keyUp = new KeyboardEvent('keyup', {
          key: char,
          code: `Key${char.toUpperCase()}`,
          bubbles: true
        });

        element.dispatchEvent(keyDown);
        element.dispatchEvent(keyPress);

        // Actually insert the character
        if (element.tagName === 'INPUT' || element.tagName === 'TEXTAREA') {
          element.value += char;
        } else if (element.isContentEditable) {
          document.execCommand('insertText', false, char);
        }

        element.dispatchEvent(new Event('input', { bubbles: true }));
        element.dispatchEvent(keyUp);

        await sleep(options.delay || 50);
      }
      element.dispatchEvent(new Event('change', { bubbles: true }));
    }

    // Handle Enter key if specified
    if (options.pressEnter) {
      const enterDown = new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true });
      const enterUp = new KeyboardEvent('keyup', { key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true });
      element.dispatchEvent(enterDown);
      element.dispatchEvent(enterUp);

      // Submit form if applicable
      const form = element.closest('form');
      if (form && options.submitForm !== false) {
        form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      }
    }

    return {
      typed: true,
      element: getElementInfo(element),
      text: text
    };
  }

  // Scroll functionality
  async function performScroll(options) {
    let target = window;
    let element = null;

    if (options.selector || options.xpath || options.id) {
      element = findElement(options);
      if (element) {
        target = element;
      }
    }

    if (options.toElement) {
      const targetElement = findElement({ selector: options.toElement });
      if (targetElement) {
        targetElement.scrollIntoView({
          behavior: options.smooth !== false ? 'smooth' : 'auto',
          block: options.block || 'center'
        });
        await sleep(500);
        return { scrolled: true, element: getElementInfo(targetElement) };
      }
    }

    if (options.direction) {
      const amount = options.amount || 300;
      let scrollX = 0, scrollY = 0;

      switch (options.direction) {
        case 'up': scrollY = -amount; break;
        case 'down': scrollY = amount; break;
        case 'left': scrollX = -amount; break;
        case 'right': scrollX = amount; break;
        case 'top':
          if (element) element.scrollTop = 0;
          else window.scrollTo({ top: 0, behavior: 'smooth' });
          return { scrolled: true, position: { x: 0, y: 0 } };
        case 'bottom':
          if (element) element.scrollTop = element.scrollHeight;
          else window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
          return { scrolled: true, position: 'bottom' };
      }

      if (element) {
        element.scrollBy({ left: scrollX, top: scrollY, behavior: 'smooth' });
      } else {
        window.scrollBy({ left: scrollX, top: scrollY, behavior: 'smooth' });
      }
    } else if (options.x !== undefined || options.y !== undefined) {
      const scrollOptions = {
        left: options.x || 0,
        top: options.y || 0,
        behavior: options.smooth !== false ? 'smooth' : 'auto'
      };

      if (element) {
        element.scrollTo(scrollOptions);
      } else {
        window.scrollTo(scrollOptions);
      }
    }

    await sleep(300);

    return {
      scrolled: true,
      position: {
        x: element ? element.scrollLeft : window.scrollX,
        y: element ? element.scrollTop : window.scrollY
      }
    };
  }

  // Get page information
  function getPageInfo() {
    const interactiveElements = [];

    // Find all interactive elements
    const selectors = [
      'a[href]', 'button', 'input', 'textarea', 'select',
      '[onclick]', '[role="button"]', '[role="link"]',
      '[tabindex]:not([tabindex="-1"])'
    ];

    document.querySelectorAll(selectors.join(', ')).forEach((el, index) => {
      if (index < 100) { // Limit to prevent huge responses
        const rect = el.getBoundingClientRect();
        if (rect.width > 0 && rect.height > 0) {
          interactiveElements.push({
            tag: el.tagName.toLowerCase(),
            type: el.type || null,
            id: el.id || null,
            name: el.name || null,
            text: el.textContent?.trim().substring(0, 100) || null,
            href: el.href || null,
            value: el.value?.substring(0, 100) || null,
            placeholder: el.placeholder || null,
            ariaLabel: el.getAttribute('aria-label'),
            position: {
              x: rect.left + rect.width / 2,
              y: rect.top + rect.height / 2,
              width: rect.width,
              height: rect.height
            },
            visible: isVisible(el),
            selector: generateSelector(el)
          });
        }
      }
    });

    return {
      url: window.location.href,
      title: document.title,
      documentHeight: document.documentElement.scrollHeight,
      documentWidth: document.documentElement.scrollWidth,
      viewportHeight: window.innerHeight,
      viewportWidth: window.innerWidth,
      scrollPosition: { x: window.scrollX, y: window.scrollY },
      interactiveElements: interactiveElements,
      forms: Array.from(document.forms).map(form => ({
        id: form.id,
        name: form.name,
        action: form.action,
        method: form.method,
        fields: Array.from(form.elements).slice(0, 20).map(el => ({
          tag: el.tagName.toLowerCase(),
          type: el.type,
          name: el.name,
          id: el.id,
          placeholder: el.placeholder,
          required: el.required,
          value: el.type === 'password' ? '***' : el.value?.substring(0, 50)
        }))
      })),
      headings: Array.from(document.querySelectorAll('h1, h2, h3')).slice(0, 20).map(h => ({
        level: parseInt(h.tagName[1]),
        text: h.textContent?.trim().substring(0, 100)
      }))
    };
  }

  // Get elements by selector
  function getElements(options) {
    const elements = [];
    const selector = options.selector || '*';
    const limit = options.limit || 50;

    document.querySelectorAll(selector).forEach((el, index) => {
      if (index < limit) {
        elements.push(getElementInfo(el));
      }
    });

    return { elements, count: document.querySelectorAll(selector).length };
  }

  // Highlight element
  function highlightElement(options) {
    removeHighlight();

    const element = findElement(options);
    if (!element) {
      throw new Error('Element not found');
    }

    const rect = element.getBoundingClientRect();

    highlightOverlay = document.createElement('div');
    highlightOverlay.className = 'claude-highlight-overlay';
    highlightOverlay.style.cssText = `
      position: fixed;
      left: ${rect.left}px;
      top: ${rect.top}px;
      width: ${rect.width}px;
      height: ${rect.height}px;
      border: 3px solid #7c3aed;
      background: rgba(124, 58, 237, 0.1);
      pointer-events: none;
      z-index: 999999;
      box-shadow: 0 0 10px rgba(124, 58, 237, 0.5);
      transition: all 0.3s ease;
    `;

    // Add label
    const label = document.createElement('div');
    label.style.cssText = `
      position: absolute;
      top: -25px;
      left: 0;
      background: #7c3aed;
      color: white;
      padding: 2px 8px;
      font-size: 12px;
      font-family: monospace;
      border-radius: 3px;
      white-space: nowrap;
    `;
    label.textContent = options.label || generateSelector(element);
    highlightOverlay.appendChild(label);

    document.body.appendChild(highlightOverlay);

    // Auto-remove after duration
    if (options.duration !== 0) {
      setTimeout(removeHighlight, options.duration || 3000);
    }

    return { highlighted: true, element: getElementInfo(element) };
  }

  function removeHighlight() {
    if (highlightOverlay) {
      highlightOverlay.remove();
      highlightOverlay = null;
    }
  }

  // Wait for element
  async function waitForElement(options) {
    const timeout = options.timeout || 10000;
    const interval = options.interval || 100;
    const startTime = Date.now();

    while (Date.now() - startTime < timeout) {
      const element = findElement(options);
      if (element) {
        if (!options.visible || isVisible(element)) {
          return { found: true, element: getElementInfo(element) };
        }
      }
      await sleep(interval);
    }

    throw new Error(`Element not found within ${timeout}ms`);
  }

  // Active mutation observers
  const activeObservers = new Map();

  // Wait for DOM changes (useful after clicking dynamic elements)
  async function waitForChange(options) {
    const timeout = options.timeout || 10000;
    const targetSelector = options.selector || 'body';
    const target = document.querySelector(targetSelector) || document.body;

    return new Promise((resolve, reject) => {
      let resolved = false;
      const changes = [];

      const observer = new MutationObserver((mutations) => {
        if (resolved) return;

        for (const mutation of mutations) {
          const change = {
            type: mutation.type,
            target: mutation.target.tagName?.toLowerCase(),
            addedNodes: mutation.addedNodes.length,
            removedNodes: mutation.removedNodes.length
          };

          // Filter by change type if specified
          if (options.changeType) {
            if (options.changeType === 'childList' && mutation.type !== 'childList') continue;
            if (options.changeType === 'attributes' && mutation.type !== 'attributes') continue;
            if (options.changeType === 'text' && mutation.type !== 'characterData') continue;
          }

          changes.push(change);

          // Check if we should resolve now
          if (options.waitForAll !== true) {
            resolved = true;
            observer.disconnect();
            resolve({
              changed: true,
              changes: changes,
              waitedMs: Date.now() - startTime
            });
            return;
          }
        }
      });

      const startTime = Date.now();

      observer.observe(target, {
        childList: true,
        subtree: options.subtree !== false,
        attributes: options.attributes !== false,
        characterData: options.characterData === true,
        attributeOldValue: options.attributeOldValue === true
      });

      // Timeout
      setTimeout(() => {
        if (!resolved) {
          resolved = true;
          observer.disconnect();
          if (changes.length > 0) {
            resolve({ changed: true, changes, waitedMs: timeout });
          } else {
            resolve({ changed: false, changes: [], waitedMs: timeout, timedOut: true });
          }
        }
      }, timeout);
    });
  }

  // Wait for network requests to settle (useful after AJAX calls)
  async function waitForNetworkIdle(options) {
    const timeout = options.timeout || 10000;
    const idleTime = options.idleTime || 500;
    const startTime = Date.now();

    let lastActivityTime = Date.now();
    let pendingRequests = 0;

    // Hook into fetch
    const originalFetch = window.fetch;
    window.fetch = async (...args) => {
      pendingRequests++;
      lastActivityTime = Date.now();
      try {
        const result = await originalFetch(...args);
        return result;
      } finally {
        pendingRequests--;
        lastActivityTime = Date.now();
      }
    };

    // Hook into XMLHttpRequest
    const originalOpen = XMLHttpRequest.prototype.open;
    const originalSend = XMLHttpRequest.prototype.send;

    XMLHttpRequest.prototype.open = function(...args) {
      this._ccb_tracked = true;
      return originalOpen.apply(this, args);
    };

    XMLHttpRequest.prototype.send = function(...args) {
      if (this._ccb_tracked) {
        pendingRequests++;
        lastActivityTime = Date.now();
        this.addEventListener('loadend', () => {
          pendingRequests--;
          lastActivityTime = Date.now();
        });
      }
      return originalSend.apply(this, args);
    };

    try {
      while (Date.now() - startTime < timeout) {
        const idleDuration = Date.now() - lastActivityTime;
        if (pendingRequests === 0 && idleDuration >= idleTime) {
          return {
            idle: true,
            waitedMs: Date.now() - startTime,
            pendingRequests: 0
          };
        }
        await sleep(100);
      }

      return {
        idle: false,
        timedOut: true,
        waitedMs: timeout,
        pendingRequests
      };
    } finally {
      // Restore original functions
      window.fetch = originalFetch;
      XMLHttpRequest.prototype.open = originalOpen;
      XMLHttpRequest.prototype.send = originalSend;
    }
  }

  // Set up continuous observation of an element for changes
  function observeElement(options) {
    const targetSelector = options.selector;
    const target = document.querySelector(targetSelector);

    if (!target) {
      throw new Error(`Element not found: ${targetSelector}`);
    }

    const observerId = options.observerId || `obs_${Date.now()}`;

    // Stop existing observer with same ID
    if (activeObservers.has(observerId)) {
      activeObservers.get(observerId).disconnect();
    }

    const changes = [];

    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        changes.push({
          type: mutation.type,
          timestamp: Date.now(),
          target: generateSelector(mutation.target),
          addedNodes: Array.from(mutation.addedNodes).map(n => n.tagName?.toLowerCase() || 'text').filter(Boolean),
          removedNodes: Array.from(mutation.removedNodes).map(n => n.tagName?.toLowerCase() || 'text').filter(Boolean),
          attributeName: mutation.attributeName,
          oldValue: mutation.oldValue
        });

        // Keep only last 100 changes
        if (changes.length > 100) changes.shift();
      }
    });

    observer.observe(target, {
      childList: true,
      subtree: true,
      attributes: true,
      characterData: true,
      attributeOldValue: true
    });

    activeObservers.set(observerId, { observer, changes, target: targetSelector });

    return {
      observing: true,
      observerId,
      target: targetSelector
    };
  }

  // Stop observing and get accumulated changes
  function stopObserving(options) {
    const observerId = options.observerId;

    if (!activeObservers.has(observerId)) {
      return { found: false, observerId };
    }

    const { observer, changes, target } = activeObservers.get(observerId);
    observer.disconnect();
    activeObservers.delete(observerId);

    return {
      stopped: true,
      observerId,
      target,
      changes,
      totalChanges: changes.length
    };
  }

  // Scroll through page and collect viewport snapshots info
  async function scrollAndCapture(options) {
    const scrollStep = options.scrollStep || window.innerHeight * 0.8;
    const delay = options.delay || 500;
    const maxScrolls = options.maxScrolls || 20;

    const snapshots = [];
    const originalScroll = window.scrollY;
    let scrollCount = 0;

    // Start from top
    window.scrollTo({ top: 0, behavior: 'instant' });
    await sleep(delay);

    while (scrollCount < maxScrolls) {
      const snapshot = {
        scrollY: window.scrollY,
        viewportHeight: window.innerHeight,
        documentHeight: document.documentElement.scrollHeight,
        visibleElements: getVisibleInteractiveElements(),
        timestamp: Date.now()
      };
      snapshots.push(snapshot);

      // Check if we've reached the bottom
      if (window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 10) {
        break;
      }

      // Scroll down
      window.scrollBy({ top: scrollStep, behavior: 'smooth' });
      await sleep(delay);
      scrollCount++;
    }

    // Restore original scroll position if requested
    if (options.restore !== false) {
      window.scrollTo({ top: originalScroll, behavior: 'instant' });
    }

    return {
      completed: true,
      snapshots,
      totalScrolls: scrollCount,
      documentHeight: document.documentElement.scrollHeight,
      message: 'Use browser_screenshot after each scroll position for images'
    };
  }

  // Get interactive elements currently visible in viewport
  function getVisibleInteractiveElements() {
    const elements = [];
    const selectors = [
      'a[href]', 'button', 'input', 'textarea', 'select',
      '[onclick]', '[role="button"]', '[role="link"]',
      '[tabindex]:not([tabindex="-1"])'
    ];

    document.querySelectorAll(selectors.join(', ')).forEach((el) => {
      const rect = el.getBoundingClientRect();

      // Check if element is in viewport
      if (rect.top < window.innerHeight && rect.bottom > 0 &&
          rect.left < window.innerWidth && rect.right > 0 &&
          rect.width > 0 && rect.height > 0 && isVisible(el)) {

        elements.push({
          tag: el.tagName.toLowerCase(),
          text: el.textContent?.trim().substring(0, 50) || null,
          selector: generateSelector(el),
          position: {
            x: Math.round(rect.left + rect.width / 2),
            y: Math.round(rect.top + rect.height / 2)
          }
        });
      }
    });

    return elements.slice(0, 50); // Limit to 50 elements
  }

  // Click an element and wait for dynamic changes
  async function clickAndWait(options) {
    const waitTimeout = options.waitTimeout || 5000;
    const waitForSelector = options.waitForSelector;
    const waitForChange = options.waitForChange !== false;

    // Set up mutation observer before clicking
    let changes = [];
    let observer = null;

    if (waitForChange) {
      observer = new MutationObserver((mutations) => {
        for (const mutation of mutations) {
          changes.push({
            type: mutation.type,
            target: mutation.target.tagName?.toLowerCase(),
            addedNodes: mutation.addedNodes.length,
            removedNodes: mutation.removedNodes.length
          });
        }
      });

      observer.observe(document.body, {
        childList: true,
        subtree: true,
        attributes: true
      });
    }

    // Perform the click
    const clickResult = await performClick(options);

    // Wait for changes or specific element
    const startTime = Date.now();

    if (waitForSelector) {
      // Wait for specific element to appear
      while (Date.now() - startTime < waitTimeout) {
        const el = document.querySelector(waitForSelector);
        if (el && isVisible(el)) {
          if (observer) observer.disconnect();
          return {
            ...clickResult,
            waited: true,
            waitedMs: Date.now() - startTime,
            foundElement: getElementInfo(el),
            changes: changes.slice(0, 20)
          };
        }
        await sleep(100);
      }
    } else if (waitForChange) {
      // Wait for any DOM changes to settle
      let lastChangeCount = 0;
      let stableTime = 0;

      while (Date.now() - startTime < waitTimeout) {
        if (changes.length > lastChangeCount) {
          lastChangeCount = changes.length;
          stableTime = 0;
        } else {
          stableTime += 100;
          if (stableTime >= 500) {
            // DOM has been stable for 500ms
            break;
          }
        }
        await sleep(100);
      }
    }

    if (observer) observer.disconnect();

    return {
      ...clickResult,
      waited: true,
      waitedMs: Date.now() - startTime,
      changes: changes.slice(0, 20),
      totalChanges: changes.length
    };
  }

  // Capture full page
  async function captureFullPage(options) {
    // This needs to be handled by background script
    // Content script can only prepare the page
    return {
      scrollHeight: document.documentElement.scrollHeight,
      scrollWidth: document.documentElement.scrollWidth,
      viewportHeight: window.innerHeight,
      viewportWidth: window.innerWidth
    };
  }

  // Inspect element at position
  function inspectElement(options) {
    const element = document.elementFromPoint(options.x, options.y);
    if (!element) {
      return { found: false };
    }

    highlightElement({ selector: generateSelector(element), duration: 5000 });

    return {
      found: true,
      element: getElementInfo(element),
      selector: generateSelector(element),
      xpath: generateXPath(element)
    };
  }

  // Get value
  function getValue(options) {
    const element = findElement(options);
    if (!element) throw new Error('Element not found');

    let value;
    if (element.tagName === 'INPUT' || element.tagName === 'TEXTAREA') {
      value = element.value;
    } else if (element.tagName === 'SELECT') {
      value = element.options[element.selectedIndex]?.value;
    } else {
      value = element.textContent;
    }

    return { value, element: getElementInfo(element) };
  }

  // Set value
  function setValue(options) {
    const element = findElement(options);
    if (!element) throw new Error('Element not found');

    assertNotPasswordField(element, options);

    if (element.tagName === 'INPUT' || element.tagName === 'TEXTAREA') {
      element.value = options.value;
    } else if (element.tagName === 'SELECT') {
      element.value = options.value;
    } else if (element.isContentEditable) {
      element.textContent = options.value;
    }

    element.dispatchEvent(new Event('input', { bubbles: true }));
    element.dispatchEvent(new Event('change', { bubbles: true }));

    return { set: true, element: getElementInfo(element) };
  }

  // Get attribute
  function getAttribute(options) {
    const element = findElement(options);
    if (!element) throw new Error('Element not found');

    const value = element.getAttribute(options.attribute);
    return { value, element: getElementInfo(element) };
  }

  // Focus element
  function focusElement(options) {
    const element = findElement(options);
    if (!element) throw new Error('Element not found');

    element.focus();
    element.scrollIntoView({ behavior: 'smooth', block: 'center' });

    return { focused: true, element: getElementInfo(element) };
  }

  // Hover element
  async function hoverElement(options) {
    const element = findElement(options);
    if (!element) throw new Error('Element not found');

    element.scrollIntoView({ behavior: 'smooth', block: 'center' });
    await sleep(100);

    const rect = element.getBoundingClientRect();
    const x = rect.left + rect.width / 2;
    const y = rect.top + rect.height / 2;

    const mouseEnter = new MouseEvent('mouseenter', { bubbles: true, clientX: x, clientY: y });
    const mouseOver = new MouseEvent('mouseover', { bubbles: true, clientX: x, clientY: y });

    element.dispatchEvent(mouseEnter);
    element.dispatchEvent(mouseOver);

    return { hovered: true, element: getElementInfo(element) };
  }

  // Press a keyboard key with optional modifiers
  async function pressKey(options) {
    let target = document.activeElement || document.body;
    if (options.selector) {
      const element = findElement(options);
      if (!element) throw new Error('Element not found');
      element.focus();
      target = element;
    }

    const eventInit = {
      key: options.key,
      bubbles: true,
      cancelable: true,
      ctrlKey: !!options.ctrl,
      shiftKey: !!options.shift,
      altKey: !!options.alt,
      metaKey: !!options.meta
    };

    target.dispatchEvent(new KeyboardEvent('keydown', eventInit));
    target.dispatchEvent(new KeyboardEvent('keypress', eventInit));
    target.dispatchEvent(new KeyboardEvent('keyup', eventInit));

    // Synthetic key events don't trigger default actions, so emulate the
    // common one: Enter inside a form submits it
    if (options.key === 'Enter' && !options.ctrl && !options.shift && target.form) {
      if (target.form.requestSubmit) {
        target.form.requestSubmit();
      } else {
        target.form.submit();
      }
    }

    return { pressed: options.key, element: getElementInfo(target) };
  }

  // Extract visible text from the page or an element
  function getText(options) {
    let element = document.body;
    if (options.selector) {
      element = findElement(options);
      if (!element) throw new Error('Element not found');
    }

    const maxLength = options.maxLength || 20000;
    const text = element.innerText || element.textContent || '';

    return {
      text: text.slice(0, maxLength),
      truncated: text.length > maxLength,
      totalLength: text.length,
      url: window.location.href,
      title: document.title
    };
  }

  // Select option
  function selectOption(options) {
    const element = findElement(options);
    if (!element || element.tagName !== 'SELECT') {
      throw new Error('Select element not found');
    }

    if (options.value !== undefined) {
      element.value = options.value;
    } else if (options.index !== undefined) {
      element.selectedIndex = options.index;
    } else if (options.text) {
      const option = Array.from(element.options).find(o => o.text === options.text);
      if (option) element.value = option.value;
    }

    element.dispatchEvent(new Event('change', { bubbles: true }));

    return {
      selected: true,
      value: element.value,
      text: element.options[element.selectedIndex]?.text
    };
  }

  // Get computed styles
  function getComputedStyles(options) {
    const element = findElement(options);
    if (!element) throw new Error('Element not found');

    const styles = window.getComputedStyle(element);
    const properties = options.properties || [
      'display', 'visibility', 'opacity', 'position',
      'width', 'height', 'color', 'backgroundColor',
      'fontSize', 'fontFamily', 'margin', 'padding'
    ];

    const result = {};
    properties.forEach(prop => {
      result[prop] = styles.getPropertyValue(prop);
    });

    return { styles: result, element: getElementInfo(element) };
  }

  // Get bounding rect
  function getBoundingRect(options) {
    const element = findElement(options);
    if (!element) throw new Error('Element not found');

    const rect = element.getBoundingClientRect();
    return {
      rect: {
        x: rect.x,
        y: rect.y,
        width: rect.width,
        height: rect.height,
        top: rect.top,
        right: rect.right,
        bottom: rect.bottom,
        left: rect.left
      },
      element: getElementInfo(element)
    };
  }

  // Helper functions
  function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  function isVisible(element) {
    const style = window.getComputedStyle(element);
    const rect = element.getBoundingClientRect();

    return (
      style.display !== 'none' &&
      style.visibility !== 'hidden' &&
      style.opacity !== '0' &&
      rect.width > 0 &&
      rect.height > 0
    );
  }

  function getElementInfo(element) {
    const rect = element.getBoundingClientRect();
    return {
      tag: element.tagName.toLowerCase(),
      id: element.id || null,
      classes: Array.from(element.classList),
      name: element.name || null,
      type: element.type || null,
      text: element.textContent?.trim().substring(0, 200) || null,
      value: element.value?.substring(0, 200) || null,
      href: element.href || null,
      src: element.src || null,
      placeholder: element.placeholder || null,
      ariaLabel: element.getAttribute('aria-label'),
      role: element.getAttribute('role'),
      disabled: element.disabled,
      checked: element.checked,
      visible: isVisible(element),
      position: {
        x: rect.left,
        y: rect.top,
        width: rect.width,
        height: rect.height,
        centerX: rect.left + rect.width / 2,
        centerY: rect.top + rect.height / 2
      },
      selector: generateSelector(element)
    };
  }

  function generateSelector(element) {
    if (element.id) return `#${element.id}`;

    const path = [];
    let current = element;

    while (current && current !== document.body) {
      let selector = current.tagName.toLowerCase();

      if (current.id) {
        selector = `#${current.id}`;
        path.unshift(selector);
        break;
      }

      if (current.className && typeof current.className === 'string') {
        const classes = current.className.trim().split(/\s+/).filter(c => c && !c.match(/^[0-9]/));
        if (classes.length > 0) {
          selector += '.' + classes.slice(0, 2).join('.');
        }
      }

      const siblings = current.parentElement?.children || [];
      const sameTagSiblings = Array.from(siblings).filter(s => s.tagName === current.tagName);
      if (sameTagSiblings.length > 1) {
        const index = sameTagSiblings.indexOf(current) + 1;
        selector += `:nth-of-type(${index})`;
      }

      path.unshift(selector);
      current = current.parentElement;
    }

    return path.join(' > ');
  }

  function generateXPath(element) {
    if (element.id) return `//*[@id="${element.id}"]`;

    const parts = [];
    let current = element;

    while (current && current.nodeType === Node.ELEMENT_NODE) {
      let index = 1;
      let sibling = current.previousSibling;

      while (sibling) {
        if (sibling.nodeType === Node.ELEMENT_NODE && sibling.tagName === current.tagName) {
          index++;
        }
        sibling = sibling.previousSibling;
      }

      const tagName = current.tagName.toLowerCase();
      parts.unshift(`${tagName}[${index}]`);
      current = current.parentNode;
    }

    return '/' + parts.join('/');
  }

  console.log('[ClaudeCodeBrowser] Content script loaded');
})();
