# Google Fact Check Layer Review

Overall, I would not merge this as-is until the API-key logging issue is fixed. The tiering itself is sound: Google hits skip ddgs and the LLM, and no-key/no-hit/non-200/exception cases fall back to the old LLM path. For an educational project, the feature is otherwise close and well covered.

## Findings

| ID | Severity | File:line | Issue | Suggested fix |
|---|---|---:|---|---|
| G-001 | HIGH | `src/factcheckbot/google_factcheck.py:48` | Google failures log the raw exception text. If an `httpx`/transport exception, proxy, mock, or future `raise_for_status()` path includes the request URL, the logged URL can contain `key=<GOOGLE_FACTCHECK_API_KEY>`. The key does not appear in replies, but it can leak to logs. | Do not interpolate raw exceptions from this call. Log the exception class and safe context only, or explicitly redact the configured key before logging. Add a `caplog` regression test that raises an exception containing the key and asserts the key is absent. |
| G-002 | MEDIUM | `src/factcheckbot/rendering.py:138` | Google publisher text is escaped for Markdown link syntax, but not for table-cell pipes. A publisher like `Bad | Publisher` can break the table layout and make the source column misleading. | Escape publisher text as a table cell before placing it inside the link label, or make `_escape_markdown_title` also handle `|` when used in table cells. |
| G-003 | LOW | `src/factcheckbot/google_factcheck.py:43` | Mapping is effectively all-or-nothing for a response. One malformed claim/review that makes Pydantic reject optional fields can trigger the broad `except` and discard otherwise valid Google hits, forcing unnecessary fallback. | Iterate claims in a loop, catch mapping/validation errors per claim, and coerce optional scalar fields such as `claimant`, `title`, and `reviewDate` to `str | None`. |
| G-004 | LOW | `README.md:3` | The opening description still says the bot uses an LLM instead of Google's Fact Check Tools API. The later optional Google section is accurate, but the intro now undersells the new first tier. | Adjust the intro to say the bot is local/LLM-backed by default with an optional Google Fact Check Tools first tier. |

## High-Severity Detail

### G-001: Google API key can leak through logged exception text

Problematic snippet:

```python
        except Exception as exc:
            logger.warning("Google fact-check failed: %s", exc)
            return []
```

The request is made with the key in query params:

```python
            response = self._client.get(
                self.ENDPOINT,
                params={
                    "query": query,
                    "key": self._settings.google_factcheck_api_key,
                    "languageCode": self._settings.google_factcheck_language,
                    "pageSize": self._settings.google_factcheck_max_claims,
                },
                timeout=self._settings.google_factcheck_timeout_seconds,
            )
```

Concrete fix:

```python
        except Exception as exc:
            logger.warning("Google fact-check failed (%s)", type(exc).__name__)
            return []
```

If keeping the message is important, run it through a redaction helper:

```python
def _redact_key(message: str, api_key: str | None) -> str:
    if not api_key:
        return message
    return message.replace(api_key, "[redacted]")
```

Then add a regression test with a fake client that raises `RuntimeError("boom key=secret-key")` and assert `secret-key` is not in `caplog.text`.

## Pytest Run

Command:

```text
source .venv/bin/activate && pytest
```

Result:

```text
56 passed in 0.30s
```

The new tests are meaningful. They assert Google hits do not call ddgs/LLM, disabled/no-hit paths fall back, non-200 and thrown HTTP exceptions return `[]`, non-http review URLs are dropped, config keeps the key optional, and rendering uses the published-fact-check table rather than the AI verdict path.

Important gaps: no regression test for API-key redaction in logs, no malformed-optional-field case inside an otherwise valid Google response, and no publisher `|` injection case in the Google table renderer.

## Explicit Answers

- Does no-key behavior exactly match v1? Yes. `__main__` passes `google=None` when the key is unset/blank, and the pipeline goes straight to search plus LLM.
- Can any Google-layer exception crash the bot instead of falling back? No for the production `GoogleFactCheckClient.search()` path reviewed here. It catches broad exceptions around the HTTP call and mapping, returns `[]`, and the pipeline falls back. The pipeline does trust any injected Google collaborator to follow that contract.
- Can the API key leak into logs or replies? Yes for logs, via raw exception text in `google_factcheck.py`. I did not find a reply path that includes the key.
