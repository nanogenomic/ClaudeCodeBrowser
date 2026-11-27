import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { pathToFileURL, URL } from "node:url";

const FIELD_NAMES = {
  testOutput: "Test output / evidence",
  testScript: "Test script permalink",
  implementation: "Implementation code permalink",
  featureMap: "Feature map permalink",
  frontendVideo: "Frontend test video",
};

const FRONTEND_EXTENSION = /\.(?:astro|css|html?|jsx|less|sass|scss|svelte|tsx|vue)$/i;
const FRONTEND_SEGMENT = /(^|\/)(?:app|client|components|front[-_]end|frontend|pages|public|screens|ui|views|web)(\/|$)/i;
const FRONTEND_VIDEO_URL =
  /^https:\/\/(?:(?:www\.)?(?:loom\.com|youtu\.be|youtube\.com|vimeo\.com)\/|github\.com\/user-attachments\/assets\/|github\.com\/[^/]+\/[^/]+\/assets\/|private-user-images\.githubusercontent\.com\/|[\w.-]+\/[^\s?#]+\.(?:gif|mov|mp4|webm)(?:[?#].*)?$)/i;

export function extractField(body, label) {
  const escaped = label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const line = body
    .split(/\r?\n/)
    .find((candidate) => new RegExp(`^\\s*(?:[-*]\\s*)?${escaped}\\s*:`, "i").test(candidate));
  if (!line) return "";
  return line.replace(new RegExp(`^\\s*(?:[-*]\\s*)?${escaped}\\s*:\\s*`, "i"), "").trim();
}

export function extractHttpsUrl(value) {
  const match = value.match(/https:\/\/[^\s<>)\]]+/i);
  return match?.[0].replace(/[.,;]+$/, "") ?? "";
}

export function parseLinePermalink(value, { repository, headSha, serverUrl }) {
  const rawUrl = extractHttpsUrl(value);
  if (!rawUrl) return { error: "must contain an HTTPS GitHub line permalink" };

  let url;
  try {
    url = new URL(rawUrl);
  } catch {
    return { error: "is not a valid URL" };
  }

  const expectedHost = new URL(serverUrl).host;
  if (url.protocol !== "https:" || url.host !== expectedHost) {
    return { error: `must use HTTPS on ${expectedHost}` };
  }

  const match = url.pathname.match(/^\/([^/]+)\/([^/]+)\/blob\/([0-9a-f]{40})\/(.+)$/i);
  if (!match) return { error: "must link to a file at a commit SHA" };

  const actualRepository = `${match[1]}/${match[2]}`.toLowerCase();
  if (actualRepository !== repository.toLowerCase()) {
    return { error: `must point to ${repository}` };
  }

  const sha = match[3].toLowerCase();
  if (sha !== headSha.toLowerCase()) {
    return { error: "must use the current PR head commit SHA" };
  }

  let filePath;
  try {
    filePath = decodeURIComponent(match[4]);
  } catch {
    return { error: "contains an invalid encoded file path" };
  }
  if (filePath.split("/").some((part) => part === "." || part === "..")) {
    return { error: "must not contain relative path segments" };
  }

  const anchor = url.hash.match(/^#L([1-9]\d*)(?:-L([1-9]\d*))?$/);
  if (!anchor) return { error: "must include a line anchor such as #L12 or #L12-L18" };

  const startLine = Number(anchor[1]);
  const endLine = Number(anchor[2] ?? anchor[1]);
  if (endLine < startLine) return { error: "has a line range that ends before it starts" };

  return { filePath, startLine, endLine, sha };
}

export function isFrontendPath(filePath) {
  return FRONTEND_EXTENSION.test(filePath) || FRONTEND_SEGMENT.test(filePath);
}

export function validateEvidence({ body, changedFiles, repository, headSha, serverUrl }) {
  const errors = [];
  const fields = Object.fromEntries(
    Object.entries(FIELD_NAMES).map(([key, label]) => [key, extractField(body, label)]),
  );
  const urls = Object.fromEntries(
    Object.entries(fields).map(([key, value]) => [key, extractHttpsUrl(value)]),
  );

  if (!urls.testOutput) errors.push(`${FIELD_NAMES.testOutput}: add an HTTPS link to the test output`);
  if (!urls.testScript) errors.push(`${FIELD_NAMES.testScript}: add a GitHub line permalink`);
  if (!urls.implementation) errors.push(`${FIELD_NAMES.implementation}: add a GitHub line permalink`);
  if (!urls.featureMap) errors.push(`${FIELD_NAMES.featureMap}: add a GitHub line permalink`);

  const parsed = {};
  for (const key of ["testScript", "implementation", "featureMap"]) {
    if (!urls[key]) continue;
    parsed[key] = parseLinePermalink(fields[key], { repository, headSha, serverUrl });
    if (parsed[key].error) errors.push(`${FIELD_NAMES[key]}: ${parsed[key].error}`);
  }

  if (parsed.testScript && !parsed.testScript.error && !/\.test\.[^/]+$/i.test(parsed.testScript.filePath)) {
    errors.push(`${FIELD_NAMES.testScript}: link to a test file whose name ends in .test.<extension>`);
  }

  const featureMapPath = "docs/feature-map.md";
  if (!changedFiles.some((filePath) => filePath.toLowerCase() === featureMapPath)) {
    errors.push(`The PR must update ${featureMapPath}`);
  }
  if (
    parsed.featureMap &&
    !parsed.featureMap.error &&
    parsed.featureMap.filePath.toLowerCase() !== featureMapPath
  ) {
    errors.push(`${FIELD_NAMES.featureMap}: link to ${featureMapPath}`);
  }

  if (changedFiles.some(isFrontendPath)) {
    if (!urls.frontendVideo) {
      errors.push(`${FIELD_NAMES.frontendVideo}: add a captured frontend test video link`);
    } else if (!FRONTEND_VIDEO_URL.test(urls.frontendVideo)) {
      errors.push(`${FIELD_NAMES.frontendVideo}: link to a video or GitHub user-attachment URL`);
    }
  }

  return { errors, parsed };
}

function readHeadFile(headSha, filePath) {
  return execFileSync("git", ["show", `${headSha}:${filePath}`], { encoding: "utf8" });
}

function main() {
  const eventText = readFileSync(process.env.GITHUB_EVENT_PATH, "utf8").replace(/^\uFEFF/, "");
  const event = JSON.parse(eventText);
  const pullRequest = event.pull_request;
  if (!pullRequest) throw new Error("This check must run for a pull_request event.");

  const repository = process.env.GITHUB_REPOSITORY;
  const serverUrl = process.env.GITHUB_SERVER_URL || "https://github.com";
  const headSha = pullRequest.head.sha;
  const changedFiles = execFileSync(
    "git",
    ["diff", "--name-only", `${pullRequest.base.sha}...${headSha}`],
    { encoding: "utf8" },
  )
    .split(/\r?\n/)
    .filter(Boolean);

  const { errors, parsed } = validateEvidence({
    body: pullRequest.body || "",
    changedFiles,
    repository,
    headSha,
    serverUrl,
  });

  for (const key of ["testScript", "implementation", "featureMap"]) {
    const permalink = parsed[key];
    if (!permalink || permalink.error) continue;
    try {
      const content = readHeadFile(headSha, permalink.filePath);
      const lineCount = content.split(/\r?\n/).length;
      if (permalink.endLine > lineCount) {
        errors.push(
          `${FIELD_NAMES[key]}: line ${permalink.endLine} is past the end of ${permalink.filePath}`,
        );
      }
    } catch {
      errors.push(`${FIELD_NAMES[key]}: ${permalink.filePath} does not exist at the PR head`);
    }
  }

  if (errors.length > 0) {
    console.error("PR evidence check failed:");
    for (const error of errors) console.error(`- ${error}`);
    process.exitCode = 1;
    return;
  }

  console.log("PR evidence links are valid, the feature map changed, and frontend video requirements passed.");
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main();
}
