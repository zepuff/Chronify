# Releasing a new version

Two repositories are involved:

- `zepuff/Chronify` holds the code, the site and this checklist
- `zepuff/homebrew-chronify` holds the formula people install from

The code is released first, then the formula is pointed at it.

## In the code repository

1. Update `CHANGELOG.md` with what changed.

2. Bump the version in two places, and keep them equal:

   - `pyproject.toml`, the `version` line
   - `chronify/__init__.py`, `__version__`

3. Check it:

   ```bash
   python3 -m pytest tests -q
   ```

4. Commit, tag, push:

   ```bash
   git add -A
   git commit -m "Release 0.3.0"
   git tag -a v0.3.0 -m "0.3.0"
   git push origin main --tags
   ```

5. Publish the release on GitHub. The tarball it creates is what the formula
   downloads:

   ```bash
   gh release create v0.3.0 --title "0.3.0" --notes-file CHANGELOG.md
   ```

6. Take the checksum of that tarball:

   ```bash
   curl -sL https://github.com/zepuff/Chronify/archive/refs/tags/v0.3.0.tar.gz \
     | shasum -a 256
   ```

## In the tap repository

7. In `Formula/chronify.rb`, two lines change per release:

   ```ruby
   url "https://github.com/zepuff/Chronify/archive/refs/tags/v0.3.0.tar.gz"
   sha256 "<the checksum from step 6>"
   ```

   The dependency resources stay as they are. They only need regenerating
   when the formula moves to a different Python, and `packaging/wheels.py`
   does that.

   Never run `brew update-python-resources` on this formula. It replaces the
   wheels with source archives, which is exactly the twenty minute install we
   moved away from.

8. Install it the way a person would, from a clean state, and time it:

   ```bash
   brew uninstall chronify
   brew update
   time brew install zepuff/chronify/chronify
   brew test chronify
   ```

   Under a minute, and no compiler in `brew install --verbose` output.

9. Commit and push the formula:

   ```bash
   git commit -am "chronify 0.3.0"
   git push
   ```

## Afterwards

Everyone else updates with:

```bash
brew update && brew upgrade chronify
```

Two things to tell them when the version carries them:

- macOS ties Screen Recording to the exact binary, so the permission has to be
  granted again after an upgrade
- a quit and start is needed for the new build to be the one running
