// Loads the real extension/background.js into a Node vm context.
// `browserApi` overrides parts of the WebExtension API (e.g. { tabs: {...} });
// every other browser.* call is absorbed by a no-op stub, so the script's
// start-up code (native-host connection, listeners, menus) runs harmlessly.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const BACKGROUND_JS = fs.readFileSync(
  path.join(__dirname, '..', '..', 'extension', 'background.js'), 'utf8');

function noop() {
  return new Proxy(function () {}, {
    get: (_, key) => (key === 'then' ? undefined : noop()),
    apply: () => noop(),
  });
}

// Overridden namespaces keep the no-op fallback for members a test doesn't set.
function withFallback(target) {
  return new Proxy(target, { get: (obj, key) => (key in obj ? obj[key] : noop()) });
}

function loadBackgroundScript(browserApi = {}, globals = {}) {
  const browser = new Proxy(browserApi, {
    get: (overrides, key) => (key in overrides ? withFallback(overrides[key]) : noop()),
  });
  const quiet = { log() {}, warn() {}, error() {}, info() {}, debug() {} };
  const context = vm.createContext({
    browser, console: quiet, setTimeout, clearTimeout, setInterval, clearInterval,
    ...globals, // e.g. a fake fetch
  });
  vm.runInContext(BACKGROUND_JS, context);
  return context; // top-level functions (takeScreenshot, ...) are globals here
}

module.exports = { loadBackgroundScript };
