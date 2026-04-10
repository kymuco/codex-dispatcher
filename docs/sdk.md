# Python SDK (`Dispatcher`)

`codex_dispatcher.sdk.Dispatcher` is a thin Python facade over the same orchestration layer used by Telegram and CLI flows.

## Quick start

```python
from codex_dispatcher.sdk import Dispatcher

dispatcher = Dispatcher.from_config("config.json")
code, report = dispatcher.check()
print(code)
print(report)
```

## Core methods

### Readiness and diagnostics

- `check()` -> `(exit_code, report_text)`
- `startup_report()` -> structured startup report dict
- `ensure_ready()` -> raises if startup checks fail

### Chat/session state

- `active_chat(chat_id)`
- `new_chat(chat_id, alias)`
- `use_chat(chat_id, alias)`
- `reset_chat(chat_id, alias=None)`
- `status(chat_id)`
- `health(chat_id)`
- `threads(chat_id)`
- `settings(chat_id)`
- `session_id(chat_id)`

### Runtime/account controls

- `accounts()`
- `switch_account(name)`
- `set_model(chat_id, model, alias=None)`
- `set_reasoning(chat_id, reasoning_effort, alias=None)`
- `set_sandbox(chat_id, sandbox_mode, alias=None)`

### Session file workflows

- `attach_session(chat_id, session_ref, alias=None)`
- `clone_vscode(chat_id, alias=None, title=None)`
- `export_vscode(chat_id, alias=None)`
- `sync_vscode(chat_id, alias=None)`
- `delete_vscode_copy(session_id)`

### Prompt execution

- `ask(chat_id, prompt, alias=None)`

## Example flows

### 1. Check + status

```python
from codex_dispatcher.sdk import Dispatcher

d = Dispatcher.from_config("config.json")
d.ensure_ready()

chat_id = 123456
status = d.status(chat_id)
print(status.active_alias, status.session, status.model)
```

### 2. Per-chat runtime settings

```python
chat_id = 123456

d.new_chat(chat_id, "bugfix")
d.set_model(chat_id, "gpt-5.4")
d.set_reasoning(chat_id, "high")
d.set_sandbox(chat_id, "workspace-write")

print(d.settings(chat_id))
```

### 3. Run a prompt

```python
result = d.ask(chat_id=123456, prompt="summarize this repository")
print(result.success, result.final_message)
```

### 4. Attach existing session

```python
attachment = d.attach_session(chat_id=123456, session_ref="019d....")
print(attachment.session_id, attachment.target_file)
```

## Error handling notes

- `ensure_ready()` and `ask()` can raise startup-related errors if environment is invalid.
- Invalid aliases/accounts/session references surface as `KeyError`/`ValueError`/`FileNotFoundError`, matching current service behavior.
- `ask()` validates non-empty prompt and raises `ValueError` for blank input.

## Stability notes

- This is the first SDK facade API and may grow in small, backward-compatible steps.
- Prefer these high-level methods over calling internal modules directly.
