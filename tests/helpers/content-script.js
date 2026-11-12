// Loads the real extension/content.js into a jsdom page and returns a function
// that sends it a message exactly the way background.js does
// (browser.tabs.sendMessage → runtime.onMessage listener → sendResponse).
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');

const CONTENT_JS = fs.readFileSync(
  path.join(__dirname, '..', '..', 'extension', 'content.js'), 'utf8');

function loadContentScript(bodyHtml) {
  const dom = new JSDOM(`<!doctype html><html><body>${bodyHtml}</body></html>`, {
    runScripts: 'outside-only',
    pretendToBeVisual: true,
    url: 'http://127.0.0.1/',
  });
  const { window } = dom;
  window.Element.prototype.scrollIntoView = () => {}; // not implemented by jsdom

  let listener = null;
  window.browser = { runtime: { onMessage: { addListener: (fn) => { listener = fn; } } } };
  window.console.log = () => {}; // silence "Content script loaded"
  window.eval(CONTENT_JS);

  const send = (message) => new Promise((resolve) => listener(message, {}, resolve));
  return { window, send };
}

module.exports = { loadContentScript };
