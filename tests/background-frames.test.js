// Issue #25: content.js runs in every frame (all_frames), and messages without a
// frameId reach all of them, so one click hit the page and its iframes.
const test = require('node:test');
const assert = require('node:assert/strict');
const { loadBackgroundScript } = require('./helpers/background-script');

const TAB = { id: 7, windowId: 1, url: 'http://127.0.0.1/frames.html', title: 'Frames' };

function recordingBrowser() {
  const sent = [];
  let menuListener = null;
  const api = {
    tabs: {
      query: async () => [TAB],
      get: async () => TAB,
      update: async () => TAB,
      captureVisibleTab: async () => 'data:image/png;base64,X',
      captureTab: async () => 'data:image/png;base64,X',
      sendMessage: async (tabId, message, options) => {
        sent.push({ action: message.action, options: options && { ...options } });
        return message.action === 'captureFullPage' ? { scrollWidth: 10, scrollHeight: 10 } : {};
      },
    },
    windows: { get: async () => ({ id: 1 }) },
    contextMenus: { create: () => {}, onClicked: { addListener: (fn) => { menuListener = fn; } } },
  };
  return { api, sent, clickMenu: (info) => menuListener(info, TAB) };
}

const COMMANDS = [
  ['click', { selector: '#go' }], ['type', { selector: '#q', text: 'x' }], ['scroll', { direction: 'down' }],
  ['getPageInfo', {}], ['getElements', { selector: 'a' }], ['highlight', { selector: 'a' }],
  ['waitForElement', { selector: 'a' }], ['pressKey', { key: 'Enter' }], ['getText', {}],
  ['getTabInfo', {}], ['screenshot', { fullPage: true }],
];

test('every command is sent to the top frame only', async () => {
  const { api, sent } = recordingBrowser();
  const bg = loadBackgroundScript(api);

  for (const [action, data] of COMMANDS) {
    await bg.handleCommand({ action, tabId: TAB.id, data });
  }

  assert.ok(sent.length >= COMMANDS.length, `only ${sent.length} messages sent`);
  const notTopOnly = sent.filter((m) => !m.options || m.options.frameId !== 0).map((m) => m.action);
  assert.deepEqual(notTopOnly, []);
});

test('"Inspect Element for Claude" goes to the frame that was right-clicked', async () => {
  const { api, sent, clickMenu } = recordingBrowser();
  loadBackgroundScript(api);

  clickMenu({ menuItemId: 'claude-inspect', frameId: 42, pageX: 5, pageY: 6 });

  assert.deepEqual(sent, [{ action: 'inspectElement', options: { frameId: 42 } }]);
});
