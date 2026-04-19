---
name: patch
description: Use when releasing a new patch version of named-pipes to GitHub and PyPI
---

# Patch Release

Releases a new **patch** version: increments the last digit of the semver (e.g. `0.3.0` → `0.3.1`).

## Steps

### 1. Determine next version

Read `pyproject.toml` for `version = "X.Y.Z"`. Next version is `X.Y.(Z+1)`.

### 2. Update version

Edit `pyproject.toml`: set `version = "X.Y.(Z+1)"`.

### 3. Update CHANGELOG.md

Prepend a new section at the top (after the `# Changelog` heading) for the new version:

```markdown
## X.Y.(Z+1) — YYYY-MM-DD

### Bug fixes
...

### Improvements (if applicable)
...
```

Summarise commits since the previous tag:

```bash
git log vX.Y.Z..HEAD --oneline
```

### 4. Update RELEASE.md

Replace the entire contents of `RELEASE.md` with only the body of the new changelog entry (the sections under the new version heading). **No top-level header** — start directly with `## Bug fixes` or equivalent.

### 5. Commit and tag

```bash
git add pyproject.toml CHANGELOG.md RELEASE.md
git commit -m "Release vX.Y.(Z+1): <one-line summary>"
git tag -a vX.Y.(Z+1) HEAD -m "<same one-line summary>"
git push origin main --follow-tags
```

The tag **must point to HEAD** (the commit that includes the workflow in `.github/workflows/release.yml`), otherwise GitHub Actions won't fire.

## What happens next

Pushing the tag triggers:
- `release.yml` → creates a GitHub release with auto-generated notes
- `publish.yml` → publishes to PyPI via OIDC trusted publisher
