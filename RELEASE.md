# Release Checklist

This checklist is for creating a stable release from `main`.

## 1. Pre-release validation

- [ ] Working tree is clean (`git status --short` is empty).
- [ ] `config.json`, runtime state folders, and local secrets are not tracked.
- [ ] CI is green for the target commit.

## 2. Local verification

Run the same baseline checks used in CI:

```powershell
python -m pip install -e .
python -m unittest discover -s tests -v
python -m pip install build
python -m build
```

## 3. Changelog update

- [ ] Move important items from `Unreleased` to a new version section in `CHANGELOG.md`.
- [ ] Set the release date in `YYYY-MM-DD` format.

## 4. Tag and push

```powershell
git checkout main
git pull --ff-only origin main
git tag -a vX.Y.Z -m "vX.Y.Z"
git push origin main
git push origin vX.Y.Z
```

## 5. GitHub release

- [ ] Create a GitHub Release from tag `vX.Y.Z`.
- [ ] Use `CHANGELOG.md` notes as release notes.
- [ ] Attach `dist/*` artifacts from CI if needed.
