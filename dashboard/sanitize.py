"""Make assistant text speakable before it reaches TTS.

Ported in spirit from aloud/backend/agent/sanitizer.py, which leaned on Pipecat's
MarkdownTextFilter. The system prompt already forbids markdown, so this is a safety
net: strip whatever slips through and make identifiers pronounceable, so the voice
never says "asterisk" or "underscore".
"""

import re

_FENCE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`([^`]*)`")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_URL = re.compile(r"https?://\S+")
_HEADER = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_BULLET = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+", re.MULTILINE)
_EMPHASIS = re.compile(r"(\*{1,3}|_{1,3})(?=\S)(.+?)(?<=\S)\1")
_SNAKE = re.compile(r"(?<=[A-Za-z0-9])_(?=[A-Za-z0-9])")  # from aloud: snake_case -> spoken words; \w would include _ itself
_SPACES = re.compile(r"[ \t]+")
_BLANKS = re.compile(r"\n{2,}")


def sanitize(text):
    t = _FENCE.sub(" ", text or "")
    t = _INLINE_CODE.sub(r"\1", t)
    t = _LINK.sub(r"\1", t)
    t = _URL.sub("a link", t)
    t = _HEADER.sub("", t)
    t = _BULLET.sub("", t)
    # snake_case before emphasis: intra-word underscores and _emphasis_ delimiters are
    # disjoint, and doing it the other way round lets "a_b then c_d" read as an italic span
    t = _SNAKE.sub(" ", t)
    t = _EMPHASIS.sub(r"\2", t)
    t = _SPACES.sub(" ", t)
    return _BLANKS.sub("\n", t).strip()
