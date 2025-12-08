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
      case "getBoundingRect":
        return getBoundingRect(message);
      default:
        throw new Error(`Unknown action: ${message.action}`);
    }
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
      element.dispatchEvent(click);

      // Also try native click for form elements
      if (element.click) {
        element.click();
      }
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
