# Web search fix: provider-native first, honest failures — 2026-10-02

## Why

The 0.1.49 paired bench found Arslan's zero-key search dead: DuckDuckGo's HTML endpoint answers
**202 with a "prove you are human" challenge**, which `DuckDuckGoHtmlProvider` parsed as "0 results".
Every user without a Tavily/SearXNG key had no search, and the model was told the web was empty.

## How mainstream agents do it (checked 2026-10-02)

| Agent | Default search | Without extra setup |
| --- | --- | --- |
| Claude Code | the model provider's server-side search | same key |
| Codex CLI | OpenAI hosted `web_search` (cached by default, live opt-in) | same key |
| DeepSeek Harness | **DeepSeek native search**: `web_search_20250305` on `https://api.deepseek.com/anthropic/v1/messages`, results from `web_search_tool_result` blocks only; one model turn per search | same DeepSeek key |
| Hermes | configured vendor (Firecrawl, Exa, Parallel, Tavily, Brave, Perplexity, SearXNG, ddgs…) | anonymous free tiers (Exa, Parallel MCP) strictly last; every failure names the key to set |
| OpenClaw | 15 providers, keyed ones auto-detected first | keyless ones (DuckDuckGo, Parallel Free, SearXNG) never win auto-detection |

Sources: DeepSeek Harness `@deepseek-ai/dsh-web-search-deepseek` README and source; Hermes
`tools/web_tools.py`, `plugins/web/keyless_mcp.py`; OpenClaw docs (docs.openclaw.ai/tools/web);
Codex docs (developers.openai.com/codex/config-basic).

## What Arslan does now

- **Automatic order** when the user made no deliberate choice (stored default `duckduckgo` or empty):
  1. the chat provider's own search — DeepSeek native when the primary chat model is a DeepSeek
     official model (same endpoint and key as chat; the query goes to the party the conversation
     already goes to; one deepseek-v4-flash turn, counted against the work budget like any model call);
  2. the DuckDuckGo scrape, best-effort, last.
- **A deliberate choice is respected exactly**: Tavily or SearXNG never fall back (SearXNG users
  self-host so their queries stay on their network).
- **Honest failures**: a challenge page raises `SearchBlocked`; when every provider fails the model
  gets `code: search_blocked|search_failed` with each provider's reason, "This is not 'no results':
  nothing was searched", and how to fix it. A fallback that succeeds carries `fallback_from`.
- The native search call lives in the model layer (`arslan/llm/deepseek_search.py`); arbitrary web
  destinations stay on `net_pin`.

## Not yet done

- Other providers' native search (OpenAI `web_search`, Anthropic `web_search`, Gemini grounding).
- Hermes-style keyless free tiers (Exa / Parallel MCP) as a non-DeepSeek fallback.
- Settings UI: show "Automatic (uses your model's built-in search)" instead of "duckduckgo".
- Live verification against DeepSeek (needs a tiny paid call; all tests here use recorded shapes).
