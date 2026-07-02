"""Render Reddit markdown replies."""

from urllib.parse import urlparse

from factcheckbot.config import Settings
from factcheckbot.models import Evidence, FactCheckResult, Verdict

VERDICT_EMOJI = {
    Verdict.TRUE: "✅",
    Verdict.MOSTLY_TRUE: "✅",
    Verdict.MIXED: "⚖️",
    Verdict.MOSTLY_FALSE: "❌",
    Verdict.FALSE: "❌",
    Verdict.UNVERIFIABLE: "❓",
}

DISCLAIMER = (
    "^(🤖 I'm an experimental, AI-powered bot. This is an automated, LLM-generated "
    "assessment based on a quick web search, NOT authoritative fact-checking. Verify "
    "important claims yourself.)"
)
FOOTER_TEMPLATE = (
    "^(Usage: reply to any comment with `{trigger} <claim>`, or just `{trigger}` to check "
    "the comment you're replying to.)"
)
NO_CLAIM_DISCLAIMER = (
    "^(🤖 I'm an experimental, AI-powered bot, not an authoritative fact-checker.)"
)


def render_reply(
    claim: str,
    result: FactCheckResult,
    evidence: list[Evidence],
    settings: Settings,
) -> str:
    confidence = round(result.confidence * 100)
    header = (
        f"**Fact check: {VERDICT_EMOJI[result.verdict]} {result.verdict.value}**  "
        f"(confidence: {confidence}%)"
    )
    footer = FOOTER_TEMPLATE.format(trigger=settings.bot_trigger)
    source_lines = _source_lines(result, evidence)
    return _fit_to_limit(
        header=header,
        claim=claim,
        reasoning=result.reasoning,
        source_lines=source_lines,
        footer=footer,
        max_chars=settings.max_reply_chars,
    )


def render_no_claim_reply(settings: Settings) -> str:
    return (
        "I couldn't find a claim to check. Reply with "
        f"`{settings.bot_trigger} <claim>`, or use just\n"
        f"`{settings.bot_trigger}` as a reply to the comment or post you want checked.\n\n"
        "---\n"
        f"{NO_CLAIM_DISCLAIMER}"
    )


def _sources_block(result: FactCheckResult, evidence: list[Evidence]) -> str:
    lines = _source_lines(result, evidence)
    if not lines:
        return "*No web sources were found for this claim.*"
    return "**Sources**\n" + "\n".join(lines)


def _source_lines(result: FactCheckResult, evidence: list[Evidence]) -> list[str]:
    if not evidence:
        return []
    by_index = {item.index: item for item in evidence}
    selected = [
        by_index[index]
        for index in result.cited_sources
        if index in by_index and _is_http_url(by_index[index].url)
    ]
    if not selected:
        selected = [item for item in evidence if _is_http_url(item.url)][:5]
    return [
        f"{index}. [{_escape_markdown_title(item.title)}]({item.url})"
        for index, item in enumerate(selected, start=1)
    ]


def _escape_markdown_title(title: str) -> str:
    return (
        title.replace("\\", "\\\\")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )


def _is_http_url(url: str) -> bool:
    return urlparse(url).scheme in {"http", "https"}


def _fit_to_limit(
    *,
    header: str,
    claim: str,
    reasoning: str,
    source_lines: list[str],
    footer: str,
    max_chars: int,
) -> str:
    lines = source_lines[:]
    current_reasoning = reasoning
    while True:
        reply = _assemble_reply(header, claim, current_reasoning, lines, footer)
        if len(reply) <= max_chars:
            return reply
        if lines:
            lines.pop()
            continue
        fixed = _assemble_reply(header, claim, "", [], footer)
        available = max(max_chars - len(fixed) - 1, 0)
        if available <= 1:
            return fixed[:max_chars]
        truncated = current_reasoning[: available - 1].rstrip() + "…"
        return _assemble_reply(header, claim, truncated, [], footer)[:max_chars]


def _assemble_reply(
    header: str,
    claim: str,
    reasoning: str,
    source_lines: list[str],
    footer: str,
) -> str:
    if source_lines:
        sources = "**Sources**\n" + "\n".join(source_lines)
    else:
        sources = "*No web sources were found for this claim.*"
    return (
        f"{header}\n\n"
        f"> {claim}\n\n"
        f"{reasoning}\n\n"
        f"{sources}\n\n"
        "---\n"
        f"{DISCLAIMER}\n\n"
        f"{footer}"
    ).strip()
