"""Tests for update_all.responder."""

import re

import pytest

from update_all.responder import PromptResponder


@pytest.mark.parametrize(
    "text",
    [
        "Do you want to continue? [y/N] ",
        "Proceed? [Y/n]",
        "Really delete? [yes/no]:",
        "Continue (y/n)? ",
        "Overwrite (yes/no)> ",
        "PROCEED? [Y/N]",
        "Do you want to proceed with the upgrade? [Y/n] ",
        "Do you want to proceed with the upgrade? ",
        "Do you want to proceed with the upgrade?",
        # token before / after the question text, or wrapped by trailing text
        "[Y/n] Proceed with the upgrade: ",
        "Do you want to proceed? [Y/n] (default Y) ",
        "Proceed [Y/n] anyway: ",
    ],
)
def test_answers_prompt(text):
    assert PromptResponder().response_for(text) == b"y\n"


@pytest.mark.parametrize(
    "text",
    [
        "Upgrading foo [1/3]",
        "Downloading package...",
        "==> Pouring bottle",
        "",
    ],
)
def test_ignores_non_prompt(text):
    assert PromptResponder().response_for(text) is None


def test_strips_ansi_color():
    colored = "\x1b[1mProceed?\x1b[0m [y/N] "
    assert PromptResponder().response_for(colored) == b"y\n"


def test_custom_answer():
    assert PromptResponder(answer="n").response_for("ok? [y/N] ") == b"n\n"


def test_custom_answer_keeps_existing_newline():
    assert PromptResponder(answer="yes\n").response_for("ok? [y/N] ") == b"yes\n"


def test_custom_pattern():
    responder = PromptResponder(pattern=re.compile(r"continue\?\s*\Z", re.IGNORECASE))
    assert responder.response_for("continue?") == b"y\n"
    assert responder.response_for("done [y/N] ") is None
