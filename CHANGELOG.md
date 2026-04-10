# Changelog

All notable changes to this project will be documented in this file.

This changelog follows a lightweight Keep a Changelog style and Semantic Versioning.

## [Unreleased]

No unreleased changes.

## [0.1.1] - 2026-04-10

### Changed
- Improved first-run setup ergonomics in `README.md` and `config.example.json` (safer starter defaults and clearer setup flow).
- Tightened ambiguous callback and chat-access messages with clearer next-step guidance.
- Added concise first-run troubleshooting map based on real install failures.

### Reliability
- Added Windows-first CI smoke pipeline with Ubuntu sanity check for install/diagnostics flow.
- Improved `--check` diagnostics output with explicit `Problem` / `Fix` messaging.
- Normalized Windows path handling (`\\?\`, UNC prefix, relative reference resolution) across session and diagnostics flows.
- Hardened session lookup edge cases by resolving `session_id` via `threads.rollout_path` when filename matching is insufficient.

### Testing
- Expanded regression coverage for diagnostics formatting and path normalization.
- Added session-manager tests for relative session refs and DB rollout-path resolution.

## [0.1.0] - 2026-04-10

### Added
- Telegram bot runtime for local Codex prompting and session continuation (`exec` / `exec resume`).
- Local chat aliases per Telegram chat with session tracking and switching.
- Session utilities: attach existing sessions, VSCode copy flows (`clone`, `export`, `sync`), and purge tool.
- Runtime per-chat controls for model, reasoning, and sandbox behavior.
- `/health` command for compact bot readiness and runtime diagnostics.
- Inline action buttons for `/status` and `/threads` safe navigation flows.

### Changed
- Onboarding and command discovery UX: compact `/start`, grouped `/help`, and mini-docs via `/help <command>`.
- Operational command outputs were compacted for phone-first readability (`/status`, `/threads`, `/settings`, `/sessionid`).
- Command validation and guidance use recovery-first error messages with clear next actions.

### Reliability
- Added startup preflight checks before polling (binary, workspace, state dir, account files).
- Startup failures now stop early with concise actionable messages.
- Expanded integration-style command routing tests and callback action coverage.
- Cross-platform test stability improved for environments without `codex` in `PATH`.

### Documentation
- README rewritten around user scenarios, quick start, safety notes, and command map.
- Added community files and GitHub contribution templates.
- Added release notes and a short release checklist for `v0.1.0`.
