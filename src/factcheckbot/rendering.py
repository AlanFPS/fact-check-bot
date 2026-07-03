"""Render Reddit markdown replies."""

from urllib.parse import urlparse

from factcheckbot.config import Settings
from factcheckbot.models import Evidence, FactCheckResult, GoogleClaim, PipelineOutcome, Verdict

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
GOOGLE_DISCLAIMER = (
    "^(📰 These are real, published fact-checks from independent publishers, retrieved "
    "via Google's Fact Check Tools API and collected by a bot. Ratings and wording are "
    "each publisher's own, not the bot's opinion or an AI assessment.)"
)


def render_outcome(outcome: PipelineOutcome, settings: Settings) -> str:
    if outcome.source == "google":
        return render_google_reply(outcome.claim, outcome.google_claims, settings)
    if outcome.llm_result is None:
        raise ValueError("llm_result is required for LLM outcomes")
    return render_reply(outcome.claim, outcome.llm_result, outcome.evidence, settings)


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


def render_google_reply(
    claim: str,
    google_claims: list[GoogleClaim],
    settings: Settings,
) -> str:
    footer = FOOTER_TEMPLATE.format(trigger=settings.bot_trigger)
    rows = _google_rows(google_claims, settings.google_factcheck_max_claims)
    return _fit_google_to_limit(
        claim=claim,
        rows=rows,
        footer=footer,
        max_chars=settings.max_reply_chars,
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


def _google_rows(google_claims: list[GoogleClaim], max_rows: int) -> list[str]:
    rows: list[str] = []
    for google_claim in google_claims:
        for review in google_claim.reviews:
            if not _is_http_url(review.url):
                continue
            claim_text = _escape_table_cell(_truncate_table_text(google_claim.text, 200))
            rating = _escape_table_cell(review.textual_rating or "—")
            publisher = _escape_table_cell(review.publisher)
            rows.append(f"| {claim_text} | {rating} | [{publisher}]({review.url}) |")
            if len(rows) >= max_rows:
                return rows
    return rows


def _escape_table_cell(text: str) -> str:
    return _escape_markdown_title(_collapse_table_text(text)).replace("|", r"\|")


def _collapse_table_text(text: str) -> str:
    return " ".join(text.split())


def _truncate_table_text(text: str, max_chars: int) -> str:
    collapsed = _collapse_table_text(text)
    if len(collapsed) <= max_chars:
        return collapsed
    truncated = collapsed[: max_chars - 1].rstrip()
    if " " in truncated:
        truncated = truncated.rsplit(" ", 1)[0].rstrip()
    return f"{truncated}…"


def _fit_google_to_limit(
    *,
    claim: str,
    rows: list[str],
    footer: str,
    max_chars: int,
) -> str:
    current_rows = rows[:]
    while True:
        reply = _assemble_google_reply(claim, current_rows, footer)
        if len(reply) <= max_chars or not current_rows:
            return reply[:max_chars]
        current_rows.pop()


def _assemble_google_reply(claim: str, rows: list[str], footer: str) -> str:
    table = "| Claim | Rating | Source |\n|---|---|---|"
    if rows:
        table = f"{table}\n" + "\n".join(rows)
    return (
        "**Published fact-checks found** 📰\n\n"
        f"> {claim}\n\n"
        f"{table}\n\n"
        "---\n"
        f"{GOOGLE_DISCLAIMER}\n\n"
        f"{footer}"
    ).strip()


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
