# Release Notes v0.1.1

## Overview

`v0.1.1` is a patch release focused on post-`v0.1.0` stabilization: first-run usability, diagnostics clarity, CI confidence, and session/path edge-case hardening.

## Highlights

- CI and release confidence:
  - Added a Windows-first smoke workflow with Ubuntu sanity checks.
  - CI now validates install and first-run diagnostics flows directly.
- Better first-run experience:
  - Reduced setup friction in `config.example.json` and setup guidance in `README.md`.
  - Added compact first-run troubleshooting with direct fixes.
- Clearer diagnostics and UX:
  - `--check` output now uses explicit `Problem` / `Fix` style messages.
  - Callback and access messages in Telegram are more actionable.
- Session and path robustness:
  - Normalized Windows path handling for extended path prefixes and UNC forms.
  - Improved relative session reference resolution.
  - Session lookup can resolve from `threads.rollout_path` in `state_5.sqlite` for edge cases where filename patterns are insufficient.

## Operational notes

- Recommended quick health path:
  - `codex-dispatcher --check`
  - Start bot
  - `/health` and `/status`
- `allowed_chat_ids` can remain `[]` for first boot, then be locked down after retrieving `/chatid`.
- Session attach workflows are now more tolerant of legacy or non-standard rollout naming.

## Known limitations

- Prompt execution remains sequential (single worker queue).
- Session operations still depend on local Codex state/index consistency.
- Dangerous runtime modes remain explicit and opt-in (`danger-full-access`).
