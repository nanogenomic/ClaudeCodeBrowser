// Issue #12: browser_click {text} matched only an element's own first text node.
const test = require('node:test');
const assert = require('node:assert/strict');
const { loadContentScript } = require('./helpers/content-script');

async function clickText(html, text) {
  const { window, send } = loadContentScript(html);
  const clicked = [];
  window.document.addEventListener('click', (e) => clicked.push(e.target.id || e.target.tagName));
  const result = await send({ action: 'click', text });
  return { result, clicked: [...new Set(clicked)] }; // which element, not how often (#17)
}

test('label split across elements', async () => {
  const { result, clicked } = await clickText('<button id="tab">3D-Modelle <span>(1)</span></button>', '3D-Modelle (1)');
  assert.equal(result.error, undefined);
  assert.deepEqual(clicked, ['tab']);
});

test('whitespace and line breaks are normalized', async () => {
  const { clicked } = await clickText('<a id="next" href="#">Nächster\n      Schritt</a>', 'Nächster Schritt');
  assert.deepEqual(clicked, ['next']);
});

test('text containing double quotes', async () => {
  const { result, clicked } = await clickText('<button id="q">Say "hi"</button>', 'Say "hi"');
  assert.equal(result.error, undefined);
  assert.deepEqual(clicked, ['q']);
});

test('exact match wins over an earlier partial match', async () => {
  const { clicked } = await clickText('<button id="draft">Save draft</button><button id="save">Save</button>', 'Save');
  assert.deepEqual(clicked, ['save']);
});

test('script contents are not matched', async () => {
  const { clicked } = await clickText('<script>var label = "Login";</script><a id="login" href="#">Login</a>', 'Login');
  assert.deepEqual(clicked, ['login']);
});

test('the deepest element containing the text is clicked', async () => {
  const { clicked } = await clickText('<div id="card"><p>Intro</p><a id="more" href="#">Read more</a></div>', 'Read more');
  assert.deepEqual(clicked, ['more']);
});

test('missing text still reports not found', async () => {
  const { result } = await clickText('<button>Other</button>', 'Absent');
  assert.match(result.error, /Element not found/);
});
