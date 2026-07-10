# update-all verifier

## Build

```bash
uv tool install . --force --python 3.11
```

## Drive the sequential path (the live panel)

```bash
update-all --only BREW --force
```

Observe: a Rich Panel box titled `BREW  Homebrew formulae & casks` with a live elapsed timer in the subtitle and up to 8 dimmed log lines. After completion the panel disappears and a single `✓ BREW  Homebrew formulae & casks  <duration>` line is left.

## Verify background mode (raw passthrough, no panel)

```bash
update-all --only BREW --force --background
```

Observe: raw Homebrew output printed directly, no panel, no Rich framing.

## Capture terminal output (optional)

```bash
script -q /tmp/ua.txt update-all --only BREW --force
sed 's/\x1b\[[0-9;]*[mKABCDHJsu]//g; s/\r//g' /tmp/ua.txt | grep -v '^$'
```
