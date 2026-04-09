# Release Notes v0.1.0

## Overview

`v0.1.0` is the first public release of Codex Dispatcher: a Telegram bot for driving local Codex workflows with session continuity, account switching, and practical operator UX.

## Highlights

- Telegram to local Codex prompting with support for continuing existing sessions.
- Multiple local chats per Telegram chat, each with its own tracked session context.
- Per-chat runtime settings for model, reasoning, and sandbox mode.
- Session file workflows:
  - attach existing session id or rollout file,
  - create temporary VSCode view copies,
  - export and sync VSCode session copies explicitly.
- Account operations:
  - list and switch accounts,
  - optional auto-switch when limit markers are detected.
- Reliability and operations:
  - startup preflight checks with actionable failures,
  - compact `/health` diagnostics,
  - compact dashboard-style `/status` and `/threads`.
- Telegram UX improvements:
  - compact onboarding (`/start`),
  - grouped `/help`,
  - mini command docs (`/help <command>`),
  - inline action buttons for common safe navigation actions.

## Operational notes

- `codex.state_dir` is the shared runtime home for Codex session state.
- The bot processes prompts sequentially (single queue, one active worker).
- Use `/health` for readiness and runtime snapshot.
- Use `/status` and `/threads` for day-to-day operational context.
- Use `/sessionid` when you need full session detail.

## Known limitations

- No parallel Codex execution: runs are queued sequentially.
- Session workflows depend on local file paths and valid Codex home/index content.
- Inline actions intentionally avoid dangerous operations; unsafe modes still require explicit commands and confirmations.
- `danger-full-access` remains an explicit unsafe mode and should be used only when understood and intentional.
