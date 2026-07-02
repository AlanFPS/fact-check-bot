# fact-check-bot

A small Reddit bot that replies to `!factcheck` requests with an AI-generated fact check. It is a rebuild of AlecM33/fact-check-bot, using a local or OpenAI-compatible LLM instead of Google's Fact Check Tools API, and is intended for education.

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
    ollama pull qwen3:4b-instruct

Low-RAM alternative:

    ollama pull llama3.2:3b

Then set `LLM_MODEL=llama3.2:3b`.

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
| `LLM_BASE_URL` | OpenAI-compatible endpoint, defaults to Ollama. |
| `LLM_MODEL` | Model name, defaults to `qwen3:4b-instruct`. |
| `DRY_RUN` | Logs replies instead of posting when true. |
| `SEEN_DB_PATH` | SQLite path for dedupe and rate limits. |

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
    docker compose exec ollama ollama pull qwen3:4b-instruct
    docker compose up --build bot

The compose file stores Ollama models and bot data in named volumes.

## Disclaimer

Replies are automated, LLM-generated assessments based on quick web search snippets. They are not authoritative fact checks. Verify important claims yourself.
