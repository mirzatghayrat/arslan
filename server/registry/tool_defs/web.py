"""Reading the web and drawing what was found. 0.1.63 K5: the research rules live with the web tools (they were appended
to every system text), and web_search says what a blocked search means (D5)."""
from server.registry.tool import Tool

WEB = (
    Tool("web_search",
         "Search the web for fresh/factual info; returns titles, urls and short snippets, not "
         "full data: use it to locate the best source, not to collect facts one query at a time. "
         "Do at most 1–2 broad searches, then web_extract the most authoritative page; don't run "
         "several similar searches or chase each data point with its own search, and answer as "
         "soon as you can. If it returns code search_blocked, nothing was searched: tell the user "
         "the search was blocked (not that the web has nothing) and that a fallback search "
         "service can be set in Settings, and never answer from memory as if you had searched.",
         {"type": "object",
          "properties": {"query": {"type": "string"}},
          "required": ["query"]}),
    Tool("web_extract",
         "Fetch a URL and return its main text (SSRF-guarded). Extracting the most authoritative "
         "page beats many snippet searches. If what you gathered is incomplete, answer only the "
         "supported part and name the specific unknowns; never invent missing detail or keep "
         "searching in circles.",
         {"type": "object",
          "properties": {"url": {"type": "string"},
                         "max_chars": {"type": "integer", "minimum": 1, "maximum": 40_000,
                                       "default": 12_000,
                                       "description": "Maximum extracted characters. Request a larger bounded read only when needed; check source.truncated."}},
          "required": ["url"]}),
    Tool("render_chart",
         "Render a line/bar/pie chart from structured data; the user sees the chart.",
         {"type": "object",
          "properties": {"type": {"type": "string"},
                         "x": {"type": "array"},
                         "series": {"type": "array"},
                         "title": {"type": "string"}}}),
)
