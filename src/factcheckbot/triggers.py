"""Trigger parsing and author filtering."""

import re

KNOWN_BOTS = frozenset({"automoderator", "b0trank", "sneakpeekbot"})


def strip_quoted_and_code(body: str | None) -> str:
    if not body:
        return ""
    stripped = re.sub(r"(?s)```.*?```", "", body)
    stripped = re.sub(r"`[^`\n]*`", "", stripped)
    stripped = re.sub(r"(?m)^\s*>.*(?:\n|$)", "", stripped)
    return stripped


def contains_trigger(body: str | None, trigger: str) -> bool:
    if not body or not trigger:
        return False
    return trigger.lower() in body.lower()


def extract_inline_query(body: str, trigger: str, max_chars: int = 500) -> str:
    if not body or not trigger:
        return ""
    index = body.lower().find(trigger.lower())
    if index < 0:
        return ""
    query = body[index + len(trigger) :].lstrip(" \t\r\n:：'\"`")
    return normalize_claim(query, max_chars)


def is_ignorable_author(author: str | None, bot_username: str, ignore_bots: bool) -> bool:
    if author is None:
        return True
    normalized = author.lower()
    if normalized == bot_username.lower():
        return True
    if not ignore_bots:
        return False
    return normalized.endswith("bot") or normalized in KNOWN_BOTS


def normalize_claim(text: str, max_chars: int) -> str:
    cleaned_lines = []
    for line in text.splitlines():
        cleaned_lines.append(re.sub(r"^\s*>\s?", "", line))
    cleaned = " ".join(cleaned_lines)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.strip("\"'`“”‘’")
    if not cleaned:
        return ""
    if len(cleaned) <= max_chars:
        return cleaned
    truncated = cleaned[:max_chars].rstrip()
    if len(cleaned) > max_chars and cleaned[max_chars : max_chars + 1].strip() and " " in truncated:
        truncated = truncated.rsplit(" ", 1)[0].rstrip()
    return truncated
