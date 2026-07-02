# fact-check-bot — Implementation Plan

This is a decision-complete build spec. An engineer following it should be able to produce the code without making further design decisions. Everything below (file layout, signatures, prompts, templates, config) is prescriptive. Where a choice was made, the rationale is stated inline so you don't second-guess it.

---

## 1. Overview & goals

Rebuild the decommissioned Reddit fact-checking bot with a local-first, LLM-backed pipeline instead of the Google Fact Check Tools API.

**What it does**
- Watches Reddit for `!factcheck <claim>` triggers (comment streams on a configurable subreddit list, and/or username @mentions in the inbox).
- Extracts the claim (from the trigger text, or from the parent comment/post if the user typed a bare `!factcheck`).
- Retrieves evidence with a free web search (`ddgs`, no API key).
- Feeds claim + evidence snippets to an LLM through an OpenAI-compatible client, defaulting to a local Ollama model.
- Gets back a **structured JSON verdict** (verdict enum, confidence, one-paragraph reasoning, cited source indices).
- Replies with a markdown message: verdict, reasoning, numbered source links, disclaimer, how-to footer.

**Design goals**
- Cheap / local by default. Runs against `http://localhost:11434/v1` (Ollama) with zero paid API keys. Reconfigurable via env to any OpenAI-compatible endpoint (OpenRouter, Groq, OpenAI).
- Educational and readable. Single process, no queues, no external DB beyond a SQLite file. Clean separation of pure logic (parsing, rendering, JSON handling) from I/O edges (Reddit, HTTP, LLM) so the core is unit-testable with everything mocked.
- Robust enough to run unattended: dedupe across restarts, never reply to itself or loop, ignore other bots, rate-limit per-user and globally, cap reply length, survive Ollama being down and PRAW exceptions, and support a dry-run mode.

**Non-goals**: authoritative fact-checking, multi-process scaling, a web UI, model fine-tuning. This bot's replies are clearly labeled as AI-generated and not authoritative.

---

## 2. Architecture (ASCII) + data flow

```
                          ┌─────────────────────────────────────────────┐
                          │                  bot.py                      │
                          │  (main loop, wiring, signal handling)        │
                          └───────────────┬─────────────────────────────┘
                                          │
              ┌───────────────────────────┼───────────────────────────┐
              │                           │                           │
      ┌───────▼────────┐        ┌─────────▼────────┐         ┌────────▼─────────┐
      │ comment stream │        │  inbox mentions  │         │   SIGINT/SIGTERM │
      │ (subreddits)   │        │  (@username)     │         │   graceful stop  │
      └───────┬────────┘        └─────────┬────────┘         └──────────────────┘
              │                           │
              └─────────────┬─────────────┘
                            │  praw Comment / Message objects
                            ▼
                   ┌──────────────────┐   already seen? self? bot? rate-limited?
                   │  gatekeeping     │───────────────────────────────► skip (log)
                   │ (seen_store,     │
                   │  rate_limit)     │
                   └────────┬─────────┘
                            │ TriggerContext (claim text OR parent ref)
                            ▼
                   ┌──────────────────────────────────────────────────┐
                   │                  pipeline.py                      │
                   │                                                   │
                   │  triggers.extract_claim ──► claim string          │
                   │        │ (if empty, use parent body via reddit)   │
                   │        ▼                                          │
                   │  search.search_evidence ──► list[Evidence]        │
                   │        │  (ddgs.text, N results, truncated)       │
                   │        ▼                                          │
                   │  llm.fact_check ──► Verdict (structured JSON)     │
                   │        │  (OpenAI-compat client; JSON mode+retry) │
                   │        ▼                                          │
                   │  rendering.render_reply ──► markdown string       │
                   └────────┬──────────────────────────────────────────┘
                            │ reply text (<= 10000 chars)
                            ▼
                   ┌──────────────────┐
                   │ reddit_client    │  dry_run? ──► log only
                   │ .safe_reply      │  else ──► comment.reply(text)
                   └────────┬─────────┘
                            │ on success
                            ▼
                   ┌──────────────────┐
                   │  seen_store.mark │  persist processed id (SQLite)
                   │  rate_limit.hit  │  record timestamp for user/global
                   └──────────────────┘
```

**Data flow summary**: Reddit item → gatekeeping → `TriggerContext` → claim extraction → evidence retrieval → LLM verdict → markdown render → reply (or dry-run log) → persist seen id + rate-limit tick.

---

## 3. Tech stack — exact package list & version constraints

- **Python**: `>=3.11,<3.14`. (PRAW 8 requires 3.10+; we pick 3.11 as floor for `tomllib`, better typing, and `StrEnum`.)
- **Build backend**: `hatchling` (via `hatch`), src layout. Simple, standard, no plugins needed.
- **Runtime dependencies** (pin with compatible-release / lower bounds; do not over-pin for an educational project):
  - `praw>=8.0,<9` — Reddit API wrapper. v8 is current (released 2026-06), 3.10+ only, ships `py.typed`.
  - `openai>=1.40,<2` — OpenAI-compatible client. Used against Ollama's `/v1` endpoint or any compatible API.
  - `ddgs>=9.0,<10` — DuckDuckGo/metasearch (the renamed `duckduckgo_search`; import is `from ddgs import DDGS`). Free, no key.
  - `pydantic>=2.7,<3` — data models + verdict schema/validation.
  - `pydantic-settings>=2.3,<3` — env/`.env` config loading.
  - `python-dotenv` is NOT a direct dep; `pydantic-settings` handles `.env`.
- **Dev dependencies** (optional group `dev`):
  - `pytest>=8,<9`
  - `pytest-mock>=3.12,<4`
  - `respx>=0.21` OR rely on `unittest.mock` — we use plain `unittest.mock` + `pytest-mock`, no HTTP recording lib (keeps it lean). `respx` is NOT included.
  - `ruff>=0.6` (lint + format)
  - `mypy>=1.10` (optional type checking; not required to pass CI for an educational project but configured)
- **External services**:
  - **Ollama** (local) serving an OpenAI-compatible API at `http://localhost:11434/v1`.
  - Default model: **`qwen3:4b-instruct`** (~3 GB Q4, ~2.6 GB disk, fits ≤4 GB VRAM/8 GB RAM, strong instruction-following and JSON, and the `-instruct` variant avoids Qwen3 "thinking" traces that pollute JSON output). Documented fallback for very low RAM: `llama3.2:3b`. Documented no-GPU cloud path: point env at OpenRouter/Groq with a `gpt-4o-mini`-class model.

> **Important LLM finding baked into the design**: Ollama's `/v1` OpenAI-compatible endpoint accepts `response_format` but its JSON-**schema** enforcement is unreliable (known upstream bugs: it honors `{"type":"json_object"}` JSON mode but frequently ignores a full `json_schema`). Therefore the plan uses **JSON mode** (`response_format={"type": "json_object"}`) + a schema embedded in the prompt + **robust parse-and-retry with fallback extraction**, rather than trusting server-side schema validation. This works identically against Ollama and hosted OpenAI-compatible APIs.

---

## 4. Configuration spec (env vars)

Config is loaded by `pydantic-settings.BaseSettings` in `config.py`. Source precedence: real environment variables > `.env` file > defaults. All names are UPPER_SNAKE. `.env` is git-ignored; `.env.example` is committed.

| Env var | Type | Default | Required | Notes |
|---|---|---|---|---|
| `REDDIT_CLIENT_ID` | str | — | yes | Reddit app client id. |
| `REDDIT_CLIENT_SECRET` | str | — | yes | Reddit app secret. |
| `REDDIT_USERNAME` | str | — | yes | Bot account username (no leading `u/`). |
| `REDDIT_PASSWORD` | str | — | yes | Bot account password. |
| `REDDIT_USER_AGENT` | str | `fact-check-bot/1.0 (by u/<REDDIT_USERNAME>)` | no | Built at runtime if unset; see config validator. |
| `BOT_TRIGGER` | str | `!factcheck` | no | Case-insensitive trigger token. |
| `MONITORED_SUBREDDITS` | str (csv) | `testingground4bots` | no | Comma/plus separated. Parsed into a list. Default is a safe test sub. |
| `ENABLE_COMMENT_STREAM` | bool | `true` | no | Watch comment streams on `MONITORED_SUBREDDITS`. |
| `ENABLE_INBOX_MENTIONS` | bool | `true` | no | Watch inbox for username mentions. |
| `LLM_BASE_URL` | str | `http://localhost:11434/v1` | no | Any OpenAI-compatible base URL. |
| `LLM_API_KEY` | str | `ollama` | no | Ignored by Ollama; required non-empty by the client. Put your real key here for hosted APIs. |
| `LLM_MODEL` | str | `qwen3:4b-instruct` | no | Model name/slug. |
| `LLM_TEMPERATURE` | float | `0.0` | no | Deterministic for verdicts. |
| `LLM_MAX_TOKENS` | int | `700` | no | Cap on completion tokens. |
| `LLM_TIMEOUT_SECONDS` | float | `60.0` | no | Per-request timeout. |
| `LLM_MAX_RETRIES` | int | `2` | no | JSON parse/validation retries (see llm.py). |
| `SEARCH_MAX_RESULTS` | int | `5` | no | Results requested from ddgs. |
| `SEARCH_SNIPPET_CHARS` | int | `500` | no | Max chars kept per snippet body. |
| `SEARCH_REGION` | str | `us-en` | no | ddgs region. |
| `SEARCH_TIMELIMIT` | str \| None | `None` | no | ddgs timelimit: `d`/`w`/`m`/`y` or empty→None. |
| `SEARCH_TIMEOUT_SECONDS` | float | `15.0` | no | Soft timeout guard for search step. |
| `MAX_CLAIM_CHARS` | int | `500` | no | Truncate claim fed to LLM/search. |
| `MAX_REPLY_CHARS` | int | `9500` | no | Hard cap below Reddit's 10k limit. |
| `RATE_LIMIT_PER_USER_PER_HOUR` | int | `3` | no | Max replies to one author per rolling hour. |
| `RATE_LIMIT_GLOBAL_PER_HOUR` | int | `30` | no | Max total replies per rolling hour. |
| `SEEN_DB_PATH` | str (path) | `data/seen.sqlite3` | no | SQLite file for dedupe + rate-limit state. |
| `DRY_RUN` | bool | `true` | no | If true, log the reply instead of posting. **Defaults to true so a fresh clone never posts by accident.** |
| `IGNORE_BOTS` | bool | `true` | no | Skip authors whose name ends in `bot` / are known bots (see triggers). |
| `LOG_LEVEL` | str | `INFO` | no | `DEBUG`/`INFO`/`WARNING`/`ERROR`. |
| `LOG_JSON` | bool | `false` | no | If true, structured JSON logs; else human-readable. |
| `POLL_SLEEP_SECONDS` | float | `10.0` | no | Sleep between inbox polls / after stream errors. |

**Bool parsing**: pydantic-settings parses `true/false/1/0/yes/no` case-insensitively.

**CSV parsing**: `MONITORED_SUBREDDITS` accepts commas or `+`; a field validator splits on `[,+]`, strips, drops empties, lowercases.

---

## 5. Project layout & file-by-file spec

```
fact-check-bot/
├── pyproject.toml
├── README.md
├── .env.example
├── .gitignore
├── Dockerfile
├── docker-compose.yml
├── docs/
│   └── PLAN.md                 # this file
├── data/                       # gitignored (SQLite lives here at runtime)
│   └── .gitkeep
├── src/
│   └── factcheckbot/
│       ├── __init__.py
│       ├── __main__.py
│       ├── config.py
│       ├── logging_setup.py
│       ├── models.py
│       ├── prompts.py
│       ├── triggers.py
│       ├── search.py
│       ├── llm.py
│       ├── rendering.py
│       ├── seen_store.py
│       ├── rate_limit.py
│       ├── reddit_client.py
│       ├── pipeline.py
│       └── bot.py
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── fixtures.py
    ├── test_config.py
    ├── test_triggers.py
    ├── test_search.py
    ├── test_llm.py
    ├── test_rendering.py
    ├── test_seen_store.py
    ├── test_rate_limit.py
    └── test_pipeline.py
```

### 5.1 `pyproject.toml`

- `[build-system]`: `requires = ["hatchling"]`, `build-backend = "hatchling.build"`.
- `[project]`: name `fact-check-bot`, version `1.0.0`, `requires-python = ">=3.11,<3.14"`, description, readme = `README.md`, license `MIT`, authors placeholder.
- `[project.dependencies]`: the runtime list from §3.
- `[project.optional-dependencies]`: `dev = [pytest, pytest-mock, ruff, mypy]`.
- `[project.scripts]`: `fact-check-bot = "factcheckbot.__main__:main"`.
- `[tool.hatch.build.targets.wheel]`: `packages = ["src/factcheckbot"]`.
- `[tool.ruff]`: `line-length = 100`, `target-version = "py311"`, select `["E","F","I","UP","B"]`.
- `[tool.pytest.ini_options]`: `testpaths = ["tests"]`, `pythonpath = ["src"]`, `addopts = "-q"`.
- `[tool.mypy]`: `python_version = "3.11"`, `packages = ["factcheckbot"]`, `ignore_missing_imports = true` (praw/ddgs may lack stubs).

### 5.2 `src/factcheckbot/__init__.py`

- Module docstring (1 line). `__version__ = "1.0.0"`. No side effects.

### 5.3 `src/factcheckbot/__main__.py`

- `def main() -> int:` entrypoint.
  - Load `Settings()` (from `config`).
  - Call `logging_setup.configure(settings)`.
  - Construct dependencies: `SeenStore(settings.seen_db_path)`, `RateLimiter(...)`, `EvidenceSearcher(settings)`, `LlmClient(settings)`, build the reddit instance via `reddit_client.build_reddit(settings)`.
  - Instantiate `Bot(settings, reddit, searcher, llm, seen, limiter)`.
  - Register SIGINT/SIGTERM handlers that set a stop flag on the bot.
  - `bot.run()` wrapped in try/except: on `KeyboardInterrupt` log clean shutdown; on unexpected exception log and return non-zero.
  - Return `0` on clean exit.
- `if __name__ == "__main__": raise SystemExit(main())`.

### 5.4 `src/factcheckbot/config.py`

Purpose: typed settings via `pydantic-settings`.

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # reddit
    reddit_client_id: str
    reddit_client_secret: str
    reddit_username: str
    reddit_password: str
    reddit_user_agent: str | None = None

    # trigger / subs
    bot_trigger: str = "!factcheck"
    monitored_subreddits: list[str] = ["testingground4bots"]
    enable_comment_stream: bool = True
    enable_inbox_mentions: bool = True

    # llm
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = "ollama"
    llm_model: str = "qwen3:4b-instruct"
    llm_temperature: float = 0.0
    llm_max_tokens: int = 700
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 2

    # search
    search_max_results: int = 5
    search_snippet_chars: int = 500
    search_region: str = "us-en"
    search_timelimit: str | None = None
    search_timeout_seconds: float = 15.0

    # limits
    max_claim_chars: int = 500
    max_reply_chars: int = 9500
    rate_limit_per_user_per_hour: int = 3
    rate_limit_global_per_hour: int = 30

    # storage / behavior
    seen_db_path: str = "data/seen.sqlite3"
    dry_run: bool = True
    ignore_bots: bool = True
    log_level: str = "INFO"
    log_json: bool = False
    poll_sleep_seconds: float = 10.0
```

Behavior / validators:
- `@field_validator("monitored_subreddits", mode="before")`: if value is a `str`, split on `[,+]`, strip, lowercase, drop empties. Return list.
- `@field_validator("search_timelimit", mode="before")`: empty string / `"none"` → `None`.
- `@model_validator(mode="after")`: if `reddit_user_agent` is None, set it to `f"fact-check-bot/1.0 (by u/{self.reddit_username})"`.
- Edge cases: missing required reddit vars → pydantic raises `ValidationError` at startup (fail fast, clear message). `max_reply_chars` clamped to ≤ 10000 in the after-validator (hard safety).

### 5.5 `src/factcheckbot/logging_setup.py`

- `def configure(settings: Settings) -> None:`
  - Set root logger level from `settings.log_level`.
  - If `settings.log_json`: attach a handler with a `JsonFormatter` (custom minimal formatter emitting `{"ts","level","logger","msg", ...extras}`).
  - Else: `logging.Formatter("%(asctime)s %(levelname)-7s %(name)s | %(message)s")`.
  - Quiet noisy libs: set `logging.getLogger("praw").setLevel(WARNING)`, same for `prawcore`, `httpx`, `openai`, `ddgs`.
- `def get_logger(name: str) -> logging.Logger:` thin wrapper returning `logging.getLogger(name)`.
- Minimal `JsonFormatter(logging.Formatter)` with `format()` returning `json.dumps(...)`.

### 5.6 `src/factcheckbot/models.py`

Pydantic v2 models + enums. All pure data, no I/O.

```python
class Verdict(str, Enum):
    TRUE = "TRUE"
    MOSTLY_TRUE = "MOSTLY TRUE"
    MIXED = "MIXED"
    MOSTLY_FALSE = "MOSTLY FALSE"
    FALSE = "FALSE"
    UNVERIFIABLE = "UNVERIFIABLE"

class Evidence(BaseModel):
    index: int            # 1-based, matches what we show the LLM and the reply
    title: str
    url: str
    snippet: str          # truncated body

class FactCheckResult(BaseModel):
    verdict: Verdict
    confidence: float            # 0.0–1.0
    reasoning: str               # one paragraph
    cited_sources: list[int]     # 1-based indices into the Evidence list
    # validators:
    #  - confidence clamped to [0,1]
    #  - cited_sources: drop out-of-range / duplicate indices, keep order

class TriggerContext(BaseModel):
    item_id: str                 # praw fullname, e.g. "t1_abc" / "t4_xyz"
    author: str | None           # None if deleted
    inline_query: str            # text after the trigger token (may be "")
    permalink: str               # for logging
    source: Literal["comment_stream", "inbox_mention"]
    # the raw parent text is fetched lazily in the pipeline, not stored here
```

- `FactCheckResult` has `@field_validator("confidence")` clamping and `@field_validator("cited_sources")` sanitizing.
- Add `MAX_REASONING_CHARS = 1500` module constant; `reasoning` validator truncates to it (defense against runaway output before rendering).

### 5.7 `src/factcheckbot/prompts.py`

Holds the exact prompt strings + the JSON schema text. No logic beyond simple `.format()` helpers. Full text in §6. Exposes:
- `CLAIM_EXTRACTION_SYSTEM: str`
- `CLAIM_EXTRACTION_USER_TEMPLATE: str` (placeholders `{raw_text}`)
- `VERDICT_SYSTEM: str`
- `VERDICT_USER_TEMPLATE: str` (placeholders `{claim}`, `{evidence_block}`, `{schema}`)
- `VERDICT_JSON_SCHEMA: dict` (the JSON schema dict; also serialized to a string for embedding)
- `def build_evidence_block(evidence: list[Evidence]) -> str:` renders numbered evidence for the prompt (`[1] title — url\n<snippet>`), or `"(no evidence found)"` if empty.

### 5.8 `src/factcheckbot/triggers.py`

Pure functions — the most heavily unit-tested module.

- `def contains_trigger(body: str, trigger: str) -> bool:`
  - Case-insensitive substring match of `trigger` in `body`. Returns False for None/empty body.
- `def extract_inline_query(body: str, trigger: str) -> str:`
  - Find the trigger (case-insensitive) and return the remainder of that line/text after the trigger token, stripped. If trigger appears multiple times, use the first. If nothing after, return `""`.
  - Implementation: lowercase-locate index, slice original (preserve original casing of the query), split off leading whitespace/punctuation `:` and quotes.
  - Truncate to `max_claim_chars` (caller passes it; default via param).
- `def is_ignorable_author(author: str | None, bot_username: str, ignore_bots: bool) -> bool:`
  - True if `author is None` (deleted), or `author.lower() == bot_username.lower()` (self), or (`ignore_bots` and `author.lower().endswith("bot")` or author in a small hardcoded `KNOWN_BOTS` frozenset like `{"automoderator", "b0trank", "sneakpeekbot"}`).
- `def normalize_claim(text: str, max_chars: int) -> str:`
  - Collapse whitespace, strip surrounding quotes/backticks, strip markdown quote `>` prefixes, truncate to `max_chars` on a word boundary. Returns `""` if the cleaned result is empty.

Edge cases covered by tests: trigger mid-sentence, trigger with no query, multi-line comment, trigger inside a quoted block, uppercase `!FACTCHECK`, query longer than max, author None.

### 5.9 `src/factcheckbot/search.py`

Thin I/O edge around `ddgs`.

```python
class EvidenceSearcher:
    def __init__(self, settings: Settings, ddgs_factory: Callable[[], DDGS] = DDGS): ...
    def search(self, query: str) -> list[Evidence]: ...
```

- `search`:
  - If `query` is empty → return `[]`.
  - Call `self._ddgs_factory().text(query, region=settings.search_region, safesearch="moderate", timelimit=settings.search_timelimit, max_results=settings.search_max_results, backend="auto")` inside a `try/except Exception`.
  - On any exception (`ddgs.exceptions.*`, network, ratelimit) → log a warning and return `[]` (pipeline degrades gracefully to "no evidence").
  - Map each raw dict (`{"title","href","body"}`) into `Evidence(index=i (1-based), title=..., url=href, snippet=truncate(body, settings.search_snippet_chars))`.
  - Truncation helper `_truncate(text, n)`: cut to n chars on a word boundary, append `…` if cut. Handle missing/None keys defensively (default to "").
  - Deduplicate by URL, preserving order, before indexing.
- `ddgs_factory` param exists purely so tests inject a fake DDGS returning canned dicts. Default is the real `DDGS` class.

### 5.10 `src/factcheckbot/llm.py`

I/O edge around the OpenAI-compatible client + the JSON-robustness logic (the interesting part).

```python
class LlmError(Exception): ...

class LlmClient:
    def __init__(self, settings: Settings, client: OpenAI | None = None): ...
        # builds openai.OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key,
        #                      timeout=settings.llm_timeout_seconds) if client is None

    def extract_claim(self, raw_text: str) -> str: ...
    def fact_check(self, claim: str, evidence: list[Evidence]) -> FactCheckResult: ...

    # internal:
    def _chat(self, system: str, user: str, *, json_mode: bool) -> str: ...
```

- `_chat`:
  - Calls `client.chat.completions.create(model, messages=[system,user], temperature=settings.llm_temperature, max_tokens=settings.llm_max_tokens, response_format={"type":"json_object"} if json_mode else NOT_GIVEN)`.
  - Wrap in try/except for `openai.APIConnectionError`, `openai.APITimeoutError`, `openai.APIError` → raise `LlmError("LLM unavailable: ...")` (so the pipeline can post a friendly "couldn't reach the model" note or skip; see error matrix).
  - Return `resp.choices[0].message.content or ""`.
- `extract_claim`:
  - Uses `CLAIM_EXTRACTION_*` prompts, `json_mode=True`. Expects `{"claim": "..."}`. Parse with `_loads_json_object`; on failure fall back to returning the raw stripped text (claim extraction is best-effort, never fatal).
  - Returns the extracted claim string (never raises for parse issues; only `LlmError` propagates on connection failure — caller decides).
- `fact_check`:
  - Builds messages from `VERDICT_SYSTEM` + `VERDICT_USER_TEMPLATE.format(claim=..., evidence_block=build_evidence_block(evidence), schema=json.dumps(VERDICT_JSON_SCHEMA))`.
  - Loop up to `settings.llm_max_retries + 1` times:
    1. `raw = self._chat(system, user, json_mode=True)`.
    2. `data = _extract_json_object(raw)` (see below).
    3. `return FactCheckResult.model_validate(data)`.
    4. On `json.JSONDecodeError` or `pydantic.ValidationError`: log debug with the raw text, append a corrective user message ("Your previous reply was not valid JSON matching the schema. Return ONLY the JSON object.") and retry.
  - If all attempts fail → return a safe default `FactCheckResult(verdict=UNVERIFIABLE, confidence=0.0, reasoning="The model did not return a parseable verdict.", cited_sources=[])`. **Never raises for parse failure** — degrade gracefully.
- Module-level helpers (pure, unit-tested):
  - `def _extract_json_object(text: str) -> dict:` — tolerant parser:
    1. Try `json.loads(text)`.
    2. Strip common wrappers: ```` ```json ... ``` ````/```` ``` ```` fences; leading/trailing prose.
    3. Regex/scan for the first balanced `{...}` block and `json.loads` that.
    4. Raise `json.JSONDecodeError` if nothing parses. (This is why small-model quirks like thinking preambles or fenced blocks are handled without server-side schema support.)

### 5.11 `src/factcheckbot/rendering.py`

Pure functions — reply construction. See §7 for exact template.

- `def render_reply(claim: str, result: FactCheckResult, evidence: list[Evidence], settings: Settings) -> str:`
  - Builds header (verdict + emoji), confidence line, reasoning paragraph, numbered sources list (only the cited ones; if `cited_sources` empty, list all evidence up to a cap of 5), disclaimer, footer.
  - `VERDICT_EMOJI` map: TRUE ✅, MOSTLY TRUE ✅, MIXED ⚖️, MOSTLY FALSE ❌, FALSE ❌, UNVERIFIABLE ❓ (emoji optional; keep ASCII-safe fallback in a constant so it can be disabled — but include them, harmless in reddit markdown).
  - Enforce `settings.max_reply_chars`: if the assembled reply exceeds it, truncate the reasoning first, then the source list, always preserving the disclaimer + footer. Helper `_fit_to_limit`.
  - `def render_no_claim_reply(settings) -> str:` short message for empty-claim case (mirrors original's EMPTY_QUERY_ERROR) + footer.
  - `def _sources_block(result, evidence) -> str:` renders `1. [title](url)` lines.
  - Footer includes the trigger usage and the AI/educational disclaimer.

### 5.12 `src/factcheckbot/seen_store.py`

SQLite-backed dedupe (chosen over JSONL: atomic, no full-file rewrites, survives restarts, trivially also holds rate-limit rows). Single file, `check_same_thread=False` guard since single-threaded anyway.

```python
class SeenStore:
    def __init__(self, path: str): ...        # mkdir parents, connect, _init_schema
    def _init_schema(self): ...               # CREATE TABLE IF NOT EXISTS seen(id TEXT PRIMARY KEY, ts REAL)
    def is_seen(self, item_id: str) -> bool: ...
    def mark_seen(self, item_id: str) -> None: ...   # INSERT OR IGNORE
    def close(self) -> None: ...
```

- `item_id` = praw fullname (globally unique across comments/messages).
- Uses `INSERT OR IGNORE` so double-mark is safe.
- WAL mode pragma for durability (`PRAGMA journal_mode=WAL`).
- Works with an in-memory DB (`":memory:"`) for tests.

### 5.13 `src/factcheckbot/rate_limit.py`

Rolling-window limiter persisted in the same SQLite DB (separate table) so limits survive restarts.

```python
class RateLimiter:
    def __init__(self, store: SeenStore, per_user_per_hour: int, global_per_hour: int, now: Callable[[], float] = time.time): ...
    def allow(self, author: str) -> tuple[bool, str]: ...   # (allowed, reason_if_blocked)
    def record(self, author: str) -> None: ...
    def _prune(self, cutoff: float) -> None: ...
```

- Table `replies(author TEXT, ts REAL)` created via the store's connection.
- `allow`: prune rows older than 1h; count global rows and this-author rows in window; return `(False, "global rate limit")` / `(False, "per-user rate limit")` / `(True, "")`.
- `record`: insert `(author, now())`.
- `now` injectable for deterministic tests.
- Shares the SQLite connection from `SeenStore` (pass the store in) to avoid a second file/handle. `SeenStore` exposes its `connection` or a helper `execute`.

### 5.14 `src/factcheckbot/reddit_client.py`

I/O edge around PRAW.

- `def build_reddit(settings: Settings) -> praw.Reddit:` constructs `praw.Reddit(client_id=..., client_secret=..., username=..., password=..., user_agent=settings.reddit_user_agent)`. Sets `reddit.validate_on_submit = True`.
- `def iter_comment_stream(reddit, subreddits: list[str], pause_after=None):` yields comments from `reddit.subreddit("+".join(subreddits)).stream.comments(skip_existing=True, pause_after=-1)` — `pause_after=-1` yields `None` when caught up so the main loop can also service the inbox. The generator filters out `None`? No: it yields them; the bot loop handles `None`.
- `def iter_inbox_mentions(reddit):` returns `reddit.inbox.mentions(limit=...)` (polled each loop) — actually the bot calls `reddit.inbox.unread(...)` filtered to `Mention`/`Comment` and marks read. Spec: `def fetch_unread_mentions(reddit, limit=25) -> list[Message|Comment]` returning unread mentions; caller marks them read after processing.
- `def safe_reply(item, text: str, *, dry_run: bool, logger) -> bool:`
  - If `dry_run`: log the full reply text + target permalink, return True (treated as success for seen-marking).
  - Else: `try: item.reply(text); return True` catching `praw.exceptions.RedditAPIException` (inspect for RATELIMIT sub-errors → parse wait seconds, log, return False so it's retried later / not marked seen) and `prawcore.exceptions.*` (log, return False).
- `def mark_read(item) -> None:` wraps `item.mark_read()` for mention messages (guarded try/except).

Rationale for both stream + inbox: streaming all of r/politics is read-heavy; the default sub list is a tiny test sub, and inbox mentions are cheap and always relevant. Both are supported and independently toggleable.

### 5.15 `src/factcheckbot/pipeline.py`

Pure-ish orchestration; takes already-constructed collaborators (all mockable). No PRAW imports here except type hints (kept behind `TYPE_CHECKING`), so it's unit-testable without Reddit.

```python
@dataclass
class Pipeline:
    settings: Settings
    searcher: EvidenceSearcher
    llm: LlmClient

    def resolve_claim(self, ctx: TriggerContext, parent_text_getter: Callable[[], str | None]) -> str: ...
    def run(self, claim: str) -> tuple[FactCheckResult, list[Evidence]]: ...
```

- `resolve_claim`:
  - If `ctx.inline_query` non-empty after `normalize_claim` → return it.
  - Else call `parent_text_getter()` to fetch parent comment/post text (the bot passes a closure that reads `comment.parent().body` or submission title+selftext). If parent text present, run `llm.extract_claim(parent_text)` then `normalize_claim`. If still empty → return `""`.
  - **UX decision**: bare `!factcheck` fact-checks the parent comment/post. This mirrors natural Reddit usage ("someone said X, factcheck it").
- `run(claim)`:
  - `evidence = searcher.search(claim)`.
  - `result = llm.fact_check(claim, evidence)`.
  - return `(result, evidence)`.
- Wraps `llm` connection errors: if `LlmError` propagates, `run` re-raises it; the **bot** decides whether to skip (default) — we do NOT post "model down" spam to Reddit; instead log and leave the item unmarked so it retries on next run. (Documented in error matrix.)

### 5.16 `src/factcheckbot/bot.py`

The loop + wiring of gatekeeping. This is the only place PRAW objects, seen-store, rate-limiter, pipeline, and renderer meet.

```python
class Bot:
    def __init__(self, settings, reddit, searcher, llm, seen, limiter): 
        self.pipeline = Pipeline(settings, searcher, llm)
        self._stop = False
    def request_stop(self): self._stop = True
    def run(self) -> None: ...
    def _handle_item(self, item, source: str) -> None: ...
    def _process(self, ctx: TriggerContext, item) -> None: ...
```

- `run`:
  - Log startup banner (model, base_url, subs, dry_run, enabled sources).
  - Main loop while not `_stop`:
    - If `enable_comment_stream`: iterate the comment stream generator (with `pause_after=-1` so it returns control). For each non-None comment → `_handle_item(comment, "comment_stream")`.
    - If `enable_inbox_mentions`: fetch unread mentions → `_handle_item(item, "inbox_mention")` then `mark_read`.
    - Sleep `poll_sleep_seconds` when caught up.
    - Wrap the loop body in try/except for `prawcore.exceptions.RequestException`/`ServerError`/`ResponseException` and generic `Exception`: log, sleep `poll_sleep_seconds`, continue (never crash the process on transient errors).
  - On `_stop`, close `seen` store and return.
- `_handle_item` (gatekeeping):
  1. Build `item_id = item.fullname`. If `seen.is_seen(item_id)` → return.
  2. Determine `body` (comment.body, or message.body for mentions).
  3. If not `contains_trigger(body, settings.bot_trigger)` → mark seen (so we don't re-scan) and return. *(For inbox mentions, a mention without the trigger is still marked read/seen.)*
  4. `author = str(item.author) if item.author else None`. If `is_ignorable_author(author, settings.reddit_username, settings.ignore_bots)` → mark seen, return.
  5. Rate limit: `allowed, reason = limiter.allow(author)`. If not allowed → log, mark seen (don't reply), return. (Marking seen prevents re-eval; the user can trigger again next hour on a new comment.)
  6. Build `TriggerContext` and call `_process`.
- `_process`:
  1. `claim = pipeline.resolve_claim(ctx, parent_text_getter=lambda: self._parent_text(item))`.
  2. If `claim == ""` → `reply = render_no_claim_reply(settings)`; post via `safe_reply`; on success `seen.mark_seen` + `limiter.record`; return.
  3. `try: result, evidence = pipeline.run(claim)` — on `LlmError`: log warning "LLM unavailable, leaving item for retry", **do not mark seen**, return.
  4. `reply = render_reply(claim, result, evidence, settings)`.
  5. `ok = safe_reply(item, reply, dry_run=settings.dry_run, logger=...)`.
  6. If `ok`: `seen.mark_seen(item_id)`; `limiter.record(author)`. Else: log (will retry later). 
- `_parent_text(item)`: for a comment, return parent comment `.body` or, if parent is a submission, `title + "\n\n" + selftext`. For an inbox mention (a `Comment`), same logic. Guarded try/except returning None.

Threading: single-threaded. Signals handled in `__main__` by calling `bot.request_stop()`.

---

## 6. LLM prompts (actual text)

### 6.1 Claim extraction

Used only when the user typed a bare `!factcheck` and we must derive the claim from parent text.

`CLAIM_EXTRACTION_SYSTEM`:
```
You extract a single, concise, checkable factual claim from a piece of text.
Return only strict JSON. Do not add commentary, markdown, or code fences.
```

`CLAIM_EXTRACTION_USER_TEMPLATE`:
```
From the text below, identify the single most important factual claim a reader
might want fact-checked. Rewrite it as one clear, self-contained sentence with no
pronouns that depend on missing context. If there is no checkable factual claim,
use an empty string.

Respond with JSON exactly in this form:
{{"claim": "<one sentence or empty string>"}}

TEXT:
"""
{raw_text}
"""
```
(Note the doubled braces `{{ }}` because this string is consumed with `str.format`.)

### 6.2 Verdict

`VERDICT_SYSTEM`:
```
You are a careful, neutral fact-checking assistant for an educational Reddit bot.
You judge a single claim using ONLY the numbered evidence provided. You never use
outside knowledge as if it were established fact, and you never invent sources.
If the evidence is thin, conflicting, or absent, prefer "MIXED" or "UNVERIFIABLE"
and say so. Keep reasoning to one short paragraph. Output strict JSON only, with no
markdown, no code fences, and no text before or after the JSON object.
```

`VERDICT_USER_TEMPLATE`:
```
CLAIM:
"{claim}"

EVIDENCE (numbered; may be empty):
{evidence_block}

Decide a verdict about the CLAIM based on the EVIDENCE.

Rules:
- "verdict" must be exactly one of:
  "TRUE", "MOSTLY TRUE", "MIXED", "MOSTLY FALSE", "FALSE", "UNVERIFIABLE".
- Use "UNVERIFIABLE" if the evidence does not let you judge the claim.
- "confidence" is a number from 0 to 1 reflecting how sure you are.
- "reasoning" is ONE short paragraph (max ~4 sentences), plain text.
- "cited_sources" is a list of the evidence numbers you actually relied on
  (e.g. [1, 3]); use [] if you used none.

Respond with a single JSON object matching this schema:
{schema}
```

`VERDICT_JSON_SCHEMA` (dict, also embedded as a string via `json.dumps`):
```json
{
  "type": "object",
  "properties": {
    "verdict": {
      "type": "string",
      "enum": ["TRUE", "MOSTLY TRUE", "MIXED", "MOSTLY FALSE", "FALSE", "UNVERIFIABLE"]
    },
    "confidence": { "type": "number", "minimum": 0, "maximum": 1 },
    "reasoning": { "type": "string" },
    "cited_sources": { "type": "array", "items": { "type": "integer" } }
  },
  "required": ["verdict", "confidence", "reasoning", "cited_sources"]
}
```

`build_evidence_block(evidence)` output format (one entry per result):
```
[1] <title> — <url>
<snippet>

[2] <title> — <url>
<snippet>
```
If `evidence` is empty, return the literal string `(no evidence found)`.

> The schema is sent both as `response_format={"type":"json_object"}` (JSON mode, reliably supported by Ollama) AND embedded in the prompt text, because Ollama's `/v1` endpoint does not reliably enforce a full JSON *schema*. Validation + retry in `llm.fact_check` is what actually guarantees a well-formed `FactCheckResult`.

---

## 7. Reply template (actual markdown)

`render_reply` produces (placeholders in `<>`):

```
**Fact check: <VERDICT_EMOJI> <VERDICT>**  (confidence: <NN>%)

> <CLAIM>

<REASONING_PARAGRAPH>

**Sources**
1. [<title 1>](<url 1>)
2. [<title 2>](<url 2>)
3. [<title 3>](<url 3>)

---
^(🤖 I'm an experimental, AI-powered bot. This is an automated, LLM-generated assessment based on a quick web search, NOT authoritative fact-checking. Verify important claims yourself.)

^(Usage: reply to any comment with `!factcheck <claim>`, or just `!factcheck` to check the comment you're replying to.)
```

Rules:
- `<NN>%` = `round(confidence * 100)`.
- Sources list: cited sources first (in `cited_sources` order); if empty, list up to 5 of the retrieved evidence. If no evidence at all, replace the whole Sources block with `*No web sources were found for this claim.*`.
- The `> <CLAIM>` blockquote shows the claim actually checked (helpful when derived from parent text).
- The `^( ... )` superscript syntax renders as small text on Reddit — used for disclaimer + footer.
- Everything is trimmed to `max_reply_chars` by `_fit_to_limit`, which shortens reasoning then sources but always keeps the header, disclaimer, and footer.

`render_no_claim_reply` output:
```
I couldn't find a claim to check. Reply with `!factcheck <claim>`, or use just
`!factcheck` as a reply to the comment or post you want checked.

---
^(🤖 I'm an experimental, AI-powered bot, not an authoritative fact-checker.)
```

---

## 8. Error handling & rate-limiting matrix

| Situation | Detection | Behavior |
|---|---|---|
| Item already processed | `seen.is_seen(id)` | Skip silently (debug log). |
| Comment/message has no trigger | `contains_trigger` false | Mark seen; skip. |
| Author is self | `is_ignorable_author` (name == bot) | Mark seen; skip. Prevents self-loops. |
| Author is a bot | name ends `bot` or in `KNOWN_BOTS`, `ignore_bots=true` | Mark seen; skip. |
| Author deleted | `item.author is None` | Mark seen; skip. |
| Per-user rate limit hit | `limiter.allow` → per-user | Log info; mark seen; no reply. |
| Global rate limit hit | `limiter.allow` → global | Log warning; mark seen; no reply. |
| Empty/unresolvable claim | `resolve_claim` returns "" | Post `render_no_claim_reply`; mark seen; record. |
| Web search fails / rate-limited | exception in `EvidenceSearcher.search` | Log warning; return `[]`; pipeline continues with no evidence (LLM likely returns UNVERIFIABLE). |
| LLM unreachable / timeout | `openai.APIConnectionError/APITimeoutError/APIError` → `LlmError` | Log warning; **do NOT mark seen**; skip so it retries next cycle. No Reddit reply. |
| LLM returns non-JSON / bad schema | JSONDecodeError / ValidationError | Retry up to `LLM_MAX_RETRIES`; if still bad, return `UNVERIFIABLE` default result and reply normally. |
| Reply exceeds 10k chars | length check in `_fit_to_limit` | Truncate reasoning then sources; keep disclaimer/footer. |
| Reddit API RATELIMIT | `praw RedditAPIException` w/ RATELIMIT | Parse wait seconds if present; log; return False from `safe_reply`; item NOT marked seen (retried later). |
| Reddit transient/server error | `prawcore RequestException/ServerError/ResponseException` | Log; sleep `poll_sleep_seconds`; continue loop. |
| Comment stream yields None (caught up) | `pause_after=-1` | Service inbox, then sleep, then continue. |
| SIGINT / SIGTERM | signal handler | `bot.request_stop()`; finish current item; close store; exit 0. |
| Dry-run mode | `settings.dry_run` | `safe_reply` logs full reply instead of posting, returns True (marks seen + records so behavior mirrors production). |

Rate limiting is a persisted rolling 1-hour window in SQLite (`replies` table): per-user default 3/hr, global default 30/hr. Search itself is naturally paced by the poll loop; if `ddgs` raises `RatelimitException`, we just return no evidence.

---

## 9. Test plan (pytest; all network/LLM/Reddit mocked)

All tests run offline. `conftest.py` provides a `settings` fixture (a `Settings` built with dummy reddit creds + `dry_run=True` + in-memory-ish paths) and helpers. `fixtures.py` holds canned ddgs results, canned LLM JSON strings, and a `FakeComment`/`FakeMessage`/`FakeReddit` set of lightweight stand-ins.

- **`test_config.py`**
  - Loads settings from a monkeypatched env; required-var missing raises `ValidationError`.
  - CSV parsing of `MONITORED_SUBREDDITS` (`"a,b+c"` → `["a","b","c"]`, lowercased).
  - `reddit_user_agent` auto-built from username when unset.
  - `search_timelimit` empty/"none" → None. `max_reply_chars` clamp to ≤10000.

- **`test_triggers.py`**
  - `contains_trigger`: case-insensitive, substring, empty/None body.
  - `extract_inline_query`: text after trigger, empty when nothing follows, first-of-multiple, preserves query casing, strips leading `:`/quotes, truncates to max.
  - `is_ignorable_author`: None, self (case-insensitive), `*bot` suffix, KNOWN_BOTS, and a normal human returns False; `ignore_bots=false` disables bot filtering.
  - `normalize_claim`: whitespace collapse, quote/`>` stripping, word-boundary truncation, empty result → "".

- **`test_search.py`**
  - With a fake DDGS returning 3 dicts → 3 `Evidence`, 1-based indices, snippets truncated to `search_snippet_chars`, URL dedupe.
  - Empty query → `[]` without calling DDGS.
  - DDGS raising an exception → `[]` (graceful), warning logged.
  - Missing `body`/`title` keys handled (default "").

- **`test_llm.py`**
  - `_extract_json_object`: plain JSON; JSON wrapped in ```` ```json ``` ```` fences; JSON with leading prose / thinking preamble; first balanced object among trailing junk; unparseable → raises.
  - `fact_check` happy path: fake OpenAI client returns valid JSON → correct `FactCheckResult`; `cited_sources` out-of-range dropped; confidence clamped.
  - `fact_check` retry: first call returns garbage, second returns valid → succeeds; assert 2 calls made.
  - `fact_check` exhausted retries → returns `UNVERIFIABLE` default, never raises.
  - `_chat` connection error → `LlmError` raised (for connection path); `fact_check` surfaces `LlmError` only from connection errors, not parse errors.
  - `extract_claim`: valid `{"claim": "..."}` parsed; garbage → falls back to raw text.

- **`test_rendering.py`**
  - `render_reply` includes verdict, emoji, `confidence %`, blockquoted claim, numbered cited sources only, disclaimer, footer.
  - No evidence → "No web sources were found" line.
  - `cited_sources` empty → lists retrieved evidence (≤5).
  - Over-limit reasoning → output ≤ `max_reply_chars`, disclaimer + footer still present.
  - `render_no_claim_reply` contains usage instructions.

- **`test_seen_store.py`**
  - Fresh store: `is_seen` False → `mark_seen` → True. Duplicate `mark_seen` is safe. Persists across re-open of same temp file path (use `tmp_path`).

- **`test_rate_limit.py`**
  - Per-user limit: after N `record`, `allow` returns False with per-user reason; a different user still allowed.
  - Global limit blocks even a fresh user.
  - Window rolls: with injected `now`, records older than 1h are pruned and allow again.

- **`test_pipeline.py`**
  - `resolve_claim` with inline query → normalized inline query, no parent fetch, no LLM call.
  - `resolve_claim` bare trigger → calls `parent_text_getter`, runs `extract_claim`, returns normalized claim.
  - `resolve_claim` bare trigger with no parent text → "".
  - `run`: wires searcher + llm (both fakes) → returns `(FactCheckResult, evidence)`.
  - `run` propagates `LlmError` from a connection failure.
  - (Optional light integration) a `Bot._handle_item` test using `FakeComment` + fakes verifying: seen-skip, self-skip, bot-skip, rate-limit-skip, and a happy path that marks seen + records in dry-run.

Target: fast (<2s), zero network, deterministic.

---

## 10. Runbook

### 10.1 Prerequisites
- Python 3.11+.
- [uv](https://docs.astral.sh/uv/) recommended (pip works too).
- Ollama installed and running for the local path.

### 10.2 Setup with uv (recommended)

    git clone <this repo> && cd fact-check-bot
    uv venv
    uv pip install -e ".[dev]"
    cp .env.example .env
    # edit .env with your Reddit app creds

Setup with pip:

    python -m venv .venv && source .venv/bin/activate
    pip install -e ".[dev]"
    cp .env.example .env

### 10.3 Pull the local model

    ollama serve            # if not already running as a service
    ollama pull qwen3:4b-instruct
    # low-RAM alternative: ollama pull llama3.2:3b  (then set LLM_MODEL=llama3.2:3b)

Verify the OpenAI-compatible endpoint:

    curl http://localhost:11434/v1/chat/completions -H "Content-Type: application/json" -d '{"model":"qwen3:4b-instruct","messages":[{"role":"user","content":"say hi as json {\"hi\":true}"}],"response_format":{"type":"json_object"}}'

### 10.4 Register a Reddit app
1. Log in as the **bot account**.
2. Go to https://www.reddit.com/prefs/apps → "create another app…".
3. Choose type **script**. Set redirect uri to `http://localhost:8080`.
4. Copy the client id (under the app name) and secret into `.env` as `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET`. Set `REDDIT_USERNAME` / `REDDIT_PASSWORD`.

### 10.5 Run in dry-run (default, safe)

    fact-check-bot
    # or: python -m factcheckbot

`DRY_RUN=true` by default: it logs the reply it *would* post. Test by making a comment containing `!factcheck the earth is flat` in r/testingground4bots and watching the logs.

### 10.6 Run tests / lint

    pytest
    ruff check .
    ruff format --check .
    mypy src        # optional

### 10.7 Run for real

    # in .env set:
    #   DRY_RUN=false
    #   MONITORED_SUBREDDITS=testingground4bots   (start small!)
    fact-check-bot

### 10.8 Docker (optional, included)

`docker-compose.yml` defines two services: `ollama` (image `ollama/ollama`, volume for models, port 11434) and `bot` (built from `Dockerfile`, depends_on ollama, `LLM_BASE_URL=http://ollama:11434/v1`, env from `.env`). First run must pull the model into the ollama container:

    docker compose up -d ollama
    docker compose exec ollama ollama pull qwen3:4b-instruct
    docker compose up bot          # or: docker compose up --build

`Dockerfile`: `python:3.12-slim`, install `uv`, copy project, `uv pip install --system -e .`, non-root user, `CMD ["fact-check-bot"]`. The `data/` dir is a named volume so `seen.sqlite3` persists across restarts.

Docker is included because it makes the Ollama + bot wiring one command, which is valuable for an educational demo, but it stays intentionally minimal (no orchestration beyond compose).

---

## 11. Out of scope / future work
- Persisting/serving fact-check history or a web dashboard.
- Multiple concurrent workers, queues, or horizontal scaling.
- Fetching and reading full article text (`ddgs.extract`) for deeper evidence — current design uses search snippets only to stay within a small model's context.
- Embedding-based retrieval / vector store RAG.
- OAuth "refresh token" flow (we use script-app password auth for simplicity).
- Vote/feedback loop, moderator allow/deny lists, per-subreddit config.
- Caching identical claims to avoid recomputation.
- Multi-language claims (prompts are English-only).

---

## Appendix A — key file `.env.example`

```
# --- Reddit (required) ---
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
REDDIT_USERNAME=
REDDIT_PASSWORD=
# REDDIT_USER_AGENT=fact-check-bot/1.0 (by u/yourbot)

# --- Trigger / subs ---
BOT_TRIGGER=!factcheck
MONITORED_SUBREDDITS=testingground4bots
ENABLE_COMMENT_STREAM=true
ENABLE_INBOX_MENTIONS=true

# --- LLM (OpenAI-compatible; defaults to local Ollama) ---
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
LLM_MODEL=qwen3:4b-instruct
LLM_TEMPERATURE=0.0
LLM_MAX_TOKENS=700
LLM_TIMEOUT_SECONDS=60
LLM_MAX_RETRIES=2

# --- Search ---
SEARCH_MAX_RESULTS=5
SEARCH_SNIPPET_CHARS=500
SEARCH_REGION=us-en
SEARCH_TIMELIMIT=

# --- Limits / behavior ---
MAX_CLAIM_CHARS=500
MAX_REPLY_CHARS=9500
RATE_LIMIT_PER_USER_PER_HOUR=3
RATE_LIMIT_GLOBAL_PER_HOUR=30
SEEN_DB_PATH=data/seen.sqlite3
DRY_RUN=true
IGNORE_BOTS=true
LOG_LEVEL=INFO
LOG_JSON=false
POLL_SLEEP_SECONDS=10
```

## Appendix B — `.gitignore` essentials
```
.venv/
__pycache__/
*.pyc
.env
data/*.sqlite3*
.pytest_cache/
.mypy_cache/
.ruff_cache/
dist/
build/
```
