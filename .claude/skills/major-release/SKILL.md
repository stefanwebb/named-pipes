---
name: major-release
description: Use when releasing a new major version of named-pipes to GitHub and PyPI
---

# Major Release

Releases a new **major** version: increments the first digit of the semver and resets minor and patch to 0 (e.g. `0.3.1` → `1.0.0`).

## Steps

### 1. Determine next version

Read `pyproject.toml` for `version = "X.Y.Z"`. Next version is `(X+1).0.0`.

### 2. Update version

Edit `pyproject.toml`: set `version = "(X+1).0.0"`.

### 3. Update CHANGELOG.md

Prepend a new section at the top (after the `# Changelog` heading) for the new version:

```markdown
## (X+1).0.0 — YYYY-MM-DD

### Breaking changes
...

### New features
...

### Improvements (if applicable)
...
```

Summarise commits since the previous tag:

```bash
git log vX.Y.Z..HEAD --oneline
```

### 4. Update RELEASE.md

Replace the entire contents of `RELEASE.md` with only the body of the new changelog entry (the sections under the new version heading). **No top-level header** — start directly with `## Breaking changes` or equivalent.

### 5. Commit and tag

```bash
git add pyproject.toml CHANGELOG.md RELEASE.md
git commit -m "Release v(X+1).0.0: <one-line summary>"
git tag -a v(X+1).0.0 HEAD -m "<same one-line summary>"
git push origin main --follow-tags
```

The tag **must point to HEAD** (the commit that includes the workflow in `.github/workflows/release.yml`), otherwise GitHub Actions won't fire.

## What happens next

Pushing the tag triggers:
- `release.yml` → creates a GitHub release with auto-generated notes
- `publish.yml` → publishes to PyPI via OIDC trusted publisher
