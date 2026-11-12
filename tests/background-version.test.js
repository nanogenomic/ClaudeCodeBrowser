// Issue #2: every reply to the native host carries the add-on's version, so the
// server can tell an outdated add-on from a broken tool.
const test = require('node:test');
const assert = require('node:assert/strict');
const { loadBackgroundScript } = require('./helpers/background-script');

function fakeNativePort() {
  const posted = [];
  const listeners = {};
  const port = {
    postMessage: (msg) => posted.push(JSON.parse(JSON.stringify(msg))),
    onMessage: { addListener: (fn) => { listeners.message = fn; } },
    onDisconnect: { addListener: () => {} },
  };
  return { port, posted, deliver: (msg) => listeners.message(msg) };
}

test('replies to the native host include the extension version', async () => {
  const native = fakeNativePort();
  const bg = loadBackgroundScript({
    runtime: {
      connectNative: () => native.port,
      getManifest: () => ({ version: '9.8.7' }),
      onMessage: { addListener: () => {} },
      onInstalled: { addListener: () => {} },
      onStartup: { addListener: () => {} },
    },
  });
  bg.connectNativeHost();

  native.deliver({ action: 'noSuchAction', requestId: 'r1' });
  await new Promise((resolve) => setImmediate(resolve));

  const reply = native.posted.find((m) => m.requestId === 'r1');
  assert.ok(reply, 'no reply posted');
  assert.equal(reply.extensionVersion, '9.8.7');
  assert.equal(reply.error, 'Unknown action: noSuchAction');
});
