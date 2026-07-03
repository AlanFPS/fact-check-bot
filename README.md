# fact-check-bot

A small Reddit bot that replies to `!factcheck` requests with published fact-checks or an AI-generated assessment. It is local/LLM-backed by default, with an optional Google Fact Check Tools API first tier that takes priority when a key is configured and falls back to web search plus LLM.

## How It Works

The bot watches configured subreddits and inbox mentions for `!factcheck <claim>`. For each request it extracts a claim, searches the web with `ddgs`, asks an LLM for a structured JSON verdict, and renders a Reddit markdown reply with cited sources and a disclaimer.

Bare `!factcheck` checks the parent comment or post. `DRY_RUN=true` by default, so a fresh setup logs replies instead of posting them.

## Setup

Use Python 3.11 through 3.14.

With `uv`:

    uv venv
    uv pip install -e ".[dev]"
    cp .env.example .env

With pip:

    python -m venv .venv
    source .venv/bin/activate
    pip install -e ".[dev]"
    cp .env.example .env

Pull the default local model:

    ollama serve
    ollama pull qwen3:14b

`qwen3:14b` is the default and the recommended sweet spot on Apple Silicon with about 24 GB unified memory.

Low-RAM alternatives:

    ollama pull qwen3:4b-instruct
    ollama pull llama3.2:3b

Then set `LLM_MODEL=qwen3:4b-instruct` or `LLM_MODEL=llama3.2:3b`. Hosted OpenAI-compatible endpoints only cost money if you configure `LLM_BASE_URL` and `LLM_API_KEY` for a paid provider.

Register a Reddit script app from the bot account at <https://www.reddit.com/prefs/apps>. Use `http://localhost:8080` as the redirect URI, then copy the client id, secret, username, and password into `.env`.

## Configuration

See `.env.example` for all settings.

| Variable | Purpose |
|---|---|
| `REDDIT_CLIENT_ID` | Reddit script app client id. |
| `REDDIT_CLIENT_SECRET` | Reddit script app secret. |
| `REDDIT_USERNAME` | Bot account username. |
| `REDDIT_PASSWORD` | Bot account password. |
| `MONITORED_SUBREDDITS` | Comma or plus separated subreddit list. |
| `SUBREDDIT_ALLOWLIST` | Optional reply allowlist. Set before going live in real subs. |
| `LLM_BASE_URL` | OpenAI-compatible endpoint, defaults to Ollama. |
| `LLM_MODEL` | Model name, defaults to `qwen3:14b`. |
| `GOOGLE_FACTCHECK_API_KEY` | Optional Google Fact Check Tools API key. |
| `DRY_RUN` | Logs replies instead of posting when true. |
| `SEEN_DB_PATH` | SQLite path for dedupe and rate limits. |

## Optional Google Fact Check Layer

If `GOOGLE_FACTCHECK_API_KEY` is set, the bot first checks Google's Fact Check Tools API for published fact-checks. When it finds matches, it replies with those publisher ratings and links directly, without calling the LLM. If the key is blank, Google has no hits, or the request fails, it falls back to the web-search plus LLM path.

To enable it, create a Google Cloud API key with the Fact Check Tools API enabled and set `GOOGLE_FACTCHECK_API_KEY` in `.env`. You can also tune `GOOGLE_FACTCHECK_MAX_CLAIMS`, `GOOGLE_FACTCHECK_LANGUAGE`, and `GOOGLE_FACTCHECK_TIMEOUT_SECONDS`.

## Optional Runtime Features

`ENABLE_VERDICT_CACHE=false` by default. When enabled, repeated normalized claims reuse a SQLite cached `PipelineOutcome` for `CACHE_TTL_SECONDS` seconds.

`ENABLE_FULLTEXT_EVIDENCE=false` by default. When enabled, the bot tries to enrich the top `EVIDENCE_FETCH_TOP_N` web results with `DDGS.extract`, capped by `EVIDENCE_FULLTEXT_CHARS`; if extraction is unavailable or fails, snippets are used.

Metrics are in-process counters logged every `METRICS_LOG_INTERVAL_SECONDS` seconds. Use `LOG_JSON=true` if you want structured metric fields.

The bot keeps lightweight local SQLite state for seen items, pending replies, rate limits, and optional cache entries by default.

Before posting outside a test subreddit, set `SUBREDDIT_ALLOWLIST` to the subs where the bot is allowed to reply. Inbox mentions bypass the allowlist because the user explicitly summoned the bot.

## Usage

Run:

    fact-check-bot

or:

    python -m factcheckbot

Trigger it with:

    !factcheck the earth is flat

or reply with:

    !factcheck

The second form checks the parent comment or post.

## Testing

    pytest
    ruff check .
    ruff format --check .

`mypy src` is configured but optional.

## Docker

Start Ollama, pull the model, then run the bot:

    docker compose up -d ollama
    docker compose exec ollama ollama pull qwen3:14b
    docker compose up --build bot

The compose file stores Ollama models and bot data in named volumes.

## Disclaimer

Replies are automated, LLM-generated assessments based on quick web search snippets. They are not authoritative fact checks. Verify important claims yourself.
