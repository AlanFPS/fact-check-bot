# fact-check-bot Devvit port

This is the Reddit Developer Platform version of the fact-check bot. It runs live on Reddit through Devvit, where the old self-service Reddit API/PRAW path can no longer be used.

The core behavior matches the Python bot: `!factcheck` triggers claim extraction, Google Fact Check Tools runs first when configured, and the fallback path uses a hosted OpenAI-compatible LLM. Unlike the Python bot, this version uses Redis instead of SQLite, runs per subreddit install, and uses a hosted LLM by default because local Ollama is not reachable from Devvit.

## Local setup

    npm install
    npm run typecheck
    npm run build
    npm test

## Settings

Set secret app settings after login and at least one install:

    devvit settings set llmApiKey
    devvit settings set googleFactCheckApiKey
    devvit settings set searchApiKey

`llmApiKey` is required. `googleFactCheckApiKey` enables the published fact-check tier. `searchApiKey` enables Tavily evidence search for the LLM fallback; without it, the fallback is LLM-only.

Non-secret settings are configured per install: `llmBaseUrl`, `llmModel`, `botTrigger`, `dryRun`, `ignoreBots`, `rateLimitPerUserPerHour`, `rateLimitGlobalPerHour`, and `enableVerdictCache`.

## Live runbook

    npm i -g devvit
    devvit login
    devvit whoami
    devvit playtest r/your_test_subreddit

In a second terminal, set the secrets above. Test first with `dryRun=true`, then set `dryRun=false` in the subreddit app settings when you want real replies.

Before production, submit for review:

    devvit publish

The app needs these external domains approved:

- `openrouter.ai`
- `factchecktools.googleapis.com`
- `api.tavily.com`

`openrouter.ai` is required for the default LLM path. Google and Tavily are optional at runtime, but they are listed so production review can approve them ahead of time.
