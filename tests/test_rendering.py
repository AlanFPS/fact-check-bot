from factcheckbot.models import (
    Evidence,
    FactCheckResult,
    GoogleClaim,
    GoogleReview,
    PipelineOutcome,
    Verdict,
)
from factcheckbot.rendering import (
    render_google_reply,
    render_no_claim_reply,
    render_outcome,
    render_reply,
)
from tests.fixtures import CANNED_EVIDENCE


def test_render_reply_includes_core_parts(settings):
    result = FactCheckResult(
        verdict=Verdict.FALSE,
        confidence=0.84,
        reasoning="The sources contradict the claim.",
        cited_sources=[2],
    )

    reply = render_reply("The claim.", result, CANNED_EVIDENCE, settings)

    assert "**Fact check: ❌ FALSE**  (confidence: 84%)" in reply
    assert "> The claim." in reply
    assert "The sources contradict the claim." in reply
    assert "1. [Source two](https://example.com/two)" in reply
    assert "Source one" not in reply
    assert "AI-powered bot" in reply
    assert "Usage: reply" in reply


def test_no_evidence_message(settings):
    result = FactCheckResult(
        verdict=Verdict.UNVERIFIABLE,
        confidence=0,
        reasoning="There is no evidence.",
        cited_sources=[],
    )

    reply = render_reply("The claim.", result, [], settings)

    assert "*No web sources were found for this claim.*" in reply


def test_empty_cited_sources_lists_retrieved_evidence(settings):
    result = FactCheckResult(
        verdict=Verdict.MIXED,
        confidence=0.5,
        reasoning="Evidence is mixed.",
        cited_sources=[],
    )

    reply = render_reply("The claim.", result, CANNED_EVIDENCE, settings)

    assert "1. [Source one](https://example.com/one)" in reply
    assert "2. [Source two](https://example.com/two)" in reply


def test_source_titles_are_escaped_and_non_http_urls_skipped(settings):
    evidence = [
        Evidence(
            index=1,
            title=r"A [bad](title) \ test",
            url="https://example.com/one",
            snippet="",
        ),
        Evidence(index=2, title="Javascript URL", url="javascript:alert(1)", snippet=""),
    ]
    result = FactCheckResult(
        verdict=Verdict.MIXED,
        confidence=0.5,
        reasoning="Evidence is mixed.",
        cited_sources=[],
    )

    reply = render_reply("The claim.", result, evidence, settings)

    assert r"1. [A \[bad\]\(title\) \\ test](https://example.com/one)" in reply
    assert "Javascript URL" not in reply
    assert "javascript:alert" not in reply


def test_over_limit_keeps_footer(settings):
    settings.max_reply_chars = 500
    result = FactCheckResult(
        verdict=Verdict.TRUE,
        confidence=1,
        reasoning="Long reasoning. " * 200,
        cited_sources=[],
    )

    reply = render_reply("The claim.", result, CANNED_EVIDENCE, settings)

    assert len(reply) <= settings.max_reply_chars
    assert "AI-powered bot" in reply
    assert "Usage: reply" in reply


def test_render_no_claim_reply_contains_usage(settings):
    reply = render_no_claim_reply(settings)

    assert "I couldn't find a claim to check" in reply
    assert "`!factcheck <claim>`" in reply


def test_render_google_reply_outputs_published_fact_check_table(settings):
    settings.google_factcheck_max_claims = 1
    claims = [
        GoogleClaim(
            text="A | claim\nwith newline",
            reviews=[
                GoogleReview(
                    publisher=r"Fact [Publisher](test)",
                    textual_rating="",
                    url="https://example.com/review",
                ),
                GoogleReview(
                    publisher="Second Publisher",
                    textual_rating="True",
                    url="https://example.com/second",
                ),
            ],
        )
    ]

    reply = render_google_reply("Original claim.", claims, settings)

    assert "**Published fact-checks found** 📰" in reply
    assert "> Original claim." in reply
    assert "| Claim | Rating | Source |" in reply
    assert r"| A \| claim with newline | — | [Fact \[Publisher\]\(test\)]" in reply
    assert "(https://example.com/review)" in reply
    assert "Second Publisher" not in reply
    assert "real, published fact-checks" in reply
    assert "AI-generated assessment" not in reply


def test_render_google_reply_escapes_table_markdown_and_publisher_pipe(settings):
    claims = [
        GoogleClaim(
            text="Claim says [click](http://evil) | now",
            reviews=[
                GoogleReview(
                    publisher="Bad | Publisher",
                    textual_rating="[False](http://evil)",
                    url="https://example.com/review",
                )
            ],
        )
    ]

    reply = render_google_reply("Original claim.", claims, settings)

    assert "[click](http://evil)" not in reply
    assert r"\[click\]\(http://evil\)" in reply
    assert r"\[False\]\(http://evil\)" in reply
    assert r"[Bad \| Publisher](https://example.com/review)" in reply


def test_render_google_reply_over_limit_keeps_disclaimer_and_footer(settings):
    settings.max_reply_chars = 550
    claims = [
        GoogleClaim(
            text=f"Claim {index}",
            reviews=[
                GoogleReview(
                    publisher="Publisher",
                    textual_rating="False",
                    url=f"https://example.com/{index}",
                )
            ],
        )
        for index in range(10)
    ]

    reply = render_google_reply("Original claim.", claims, settings)

    assert len(reply) <= settings.max_reply_chars
    assert "**Published fact-checks found**" in reply
    assert "real, published fact-checks" in reply
    assert "Usage: reply" in reply


def test_render_outcome_dispatches_google_and_llm(settings):
    google_outcome = PipelineOutcome(
        source="google",
        claim="Original claim.",
        google_claims=[
            GoogleClaim(
                text="Matched claim.",
                reviews=[
                    GoogleReview(
                        publisher="Publisher",
                        textual_rating="False",
                        url="https://example.com/review",
                    )
                ],
            )
        ],
    )
    llm_result = FactCheckResult(
        verdict=Verdict.FALSE,
        confidence=0.8,
        reasoning="The sources contradict the claim.",
        cited_sources=[1],
    )
    llm_outcome = PipelineOutcome(
        source="llm",
        claim="Original claim.",
        llm_result=llm_result,
        evidence=CANNED_EVIDENCE,
    )

    assert "**Published fact-checks found**" in render_outcome(google_outcome, settings)
    assert "**Fact check:" in render_outcome(llm_outcome, settings)
