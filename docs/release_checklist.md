# Release Checklist (v0.1.1)

Use this checklist right before creating tag `v0.1.1`.

- [ ] Working tree is clean (`git status --short` is empty).
- [ ] `python -m unittest discover -s tests -v` passed locally.
- [ ] CI Smoke workflow is green on `main` (Windows smoke + Ubuntu sanity).
- [ ] Startup preflight smoke check passed (run bot once with real config; no startup check failures).
- [ ] Manual Telegram smoke checks completed:
  - [ ] `/start`
  - [ ] `/help`
  - [ ] `/health`
  - [ ] `/status`
  - [ ] `/threads`
- [ ] One attach flow tested (`/attachsession <id_or_path>`).
- [ ] One VSCode flow tested (`/clonevscode` and at least one of `/exportvscode` or `/syncvscode`).
- [ ] `config.example.json` is still accurate for new users.
- [ ] `README.md` and `CHANGELOG.md` match current behavior.
- [ ] `docs/release_notes_v0.1.1.md` is finalized.
- [ ] `pyproject.toml` version is `0.1.1`.

Tag and push:

```powershell
git checkout main
git pull --ff-only origin main
git tag -a v0.1.1 -m "v0.1.1"
git push origin main
git push origin v0.1.1
```
