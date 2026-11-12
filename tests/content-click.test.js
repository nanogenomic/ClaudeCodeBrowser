// Issue #17: browser_click dispatched a synthetic `click` AND called element.click(),
// so handlers ran twice and toggles (checkbox, <details>) flipped back.
const test = require('node:test');
const assert = require('node:assert/strict');
const { loadContentScript } = require('./helpers/content-script');

test('one browser_click runs the click handler once', async () => {
  const { window, send } = loadContentScript('<button id="b">Go</button>');
  let clicks = 0;
  window.document.getElementById('b').addEventListener('click', () => clicks++);

  await send({ action: 'click', selector: '#b' });

  assert.equal(clicks, 1);
});

test('clicking a checkbox checks it', async () => {
  const { window, send } = loadContentScript('<input type="checkbox" id="c">');

  await send({ action: 'click', selector: '#c' });

  assert.equal(window.document.getElementById('c').checked, true);
});

test('clicking a <summary> opens its <details>', async () => {
  const { window, send } = loadContentScript('<details id="d"><summary id="s">More</summary>Body</details>');

  await send({ action: 'click', selector: '#s' });

  assert.equal(window.document.getElementById('d').open, true);
});

test('right and double click still send exactly one event each', async () => {
  const { window, send } = loadContentScript('<button id="b">Go</button>');
  const seen = [];
  for (const type of ['click', 'contextmenu', 'dblclick']) {
    window.document.getElementById('b').addEventListener(type, () => seen.push(type));
  }

  await send({ action: 'click', selector: '#b', rightClick: true });
  await send({ action: 'click', selector: '#b', doubleClick: true });

  assert.deepEqual(seen, ['contextmenu', 'dblclick']);
});
