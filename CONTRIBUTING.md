# Contributing

Thanks for helping improve Codex Dispatcher.

## Development Setup

```powershell
python -m pip install -e .
```

## Run Tests

```powershell
python -m unittest discover -s tests -v
```

## Pull Request Checklist

1. Keep the change focused and minimal.
2. Add or update tests when behavior changes.
3. Update docs (`README.md`, `CHANGELOG.md`, `RELEASE.md`) when relevant.
4. Ensure tests pass locally before opening the PR.
5. Keep secrets and local runtime files out of commits.

## Commit Message Style

Use Conventional Commit style:

```text
feat(patch): short description
```

Other examples:

```text
fix(patch): correct sandbox mapping for resume
docs(patch): add troubleshooting section
```

## Scope and Compatibility

- Prefer backward-compatible changes unless a breaking change is explicitly planned.
- If a change affects CLI behavior, document it in `README.md`.
