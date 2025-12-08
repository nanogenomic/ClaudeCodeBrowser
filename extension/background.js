/**
 * ClaudeCodeBrowser - Background Script
 * Handles native messaging, tab management, and coordination with content scripts
 *
 * MIT License
 * Copyright (c) 2025 Andre Watson (nanogenomic), Ligandal Inc.
 * Author: dre@ligandal.com
 */

const NATIVE_HOST_NAME = "claudecodebrowser";
let nativePort = null;
let isConnected = false;
let pendingRequests = new Map();
let requestCounter = 0;

// Connect to native messaging host
function connectNativeHost() {
  try {
    nativePort = browser.runtime.connectNative(NATIVE_HOST_NAME);
    isConnected = true;
    console.log("[ClaudeCodeBrowser] Connected to native host");

    nativePort.onMessage.addListener(handleNativeMessage);
    nativePort.onDisconnect.addListener(handleDisconnect);
  } catch (error) {
    console.error("[ClaudeCodeBrowser] Failed to connect to native host:", error);
    isConnected = false;
  }
}

function handleDisconnect(port) {
  console.log("[ClaudeCodeBrowser] Disconnected from native host");
  if (port.error) {
    console.error("[ClaudeCodeBrowser] Disconnect error:", port.error);
  }
  isConnected = false;
  nativePort = null;

  // Reject all pending requests
  for (const [id, { reject }] of pendingRequests) {
    reject(new Error("Native host disconnected"));
  }
  pendingRequests.clear();

  // Try to reconnect after delay
  setTimeout(connectNativeHost, 5000);
}

function handleNativeMessage(message) {
  console.log("[ClaudeCodeBrowser] Received from native host:", message);

  if (message.requestId && pendingRequests.has(message.requestId)) {
    const { resolve, reject } = pendingRequests.get(message.requestId);
    pendingRequests.delete(message.requestId);

    if (message.error) {
      reject(new Error(message.error));
    } else {
      resolve(message);
    }
  } else if (message.action) {
    // Handle incoming commands from native host
    handleCommand(message);
  }
}

function sendToNativeHost(message) {
  return new Promise((resolve, reject) => {
    if (!isConnected || !nativePort) {
      connectNativeHost();
      if (!isConnected) {
        reject(new Error("Not connected to native host"));
        return;
      }
    }

    const requestId = ++requestCounter;
    message.requestId = requestId;
    pendingRequests.set(requestId, { resolve, reject });

    // Timeout after 30 seconds
    setTimeout(() => {
      if (pendingRequests.has(requestId)) {
        pendingRequests.delete(requestId);
        reject(new Error("Request timeout"));
      }
    }, 30000);

    nativePort.postMessage(message);
  });
}

// Handle commands from native host
async function handleCommand(message) {
  const { action, tabId, data } = message;
  let result = { success: false };

  try {
    switch (action) {
      case "screenshot":
        result = await takeScreenshot(tabId, data);
        break;
      case "click":
        result = await performClick(tabId, data);
        break;
      case "type":
        result = await performType(tabId, data);
        break;
      case "scroll":
        result = await performScroll(tabId, data);
        break;
      case "navigate":
        result = await navigateTo(tabId, data);
        break;
      case "getPageInfo":
        result = await getPageInfo(tabId);
        break;
      case "getElements":
        result = await getElements(tabId, data);
        break;
      case "executeScript":
        result = await executeScript(tabId, data);
        break;
      case "highlight":
        result = await highlightElement(tabId, data);
        break;
      case "waitForElement":
        result = await waitForElement(tabId, data);
        break;
      case "getTabs":
        result = await getAllTabs();
        break;
      case "createTab":
        result = await createNewTab(data);
        break;
      case "closeTab":
        result = await closeTab(tabId);
        break;
      case "focusTab":
        result = await focusTab(tabId);
        break;
      case "refresh":
      case "reload":
        result = await refreshTab(tabId, data);
        break;
      case "hardRefresh":
        result = await hardRefreshTab(tabId);
        break;
      case "reloadAll":
        result = await reloadAllTabs(data);
        break;
      case "reloadByUrl":
        result = await reloadTabsByUrl(data);
        break;
      default:
        result = { success: false, error: `Unknown action: ${action}` };
    }
  } catch (error) {
    result = { success: false, error: error.message };
  }

  // Send result back to native host
  if (nativePort && message.requestId) {
    nativePort.postMessage({
      requestId: message.requestId,
      ...result
    });
  }

  return result;
}

// Screenshot functionality
async function takeScreenshot(tabId, options = {}) {
  try {
    const tab = tabId ? await browser.tabs.get(tabId) : (await browser.tabs.query({ active: true, currentWindow: true }))[0];

    const dataUrl = await browser.tabs.captureVisibleTab(tab.windowId, {
      format: options.format || "png",
      quality: options.quality || 90
    });

    // If full page screenshot requested, use content script
    if (options.fullPage) {
      const fullPageData = await browser.tabs.sendMessage(tab.id, {
        action: "captureFullPage",
        format: options.format || "png"
      });
      return { success: true, data: fullPageData, type: "fullPage" };
    }

    return {
      success: true,
      data: dataUrl,
      type: "visible",
      tab: { id: tab.id, url: tab.url, title: tab.title }
    };
  } catch (error) {
    return { success: false, error: error.message };
  }
}

// Click functionality
async function performClick(tabId, data) {
  try {
    const tab = tabId ? await browser.tabs.get(tabId) : (await browser.tabs.query({ active: true, currentWindow: true }))[0];

    const result = await browser.tabs.sendMessage(tab.id, {
      action: "click",
      ...data
    });

    return { success: true, ...result };
  } catch (error) {
    return { success: false, error: error.message };
  }
}

// Type functionality
async function performType(tabId, data) {
  try {
    const tab = tabId ? await browser.tabs.get(tabId) : (await browser.tabs.query({ active: true, currentWindow: true }))[0];

    const result = await browser.tabs.sendMessage(tab.id, {
      action: "type",
      ...data
    });

    return { success: true, ...result };
  } catch (error) {
    return { success: false, error: error.message };
  }
}

// Scroll functionality
async function performScroll(tabId, data) {
  try {
    const tab = tabId ? await browser.tabs.get(tabId) : (await browser.tabs.query({ active: true, currentWindow: true }))[0];

    const result = await browser.tabs.sendMessage(tab.id, {
      action: "scroll",
      ...data
    });

    return { success: true, ...result };
  } catch (error) {
    return { success: false, error: error.message };
  }
}

// Navigation
async function navigateTo(tabId, data) {
  try {
    const tab = tabId ? await browser.tabs.get(tabId) : (await browser.tabs.query({ active: true, currentWindow: true }))[0];

    await browser.tabs.update(tab.id, { url: data.url });

    // Wait for page to load
    return new Promise((resolve) => {
      const listener = (updatedTabId, changeInfo) => {
        if (updatedTabId === tab.id && changeInfo.status === "complete") {
          browser.tabs.onUpdated.removeListener(listener);
          resolve({ success: true, url: data.url });
        }
      };
      browser.tabs.onUpdated.addListener(listener);

      // Timeout after 30 seconds
      setTimeout(() => {
        browser.tabs.onUpdated.removeListener(listener);
        resolve({ success: true, url: data.url, note: "Navigation initiated but completion not confirmed" });
      }, 30000);
    });
  } catch (error) {
    return { success: false, error: error.message };
  }
}

// Get page information
async function getPageInfo(tabId) {
  try {
    const tab = tabId ? await browser.tabs.get(tabId) : (await browser.tabs.query({ active: true, currentWindow: true }))[0];

    const result = await browser.tabs.sendMessage(tab.id, {
      action: "getPageInfo"
    });

    return {
      success: true,
      tab: { id: tab.id, url: tab.url, title: tab.title },
      ...result
    };
  } catch (error) {
    return { success: false, error: error.message };
  }
}

// Get elements by selector
async function getElements(tabId, data) {
  try {
    const tab = tabId ? await browser.tabs.get(tabId) : (await browser.tabs.query({ active: true, currentWindow: true }))[0];

    const result = await browser.tabs.sendMessage(tab.id, {
      action: "getElements",
      ...data
    });

    return { success: true, ...result };
  } catch (error) {
    return { success: false, error: error.message };
  }
}

// Execute arbitrary script
async function executeScript(tabId, data) {
  try {
    const tab = tabId ? await browser.tabs.get(tabId) : (await browser.tabs.query({ active: true, currentWindow: true }))[0];

    const result = await browser.tabs.executeScript(tab.id, {
      code: data.script
    });

    return { success: true, result: result[0] };
  } catch (error) {
    return { success: false, error: error.message };
  }
}

// Highlight element
async function highlightElement(tabId, data) {
  try {
    const tab = tabId ? await browser.tabs.get(tabId) : (await browser.tabs.query({ active: true, currentWindow: true }))[0];

    const result = await browser.tabs.sendMessage(tab.id, {
      action: "highlight",
      ...data
    });

    return { success: true, ...result };
  } catch (error) {
    return { success: false, error: error.message };
  }
}

// Wait for element
async function waitForElement(tabId, data) {
  try {
    const tab = tabId ? await browser.tabs.get(tabId) : (await browser.tabs.query({ active: true, currentWindow: true }))[0];

    const result = await browser.tabs.sendMessage(tab.id, {
      action: "waitForElement",
      ...data
    });

    return { success: true, ...result };
  } catch (error) {
    return { success: false, error: error.message };
  }
}

// Tab management
async function getAllTabs() {
  try {
    const tabs = await browser.tabs.query({});
    return {
      success: true,
      tabs: tabs.map(t => ({
        id: t.id,
        url: t.url,
        title: t.title,
        active: t.active,
        windowId: t.windowId
      }))
    };
  } catch (error) {
    return { success: false, error: error.message };
  }
}

async function createNewTab(data) {
  try {
    const tab = await browser.tabs.create({
      url: data.url || "about:blank",
      active: data.active !== false
    });
    return {
      success: true,
      tab: { id: tab.id, url: tab.url, title: tab.title }
    };
  } catch (error) {
    return { success: false, error: error.message };
  }
}

async function closeTab(tabId) {
  try {
    await browser.tabs.remove(tabId);
    return { success: true };
  } catch (error) {
    return { success: false, error: error.message };
  }
}

async function focusTab(tabId) {
  try {
    const tab = await browser.tabs.update(tabId, { active: true });
    await browser.windows.update(tab.windowId, { focused: true });
    return { success: true };
  } catch (error) {
    return { success: false, error: error.message };
  }
}

// Refresh/Reload functionality
async function refreshTab(tabId, options = {}) {
  try {
    const tab = tabId ? await browser.tabs.get(tabId) : (await browser.tabs.query({ active: true, currentWindow: true }))[0];

    // bypassCache: true = hard refresh (Ctrl+Shift+R), false = normal refresh (F5)
    await browser.tabs.reload(tab.id, { bypassCache: options.bypassCache || false });

    // Wait for page to load if requested
    if (options.waitForLoad !== false) {
      return new Promise((resolve) => {
        const listener = (updatedTabId, changeInfo) => {
          if (updatedTabId === tab.id && changeInfo.status === "complete") {
            browser.tabs.onUpdated.removeListener(listener);
            resolve({
              success: true,
              refreshed: true,
              tab: { id: tab.id, url: tab.url, title: tab.title },
              bypassCache: options.bypassCache || false
            });
          }
        };
        browser.tabs.onUpdated.addListener(listener);

        // Timeout after 30 seconds
        setTimeout(() => {
          browser.tabs.onUpdated.removeListener(listener);
          resolve({ success: true, refreshed: true, note: "Refresh initiated but completion not confirmed" });
        }, 30000);
      });
    }

    return { success: true, refreshed: true, tab: { id: tab.id, url: tab.url } };
  } catch (error) {
    return { success: false, error: error.message };
  }
}

// Hard refresh - bypass cache (like Ctrl+Shift+R)
async function hardRefreshTab(tabId) {
  return refreshTab(tabId, { bypassCache: true });
}

// Reload all tabs (useful when restarting dev servers)
async function reloadAllTabs(options = {}) {
  try {
    const tabs = await browser.tabs.query({});
    const results = [];

    for (const tab of tabs) {
      // Skip special browser pages
      if (tab.url.startsWith('about:') || tab.url.startsWith('moz-extension:')) {
        continue;
      }

      // Filter by URL pattern if provided
      if (options.urlPattern) {
        const regex = new RegExp(options.urlPattern);
        if (!regex.test(tab.url)) {
          continue;
        }
      }

      await browser.tabs.reload(tab.id, { bypassCache: options.bypassCache || false });
      results.push({ id: tab.id, url: tab.url, reloaded: true });
    }

    return {
      success: true,
      reloadedCount: results.length,
      tabs: results,
      bypassCache: options.bypassCache || false
    };
  } catch (error) {
    return { success: false, error: error.message };
  }
}

// Reload tabs matching a specific URL or pattern (great for dev servers)
async function reloadTabsByUrl(options) {
  try {
    if (!options.url && !options.urlPattern) {
      return { success: false, error: "Must provide url or urlPattern" };
    }

    const tabs = await browser.tabs.query({});
    const results = [];

    for (const tab of tabs) {
      let matches = false;

      if (options.url) {
        // Exact URL match or starts with
        matches = tab.url === options.url || tab.url.startsWith(options.url);
      } else if (options.urlPattern) {
        // Regex pattern match
        const regex = new RegExp(options.urlPattern);
        matches = regex.test(tab.url);
      }

      if (matches) {
        await browser.tabs.reload(tab.id, { bypassCache: options.bypassCache !== false });
        results.push({ id: tab.id, url: tab.url, reloaded: true });
      }
    }

    return {
      success: true,
      reloadedCount: results.length,
      tabs: results,
      bypassCache: options.bypassCache !== false
    };
  } catch (error) {
    return { success: false, error: error.message };
  }
}

// Listen for messages from content scripts
browser.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.target === "background") {
    handleCommand({ ...message, tabId: sender.tab?.id })
      .then(sendResponse);
    return true; // Keep channel open for async response
  }
});

// Listen for external connections (from MCP server via HTTP)
browser.runtime.onMessageExternal.addListener((message, sender, sendResponse) => {
  handleCommand(message)
    .then(sendResponse);
  return true;
});

// Context menu for quick actions
browser.contextMenus.create({
  id: "claude-screenshot",
  title: "Take Screenshot for Claude",
  contexts: ["page"]
});

browser.contextMenus.create({
  id: "claude-inspect",
  title: "Inspect Element for Claude",
  contexts: ["all"]
});

browser.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === "claude-screenshot") {
    takeScreenshot(tab.id).then(result => {
      if (result.success && nativePort) {
        nativePort.postMessage({
          action: "screenshotTaken",
          data: result.data,
          tab: { id: tab.id, url: tab.url, title: tab.title }
        });
      }
    });
  } else if (info.menuItemId === "claude-inspect") {
    browser.tabs.sendMessage(tab.id, {
      action: "inspectElement",
      x: info.pageX,
      y: info.pageY
    });
  }
});

// Initialize
connectNativeHost();
console.log("[ClaudeCodeBrowser] Background script initialized");
