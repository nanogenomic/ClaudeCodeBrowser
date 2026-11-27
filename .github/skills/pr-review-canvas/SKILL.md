---
name: pr-review-canvas
description: >-
  Render a pull request diff as a reviewer-focused canvas or walkthrough,
  including GitHub CI status and verification of linked test evidence.
---

# PR Review Canvas

Build a PR review that presents the diff for reviewer comprehension, not in file-tree order. When a Canvas SDK is available, render the review as an interactive canvas. Otherwise, present the same sections as a concise Markdown walkthrough and do not claim a canvas was rendered.

## Prerequisites

When using Cursor Canvas, read `~/.cursor/skills-cursor/canvas/SKILL.md` first. It contains generation policy, design guidance, and file-path conventions. Read the Canvas SDK declarations to discover exact exports and prop shapes rather than guessing.

## Gather the diff

Expect a GitHub PR link (a full URL like `https://github.com/<owner>/<repo>/pull/<n>`, or an equivalent `gh`-resolvable reference). Use `gh pr diff <pr>` to collect every file's path, additions, deletions, and hunks.

If the user did not provide a PR link, stop and ask which diff they want reviewed. Do not guess at the current branch, infer from recent history, or fall back to a local `git diff`.

## Review GitHub CI and test evidence

1. Check the PR's GitHub statuses with `gh pr checks <pr> --repo <owner>/<repo>` and inspect `gh pr view <pr> --repo <owner>/<repo> --json statusCheckRollup,headRefOid`.
2. Treat failing or pending required checks as unresolved. If no checks are reported, say so explicitly; never describe that as a passing CI result. Inspect relevant failed logs with `gh run view <run-id> --repo <owner>/<repo> --log-failed`.
3. Review the PR's test-evidence links. Confirm the test-output link shows the reported result, the test-script permalink points to the test that ran, and the implementation permalink points to the changed code. Check that line links use the current PR head commit.
4. Confirm `docs/feature-map.md` changed and its linked entry describes the behavior affected by the PR. For frontend changes, verify that the required captured test video is present and corresponds to the changed UI.
5. Summarize CI state and evidence quality near the top of the review. Call out missing, stale, inaccessible, or contradictory evidence as a blocker or uncertainty; do not infer a pass from PR-body claims alone.

## Group changes for comprehension

Do not present files in alphabetical or tree order. Reorganize into sections ordered by reviewer value:

1. **Core logic** — New behavior, algorithm changes, state transitions, and API surface changes. Show full diffs with surrounding context.
2. **Wiring & integration** — Route registration, dependency injection, and configuration plumbing that connects the core logic. Condense to enough detail to confirm correctness.
3. **Boilerplate & mechanical** — Import reordering, renames, generated code, formatting, and type re-exports. Summarize as file names and stats; omit inline diffs unless relevant.

Lead with core logic, after the CI and test-evidence summary.

## Distill complex logic into pseudocode

When core changes involve dense or intricate logic, such as nested conditions, state machines, retry/backoff flows, or multi-step transformations, add a short pseudocode summary beside the diff. Strip away syntax, error handling, and boilerplate to expose the essential control flow. Straightforward changes do not need a pseudocode mirror.

## Trace tricky logic on a concrete example

For behavior changes that are hard to predict from reading the hunk, choose a small, realistic input and walk through both old and new paths, highlighting where they diverge and the observable outcome. Do not add a trace for every change.

## Call attention to tricky things

Visually separate genuinely surprising, risky, or easy-to-miss hunks and pair them with a short tag such as "Subtle", "Breaking", "Race condition", or "Perf" and a one-sentence explanation. Avoid overusing callouts.

## Tone and content

Write reviewer-facing commentary, not a changelog. Focus on why a change was made, interactions between files, and behavior that the diff alone does not make obvious. Keep each note to one or two sentences.

## Choose the right presentation

The goal is the fastest path for a reviewer to understand this specific change. Use the Canvas components available in the active environment when useful. Otherwise, use clear Markdown headings, links, tables, and compact summaries. Match the representation to the change: refactors, bug fixes, and new features need different walkthroughs.
