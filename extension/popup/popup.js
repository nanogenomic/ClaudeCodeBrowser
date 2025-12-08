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
    try {
      const response = await fetch('http://localhost:8765/health');
      if (response.ok) {
        updateStatus(true);
        showToast('Connected to MCP server!', 'success');
      } else {
        updateStatus(false);
        showToast('Server not responding', 'error');
      }
    } catch (error) {
      updateStatus(false);
      showToast('Cannot reach MCP server', 'error');
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
    updateStatus(response.ok);
  } catch (error) {
    updateStatus(false);
  }
}

function updateStatus(connected) {
  const statusEl = document.getElementById('status');
  const statusText = statusEl.querySelector('.status-text');

  if (connected) {
    statusEl.classList.remove('disconnected');
    statusEl.classList.add('connected');
    statusText.textContent = 'Connected';
  } else {
    statusEl.classList.remove('connected');
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
