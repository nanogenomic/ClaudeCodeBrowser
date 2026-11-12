const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(
  process.env.CONTENT_SCRIPT || path.join(__dirname, '../extension/content.js'), 'utf8'
);

// Load the inspection functions without starting the extension's browser hooks.
function loadFunction(name, nextName, context) {
  const start = source.indexOf(`  function ${name}(`);
  const end = source.indexOf(`  function ${nextName}(`, start);
  assert.ok(start >= 0 && end > start, `Cannot locate ${name}`);
  vm.runInContext(source.slice(start, end), context);
}

function element(value, tagName = 'INPUT') {
  return {
    value, tagName, classList: [], textContent: '',
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 10, height: 10 }),
    getAttribute: () => null
  };
}

for (const [name, limit] of [['getElementInfo', 200], ['getPageInfo', 100]]) {
  function inspect(target) {
    const context = vm.createContext({
      isVisible: () => true,
      generateSelector: () => '#target',
      window: { location: { href: 'https://example.test/' } },
      document: {
        title: 'Test', documentElement: {}, forms: [],
        querySelectorAll: selector => selector.startsWith('h1') ? [] : [target]
      }
    });
    loadFunction(name, name === 'getElementInfo' ? 'generateSelector' : 'getElements', context);
    return name === 'getElementInfo'
      ? context.getElementInfo(target)
      : context.getPageInfo().interactiveElements[0];
  }

  test(`${name}: list item values remain numeric, including zero`, () => {
    for (const value of [0, 7, -1]) {
      assert.equal(inspect(element(value, 'LI')).value, value);
    }
  });

  test(`${name}: missing and null values return null`, () => {
    assert.equal(inspect(element(undefined, 'svg')).value, null);
    assert.equal(inspect(element(null)).value, null);
  });

  test(`${name}: string values retain truncation and empty-value behavior`, () => {
    assert.equal(inspect(element('hello')).value, 'hello');
    assert.equal(inspect(element('a'.repeat(250))).value, 'a'.repeat(limit));
    assert.equal(inspect(element('')).value, null);
  });
}
