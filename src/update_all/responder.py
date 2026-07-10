"""Interactive prompt auto-responder for update-all.

Encapsulates the logic that detects an interactive yes/no question in a
command's output stream and supplies a canned answer. Injected onto an
``Updater`` so that only opted-in tools (e.g. Homebrew) auto-confirm prompts;
every other tool is left untouched.
"""

from __future__ import annotations

import re

# Strips ANSI SGR/color escape sequences so a colored prompt still matches.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


class PromptResponder:
    """Detects interactive yes/no prompts in a text stream and supplies an answer."""

    # An explicit "[y/N]" / "[Y/n]" / "(yes/no)" token appearing ANYWHERE in the
    # tail — brew may print it before or after the question text
    # (e.g. "[Y/n] Proceed:" or "... proceed? [Y/n] (default Y)").
    TOKEN_PATTERN = re.compile(
        r"(\[y/n\]|\[yes/no\]|\(y/n\)|\(yes/no\))",
        re.IGNORECASE,
    )
    # Fallback: a bare question ending in "?" (e.g. brew's "Do you want to
    # proceed with the upgrade?") with no bracketed token. Anchored to the END
    # because only the un-terminated tail — normal lines are flushed on their
    # trailing newline — can be a prompt awaiting input.
    QUESTION_PATTERN = re.compile(r"\?[\s:>]*\Z")

    def __init__(
        self,
        answer: str = "y",
        pattern: re.Pattern[str] | None = None,
    ) -> None:
        self._answer = answer if answer.endswith("\n") else answer + "\n"
        # A caller-supplied pattern fully overrides the built-in detection.
        self._pattern = pattern

    def response_for(self, pending: str) -> bytes | None:
        """Return the bytes to write back if ``pending`` looks like a prompt, else ``None``.

        ``pending`` is the un-terminated tail of output (text since the last
        newline), i.e. the current prompt candidate.
        """
        text = _ANSI_RE.sub("", pending)
        if self._pattern is not None:
            return self._answer.encode() if self._pattern.search(text) else None
        if self.TOKEN_PATTERN.search(text) or self.QUESTION_PATTERN.search(text):
            return self._answer.encode()
        return None
