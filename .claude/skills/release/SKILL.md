---
name: release
description: Use when releasing a new minor version of named-pipes to GitHub and PyPI
---

# Release

Releases a new **minor** version: increments the middle digit of the semver and resets the patch digit to 0 (e.g. `0.1.2` → `0.2.0`).

## Steps

### 1. Determine next version

Read `pyproject.toml` for `version = "X.Y.Z"`. Next version is `X.(Y+1).0`.

### 2. Update version

Edit `pyproject.toml`: set `version = "X.(Y+1).0"`.

### 3. Update CHANGELOG.md

Prepend a new section at the top (after the `# Changelog` heading) for the new version:

```markdown
## X.(Y+1).0 — YYYY-MM-DD

### New features
...

### Improvements
...

### Infrastructure / Documentation (if applicable)
...
```

Summarise commits since the previous tag:

```bash
git log vX.Y.Z..HEAD --oneline
```

### 4. Update RELEASE.md

Replace the entire contents of `RELEASE.md` with only the body of the new changelog entry (the sections under the new version heading). **No top-level header** — start directly with `## New features` or equivalent.

### 5. Commit and tag

```bash
git add pyproject.toml CHANGELOG.md RELEASE.md
git commit -m "Release vX.(Y+1).0: <one-line summary>"
git tag -a vX.(Y+1).0 HEAD -m "<same one-line summary>"
git push origin main --follow-tags
```

The tag **must point to HEAD** (the commit that includes the workflow in `.github/workflows/release.yml`), otherwise GitHub Actions won't fire.

## What happens next

Pushing the tag triggers:
- `release.yml` → creates a GitHub release with auto-generated notes
- `publish.yml` → publishes to PyPI via OIDC trusted publisher
