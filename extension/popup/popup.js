/**
 * ClaudeCodeBrowser - Popup Script
 */

document.addEventListener('DOMContentLoaded', async () => {
  // Get current tab info
  const tabs = await browser.tabs.query({ active: true, currentWindow: true });
  const currentTab = tabs[0];

  if (currentTab) {
    document.querySelector('.tab-title').textContent = currentTab.title || 'Untitled';
    document.querySelector('.tab-url').textContent = currentTab.url || '-';
  }

  // Screenshot button
  document.getElementById('btn-screenshot').addEventListener('click', async () => {
    try {
      const result = await browser.runtime.sendMessage({
        target: 'background',
        action: 'screenshot'
      });

      if (result.success) {
        showToast('Screenshot captured!', 'success');

        // Download the screenshot
        const link = document.createElement('a');
        link.href = result.data;
        link.download = `screenshot-${Date.now()}.png`;
        link.click();
      } else {
        showToast(result.error || 'Screenshot failed', 'error');
      }
    } catch (error) {
      showToast(error.message, 'error');
    }
  });

  // Inspect button
  document.getElementById('btn-inspect').addEventListener('click', async () => {
    try {
      await browser.tabs.sendMessage(currentTab.id, {
        action: 'toggleInspector'
      });
      showToast('Inspector mode activated', 'success');
      window.close();
    } catch (error) {
      showToast(error.message, 'error');
    }
  });

  // Page info button
  document.getElementById('btn-pageinfo').addEventListener('click', async () => {
    try {
      const result = await browser.tabs.sendMessage(currentTab.id, {
        action: 'getPageInfo'
      });

      console.log('Page Info:', result);
      showToast(`Found ${result.interactiveElements?.length || 0} interactive elements`, 'success');

      // Copy to clipboard
      await navigator.clipboard.writeText(JSON.stringify(result, null, 2));
      showToast('Page info copied to clipboard!', 'success');
    } catch (error) {
      showToast(error.message, 'error');
    }
  });

  // Test connection button
  document.getElementById('btn-test-connection').addEventListener('click', async () => {
    showToast('Checking MCP server...', 'info');

    try {
      const response = await fetch('http://localhost:8765/health');
      if (response.ok) {
        const data = await response.json();
        updateStatus(true);
        showToast(`Connected! Server v${data.version}`, 'success');
      } else {
        throw new Error('Server not responding');
      }
    } catch (error) {
      // Server not running - trigger native host to start it
      showToast('Starting MCP server via native host...', 'info');
      updateStatus(false, 'Starting...');

      try {
        // Send a message through background script to native host
        // This will trigger the native host's ensure_mcp_server() function
        const result = await browser.runtime.sendMessage({
          target: 'background',
          action: 'status'
        });

        // Wait a moment for server to start, then recheck
        await new Promise(resolve => setTimeout(resolve, 2000));

        const retryResponse = await fetch('http://localhost:8765/health');
        if (retryResponse.ok) {
          const data = await retryResponse.json();
          updateStatus(true);
          showToast(`Server started! v${data.version}`, 'success');
        } else {
          updateStatus(false);
          showToast('Server started but not responding yet', 'warning');
        }
      } catch (nativeError) {
        updateStatus(false);
        showToast('Failed to start server. Check native host.', 'error');
        console.error('Native host error:', nativeError);
      }
    }
  });

  // Check initial connection status
  checkConnection();
});

async function checkConnection() {
  try {
    const response = await fetch('http://localhost:8765/health', {
      method: 'GET',
      mode: 'cors'
    });
    if (response.ok) {
      updateStatus(true);
    } else {
      throw new Error('Not OK');
    }
  } catch (error) {
    updateStatus(false);
    // Try to auto-start via native host on initial load
    tryAutoStart();
  }
}

async function tryAutoStart() {
  try {
    updateStatus(false, 'Starting...');

    // Trigger native host which will auto-start server
    await browser.runtime.sendMessage({
      target: 'background',
      action: 'status'
    });

    // Wait for server to start
    await new Promise(resolve => setTimeout(resolve, 2500));

    // Recheck
    const response = await fetch('http://localhost:8765/health');
    if (response.ok) {
      updateStatus(true);
    } else {
      updateStatus(false);
    }
  } catch (error) {
    updateStatus(false);
    console.log('Auto-start failed:', error);
  }
}

function updateStatus(connected, customText = null) {
  const statusEl = document.getElementById('status');
  const statusText = statusEl.querySelector('.status-text');

  statusEl.classList.remove('connected', 'disconnected', 'starting');

  if (customText) {
    statusEl.classList.add('starting');
    statusText.textContent = customText;
  } else if (connected) {
    statusEl.classList.add('connected');
    statusText.textContent = 'Connected';
  } else {
    statusEl.classList.add('disconnected');
    statusText.textContent = 'Disconnected';
  }
}

function showToast(message, type = 'info') {
  const existing = document.querySelector('.toast');
  if (existing) existing.remove();

  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  document.body.appendChild(toast);

  setTimeout(() => toast.remove(), 3000);
}
