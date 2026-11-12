// Issue #4: tab tools returned far more than an agent can take in one result.
const test = require('node:test');
const assert = require('node:assert/strict');
const { loadBackgroundScript } = require('./helpers/background-script');

const FAVICON = 'data:image/x-icon;base64,' + 'A'.repeat(2000);
const TABS = [
  { id: 1, windowId: 1, url: 'https://www.youtube.com/', title: 'YouTube', active: true, favIconUrl: FAVICON },
  { id: 2, windowId: 1, url: 'https://makerworld.com/de', title: 'MakerWorld', active: false, favIconUrl: FAVICON },
  { id: 3, windowId: 2, url: 'https://makerworld.com/de/my', title: 'Mine', active: true, favIconUrl: FAVICON },
];

function fakeBrowser() {
  return {
    tabs: {
      query: async (q) => (q.currentWindow ? TABS.filter((t) => t.windowId === 1) : TABS),
      get: async (id) => TABS.find((t) => t.id === id),
      sendMessage: async () => ({ url: TABS[0].url, title: TABS[0].title, interactiveElements: [] }),
    },
    windows: {
      getAll: async () => [{ id: 1, focused: true }, { id: 2, focused: false }],
      get: async (id) => ({ id, focused: id === 1, state: 'normal', type: 'normal' }),
    },
  };
}

const plain = (value) => JSON.parse(JSON.stringify(value));

// The server converts tool arguments to camelCase before sending them (camelize_args).
test('get_tabs honours urlPattern, currentWindowOnly and includeFavicon', async () => {
  const bg = loadBackgroundScript(fakeBrowser());

  const filtered = plain(await bg.getAllTabs({ urlPattern: 'makerworld', currentWindowOnly: false }));
  assert.deepEqual(filtered.tabs.map((t) => t.id), [2, 3]);
  assert.equal(filtered.scope, 'all_windows');
  assert.equal(filtered.tabs[0].favIconUrl, undefined);

  const withIcons = plain(await bg.getAllTabs({ includeFavicon: true }));
  assert.equal(withIcons.tabs[0].favIconUrl, FAVICON);
});

test('get_tab_info leaves the favicon out unless asked', async () => {
  const bg = loadBackgroundScript(fakeBrowser());

  const info = plain(await bg.getTabInfo(1, {}));
  assert.equal(info.success, true, info.error);
  assert.equal(info.tab.favIconUrl, undefined);
  assert.equal(info.pageInfo.title, 'YouTube');

  const withIcon = plain(await bg.getTabInfo(1, { includeFavicon: true }));
  assert.equal(withIcon.tab.favIconUrl, FAVICON);
});
