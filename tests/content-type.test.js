// Issue #8: typing was lost on React/MUI inputs while the Firefox window had no
// OS focus, and long texts kept typing after the tool had already timed out.
const test = require('node:test');
const assert = require('node:assert/strict');
const { loadContentScript } = require('./helpers/content-script');

test('typing into an unfocused window still sends focus events first', async () => {
  const { window, send } = loadContentScript('<input id="tags">');
  const input = window.document.getElementById('tags');
  // A background window: focus() moves focus but browsers fire no focus events.
  window.document.hasFocus = () => false;
  input.focus = () => {};
  const seen = [];
  for (const type of ['focus', 'focusin', 'input']) input.addEventListener(type, () => seen.push(type));

  const result = await send({ action: 'type', selector: '#tags', text: 'ab', delay: 0 });

  assert.equal(result.error, undefined);
  assert.deepEqual(seen.slice(0, 2).sort(), ['focus', 'focusin']);
  assert.ok(seen.indexOf('input') > 1, 'focus events must come before typing');
  assert.equal(input.value, 'ab');
});

test('a focused window gets no extra synthetic focus events', async () => {
  const { window, send } = loadContentScript('<input id="q">');
  window.document.hasFocus = () => true;
  const input = window.document.getElementById('q');
  let focusins = 0;
  input.addEventListener('focusin', () => focusins++);

  await send({ action: 'type', selector: '#q', text: 'x', delay: 0 });

  assert.equal(focusins, 1); // only the browser's own, from element.focus()
});

test('long texts are typed faster so typing ends well before the tool times out', async () => {
  const { window, send } = loadContentScript('<textarea id="desc"></textarea>');
  let waited = 0;
  window.setTimeout = (fn, ms = 0) => { waited += ms; fn(); return 0; }; // count instead of sleeping

  const text = 'x'.repeat(1000); // 1000 x 50 ms = 50 s at the default speed
  await send({ action: 'type', selector: '#desc', text });

  assert.equal(window.document.getElementById('desc').value, text);
  assert.ok(waited <= 11000, `typing took ${waited} ms`);
});

test('short texts keep the requested speed', async () => {
  const { window, send } = loadContentScript('<input id="q">');
  let waited = 0;
  window.setTimeout = (fn, ms = 0) => { waited += ms; fn(); return 0; };

  await send({ action: 'type', selector: '#q', text: 'hello', delay: 50 });

  assert.ok(waited >= 250, `only waited ${waited} ms`);
});

test('in a background tab typing does not pause between characters', async () => {
  // Firefox clamps timers in background tabs to >= 1 s, so any per-character
  // pause typed one character per second there (live: 30 characters in 30 s).
  const { window, send } = loadContentScript('<input id="q">');
  Object.defineProperty(window.document, 'hidden', { value: true });
  const pauses = [];
  window.setTimeout = (fn, ms = 0) => { pauses.push(ms); fn(); return 0; };

  await send({ action: 'type', selector: '#q', text: 'x'.repeat(200) });

  assert.equal(window.document.getElementById('q').value, 'x'.repeat(200));
  assert.ok(pauses.length < 5, `${pauses.length} timer waits for 200 characters`);
});
