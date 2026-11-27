import assert from "node:assert/strict";
import test from "node:test";
import {
  extractField,
  extractHttpsUrl,
  isFrontendPath,
  parseLinePermalink,
  validateEvidence,
} from "./check-pr-evidence.mjs";

const repository = "Sati-Co-Ltd/example";
const headSha = "a".repeat(40);
const serverUrl = "https://github.com";

test("extracts a labeled field and HTTPS link from a PR body", () => {
  assert.equal(extractField("- Test output / evidence: https://example.com/run", "Test output / evidence"), "https://example.com/run");
  assert.equal(extractHttpsUrl("[output](https://example.com/run)"), "https://example.com/run");
});

test("accepts line permalinks pinned to the current repository and PR head", () => {
  const result = parseLinePermalink(
    `https://github.com/${repository}/blob/${headSha}/src/example.test.mjs#L2-L4`,
    { repository, headSha, serverUrl },
  );
  assert.deepEqual(result, {
    filePath: "src/example.test.mjs",
    startLine: 2,
    endLine: 4,
    sha: headSha,
  });
});

test("rejects branch links and stale commit permalinks", () => {
  assert.match(
    parseLinePermalink(`https://github.com/${repository}/blob/main/src/a.test.mjs#L2`, {
      repository,
      headSha,
      serverUrl,
    }).error,
    /commit SHA/,
  );
  assert.match(
    parseLinePermalink(`https://github.com/${repository}/blob/${"b".repeat(40)}/src/a.test.mjs#L2`, {
      repository,
      headSha,
      serverUrl,
    }).error,
    /current PR head/,
  );
});

test("detects frontend files and frontend source directories", () => {
  assert.equal(isFrontendPath("src/components/Card.ts"), true);
  assert.equal(isFrontendPath("app/dashboard/page.tsx"), true);
  assert.equal(isFrontendPath("src/app/home.component.ts"), true);
  assert.equal(isFrontendPath("src/controllers/users.controller.ts"), false);
});

test("accepts common hosted recordings for frontend test evidence", () => {
  const result = validateEvidence({
    body: [
      "- Frontend test video: https://www.loom.com/share/example",
      "- Test output / evidence: https://example.com/output",
      `- Test script permalink: https://github.com/${repository}/blob/${headSha}/src/example.test.mjs#L1`,
      `- Implementation code permalink: https://github.com/${repository}/blob/${headSha}/src/example.mjs#L1`,
      `- Feature map permalink: https://github.com/${repository}/blob/${headSha}/docs/feature-map.md#L1`,
    ].join("\n"),
    changedFiles: ["src/components/Card.tsx", "docs/feature-map.md"],
    repository,
    headSha,
    serverUrl,
  });
  assert.ok(!result.errors.some((error) => error.includes("Frontend test video")));
});

test("validates line permalinks against a fork PR head repository", () => {
  const headRepository = "pahntanapat/token-saver-skill";
  const result = validateEvidence({
    body: [
      "- Test output / evidence: https://example.com/output",
      `- Test script permalink: https://github.com/${headRepository}/blob/${headSha}/src/example.test.mjs#L1`,
      `- Implementation code permalink: https://github.com/${headRepository}/blob/${headSha}/src/example.mjs#L1`,
      `- Feature map permalink: https://github.com/${headRepository}/blob/${headSha}/docs/feature-map.md#L1`,
    ].join("\n"),
    changedFiles: ["docs/feature-map.md"],
    repository,
    headRepository,
    headSha,
    serverUrl,
  });
  assert.deepEqual(result.errors, []);
});

test("requires a changed feature map and a video for frontend changes", () => {
  const result = validateEvidence({
    body: "",
    changedFiles: ["src/components/Card.tsx"],
    repository,
    headSha,
    serverUrl,
  });
  assert.ok(result.errors.some((error) => error.includes("docs/feature-map.md")));
  assert.ok(result.errors.some((error) => error.includes("Frontend test video")));
});
