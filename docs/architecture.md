# Architecture

This document describes the current layering in Codex Dispatcher after the first core and SDK extraction steps.

## Layer model

Codex Dispatcher is organized around one shared orchestration service.

1. Core orchestration
   - `codex_dispatcher/core/service.py`
   - Owns application workflows: startup checks, status/health snapshots, chat/session/account operations, prompt execution orchestration, and VSCode session flows.
2. Interface adapters
   - Telegram adapter: `codex_dispatcher/bot.py`
   - CLI adapter: `codex_dispatcher/__main__.py`, `codex_dispatcher/check_env.py`, `scripts/check_env.py`
   - Python SDK facade: `codex_dispatcher/sdk/dispatcher.py`
3. Lower-level runtime modules
   - Config and diagnostics: `config.py`, `diagnostics.py`
   - Persistence and session/account state: `state.py`, `accounts.py`, `session_manager.py`
   - Codex process runner: `codex_runner.py`
   - Path safety helpers: `path_utils.py`

## Request flow

### Telegram flow

`Telegram update -> bot command/callback routing -> DispatcherService -> state/session/runner -> bot text rendering`

### CLI check flow

`codex-dispatcher --check -> run_environment_check -> DispatcherService.startup_report -> report output`

### SDK flow

`Dispatcher API call -> DispatcherService -> shared modules (state/sessions/accounts/runner)`

## Responsibilities

### What belongs in core

- Domain and orchestration logic that should be reused across interfaces.
- State transitions for chats, sessions, and account selection.
- Startup readiness checks and summary snapshots.

### What belongs in adapters

- Transport-specific parsing/routing/rendering.
- Output formatting for Telegram and CLI entrypoints.
- Minimal glue code around the shared service.

## Design rules

- Keep business logic in `DispatcherService` when possible.
- Keep Telegram-specific UI behavior in `bot.py`.
- Keep CLI argument handling in `__main__.py`.
- Add new external interfaces on top of SDK/core, not by duplicating logic.

## Near-term direction

- Expand SDK examples and stability guarantees incrementally.
- Continue routing future CLI commands through shared service methods.
- Keep refactors narrow to preserve current runtime behavior.
