from factcheckbot.triggers import (
    contains_trigger,
    extract_inline_query,
    is_ignorable_author,
    normalize_claim,
    strip_quoted_and_code,
)


def test_contains_trigger_case_insensitive_and_empty():
    assert contains_trigger("please !FACTCHECK this", "!factcheck")
    assert contains_trigger("mid !factcheck sentence", "!factcheck")
    assert not contains_trigger("", "!factcheck")
    assert not contains_trigger(None, "!factcheck")


def test_strip_quoted_and_code_suppresses_triggers():
    body = (
        "> !factcheck quoted claim\n"
        "```python\n"
        "!factcheck code block\n"
        "```\n"
        "Inline `!factcheck code span`\n"
        "Actual !factcheck real claim"
    )

    stripped = strip_quoted_and_code(body)

    assert contains_trigger(stripped, "!factcheck")
    assert extract_inline_query(stripped, "!factcheck") == "real claim"
    assert "quoted claim" not in stripped
    assert "code block" not in stripped
    assert "code span" not in stripped


def test_quoted_or_code_only_trigger_is_suppressed():
    body = "> !factcheck quoted\n\n```text\n!factcheck coded\n```\n`!factcheck inline`"

    assert not contains_trigger(strip_quoted_and_code(body), "!factcheck")


def test_extract_inline_query_variants():
    assert (
        extract_inline_query("please !factcheck The Sky Is Blue", "!factcheck")
        == "The Sky Is Blue"
    )
    assert extract_inline_query("!factcheck", "!factcheck") == ""
    assert extract_inline_query("!factcheck: 'quoted claim'", "!factcheck") == "quoted claim"
    assert extract_inline_query("x !factcheck first !factcheck second", "!factcheck") == (
        "first !factcheck second"
    )
    assert (
        extract_inline_query("!FACTCHECK " + "word " * 20, "!factcheck", max_chars=12)
        == "word word"
    )


def test_ignorable_author_rules():
    assert is_ignorable_author(None, "factbot", True)
    assert is_ignorable_author("FactBot", "factbot", True)
    assert is_ignorable_author("helperbot", "factbot", True)
    assert is_ignorable_author("AutoModerator", "factbot", True)
    assert not is_ignorable_author("helperbot", "factbot", False)
    assert not is_ignorable_author("alice", "factbot", True)


def test_normalize_claim_cleanup_and_truncate():
    assert normalize_claim('> "The   earth\n is round"`', 100) == "The earth is round"
    assert normalize_claim("   ", 100) == ""
    assert normalize_claim("alpha beta gamma", 10) == "alpha beta"
