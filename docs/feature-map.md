# Feature map: ClaudeCodeBrowser

> Starter map. Keep this file aligned with user-visible behavior and verification paths; update the affected rows in every PR.

## Project purpose

![License: MIT](https://opensource.org/licenses/MIT) ![Version](https://github.com/nanogenomic/ClaudeCodeBrowser/releases) ![Firefox Add-on](https://addons.mozilla.org/firefox/) ![MCP](https://modelcontextprotocol.io) ![Python](https://www.python.org) ![Platforms](#installation)

## Feature areas

| Area | Implementation | Verification |
| --- | --- | --- |
| `.claude/` | Top-level source area; map behavior-specific entry points here. | Add the relevant test or verification path when documenting a behavior.; `.github/workflows/` |
| `agent/` | Top-level source area; map behavior-specific entry points here. | Add the relevant test or verification path when documenting a behavior.; `.github/workflows/` |
| `extension/` | Top-level source area; map behavior-specific entry points here. | Add the relevant test or verification path when documenting a behavior.; `.github/workflows/` |
| `mcp-server/` | Top-level source area; map behavior-specific entry points here. | Add the relevant test or verification path when documenting a behavior.; `.github/workflows/` |
| `native-host/` | Top-level source area; map behavior-specific entry points here. | Add the relevant test or verification path when documenting a behavior.; `.github/workflows/` |

## Change notes

- For each behavior changed by a PR, update the relevant feature-area row and link its test or verification entry point.
- If a new user-visible behavior is added, add a row before merging.

<!-- pr-review-canvas-review-step -->
## PR Review Canvas

| Capability | Implementation | Verification |
| --- | --- | --- |
| PR review guidance | `.github/skills/pr-review-canvas/SKILL.md` | Review GitHub CI status and validate linked test output, test script, implementation, feature map, and frontend video when applicable. |
