# Making `brew install chronify` fast

## Why it was slow

Homebrew builds every Python dependency from source. Four of ours are C
extensions, and `pyobjc-core` alone is most of the twenty minutes. Nothing in
the project asks for that: every one of those libraries already publishes a
prebuilt wheel on PyPI. Homebrew simply does not use them by default.

## What we do instead

The formula points at those wheels. `brew install` then downloads and unpacks
instead of compiling, on every Mac, with no per-machine build. The wheels are
universal2 where the library offers one, so the same formula covers Apple
Silicon and Intel.

Files here:

| File | What it is |
|---|---|
| `chronify.rb` | the formula, with the generated resources and the install step |
| `wheels.py` | regenerates those resource blocks |
| `caveats.rb` | the text shown after installing |

## Putting it in place

1. Copy the resource blocks and the `install` method from `chronify.rb` into
   your tap's `Formula/chronify.rb`.
2. Keep your own `url` and `sha256` for the Chronify release itself. Only the
   dependency resources change.
3. Test it on a clean machine, or at least from a clean state:

   ```bash
   brew uninstall chronify
   time brew install zepuff/chronify/chronify
   ```

   It should be under a minute, and `brew install --verbose` should show no
   compiler running.

## When it needs attention

A wheel is built for one Python version. The formula pins
`depends_on "python@3.13"` for that reason. When you move it to a newer
Python, the wheels have to be regenerated:

```bash
python3 packaging/wheels.py --python 3.14 > resources.rb
```

Paste the output between the two `# --- generated resources ---` markers in
the formula. The script resolves the whole dependency tree through pip, finds
each wheel on PyPI and writes the URL and checksum, for both architectures.
Takes about a minute and needs no Mac.

You will know it is needed because the install fails loudly: pip refuses a
wheel built for another Python rather than installing something broken.

## Two things worth knowing

`rumps` publishes no wheel at all, only a source archive. It is pure Python,
so the formula builds it in a second without a compiler. That is what the
`sources` branch in the install step is for.

`brew audit` will complain about this formula, because installing wheels goes
against homebrew-core policy. That policy is about the central repository, not
about your own tap, and the trade is deliberate: a twenty minute install for
every person, against regenerating a list of URLs when Python moves.

## The other routes, for the record

**Bottles.** Build the formula once and upload the result. Install becomes a
download too, but a bottle is tied to a macOS version and a processor, so you
build one per combination and anyone on something else silently falls back to
compiling.

**A packaged .app.** PyInstaller puts Python and everything else inside one
universal2 app, shipped as a cask. Fastest for the user and it stops the
Screen Recording permission from resetting on every upgrade, because macOS
would see a stable app instead of a rebuilt binary. Costs a build step per
release, and an Apple Developer ID if you do not want the first-launch
warning.
