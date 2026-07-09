"""Hermes Desktop catalog → Arslan registry seed (spec §1.3).

Pure data. Tier principle: real-world side-effect risk — data/results in = safe;
state changed in the world (filesystem writes, sends, execution, physical
devices) = orchestrator. EXCLUDED (never registered): godmode, obliteratus,
hermes-agent, hermes-agent-skill-authoring.

2026-07 curation (open-source honesty pass): the catalog now ships ONLY entries
that are real — wired toolsets, wire-candidates we intend to wire, and skills
with an actual SKILL.md method body (plus the orchestrator-tier coding-delegation
skills, kept as transparent catalog entries per decision §9). Integration
placeholders and Hermes-bound/infeasible entries were removed; their keys are
retired from existing DBs by the seeder's retirement list (see seeder.py).
"""
from __future__ import annotations

# Each toolset dict: key, name, description, tier, status, optional backend_note,
# and tools: list of (key, description, tier, status) tuples.
TOOLSETS: list[dict] = [
    {
        "key": "web_search_scraping",
        "name": "Web Search & Scraping",
        "description": "web_search, web_extract — live web data in.",
        "tier": "safe",
        "status": "wired",
        "tools": [
            ("web_search", "Search the web; returns titles/urls/snippets.", "safe", "wired"),
            ("web_extract", "Fetch a URL and extract readable text.", "safe", "wired"),
        ],
    },
    # Wire-candidate: kept catalogued (assignable only once a tool is wired).
    {
        "key": "file_operations",
        "name": "File Operations",
        "description": "Read & search files (write/patch is orchestrator-tier).",
        "tier": "safe",
        "status": "registered",
        "tools": [
            ("read_file", "Read a file.", "safe", "registered"),
            ("search_files", "Search files.", "safe", "registered"),
            ("write_file", "Write a file.", "orchestrator", "registered"),
            ("patch", "Patch a file.", "orchestrator", "registered"),
        ],
    },
    # Wire-candidate: kept catalogued (assignable only once a tool is wired).
    {
        "key": "session_search",
        "name": "Session Search",
        "description": "Search past conversations.",
        "tier": "safe",
        "status": "registered",
        "tools": [("session_search", "Search past sessions.", "safe", "registered")],
    },
    # Wire-candidate: kept catalogued (assignable only once a tool is wired).
    {
        "key": "skills_management",
        "name": "Skills",
        "description": "List/view skills (managing them is orchestrator-tier).",
        "tier": "safe",
        "status": "registered",
        "tools": [
            ("skills_list", "List skills.", "safe", "registered"),
            ("skill_view", "View a skill.", "safe", "registered"),
            ("skill_manage", "Install/modify skills (capability mutation).", "orchestrator", "registered"),
        ],
    },
    # Wire-candidate: kept catalogued (assignable only once a tool is wired).
    {
        "key": "task_planning",
        "name": "Task Planning",
        "description": "todo lists.",
        "tier": "safe",
        "status": "registered",
        "tools": [("todo", "Maintain a todo list.", "safe", "registered")],
    },
    {
        "key": "charting",
        "name": "Charting",
        "description": "render_chart — turn structured data into a rich interactive chart "
                       "(line, bar, area, pie, scatter, radar, funnel, gauge, heatmap).",
        "tier": "safe",
        "status": "wired",
        "tools": [
            ("render_chart", "Render an interactive chart from structured data. type=one of "
             "line|bar|area|pie|scatter|radar|funnel|gauge|heatmap; x=labels, "
             "series=[{name,values}]; optional stacked/horizontal/smooth, y=row labels for heatmap. "
             "Shown to the user.", "safe", "wired"),
        ],
    },
    {
        "key": "code_sandbox",
        "name": "Code Sandbox",
        "description": "run_python — execute Python in a local sandbox (no network, scrubbed env, "
                       "numpy/pandas/matplotlib preinstalled). Lets spawns compute, not just talk.",
        "tier": "safe",
        "status": "wired",
        "tools": [
            ("run_python", "Run Python code in a local sandbox and get stdout/stderr back. "
             "Pass {code}, OR {skill_script: '<skill-key>/<file>.py'} to run a script bundled "
             "with an imported skill. print() your results — stdout is the return channel. "
             "No network (fetch data via web_search/web_extract first, embed it in the code); "
             "numpy/pandas/matplotlib preinstalled; ~15s limit; files written land in a "
             "throwaway dir (names reported).", "safe", "wired"),
            ("read_skill", "Read the full body (or one section) of a skill you're equipped with. "
             "Pass {key:'<skill-key>'} for the whole thing, or {key, section:'## Heading'} for one "
             "section. Use this when an injected technique block is summarized/truncated.",
             "safe", "wired"),
        ],
    },
    {
        "key": "deck",
        "name": "Deck / PPTX",
        "description": "render_deck — turn a structured deck spec into a native, editable PowerPoint "
                       "(.pptx): themed slides with bullets, native tables, native editable charts and "
                       "KPI stat blocks.",
        "tier": "safe",
        "status": "wired",
        "tools": [
            ("render_deck", "ONLY when the user EXPLICITLY asks for an editable PowerPoint / "
             ".pptx FILE (说要'pptx文件'/'可编辑的PPT'/'PowerPoint'). For any other presentation "
             "request the deliverable is a designed single-file HTML deck typed directly as your "
             "reply (starts with <!DOCTYPE html — see your deck-authoring skill); do NOT call "
             "this tool for those. "
             "Generate a native, editable PowerPoint (.pptx) from a deck spec. "
             "slides=[{layout, ...}]. Per-layout fields (use ONLY these): "
             "title→{title,subtitle} · section→{title} · bullets→{title,bullets:[str]} "
             "(max ~6 shown; keep each bullet one short line) · "
             "two-column→{title,left:[str],right:[str]} (left/right ONLY here, never on bullets; "
             "may add {left_title,right_title} column headers) · "
             "quote→{text,attribution} · big-number→{value,label} · "
             "table→{title,headers:[str],rows:[[cell,...],...]} (native table, themed header + "
             "zebra rows; ≤7 rows shown, extras go to speaker notes) · "
             "chart→{title,chart_type:'bar'|'column'|'line'|'pie',categories:[str],"
             "series:[{name,values:[number]}]} (native EDITABLE chart; every series' values "
             "length must equal categories length; pie takes exactly 1 series) · "
             "kpi→{title,items:[{value,label}]} (2-4 stat blocks, e.g. value:'92%', "
             "label:'devs using AI'). "
             "PICK THE LAYOUT BY DATA SHAPE — numeric comparisons/trends/shares → chart or "
             "table; top-N lists or anything row/column-shaped → table; 1 headline stat → "
             "big-number; 2-4 headline stats → kpi. Do NOT put rows of numbers in bullets — "
             "bullets are for short prose points only. "
             "Each slide may carry notes (speaker notes). Optional theme (string): 'ember' "
             "(house default — wheat paper, warm black, rust-orange accent) | 'ember-dark' "
             "(warm black bg, bright orange) | 'ink' (paper + chartreuse) | 'midnight' "
             "(dark, cyan) | 'azure' (white, deep blue) | 'terra' (cream, orange). The user gets a downloadable .pptx — real designed shapes, text, "
             "tables and charts, not images.", "safe", "wired"),
        ],
    },
    {
        "key": "skill_authoring",
        "name": "Skill Authoring",
        "description": "create_skill — package a reusable method into a skill candidate "
                       "(human-gated before it goes live).",
        "tier": "safe",
        "status": "wired",
        "tools": [
            ("create_skill", "Forge a new skill candidate from a SKILL.md body; enters "
             "observation/eval, never auto-installed.", "safe", "wired"),
        ],
    },
]

# (key, name, category, description, tier, status)
_S = "safe"
_O = "orchestrator"
_REG = "registered"
SKILLS: list[tuple[str, str, str, str, str, str]] = [
    # META (self-authoring — ingested/adapted from anthropics/skills, Apache-2.0; see THIRD_PARTY_NOTICES.md)
    ("skill-creator", "skill-creator", "meta",
     "Package a reusable method into a high-quality SKILL.md; lets users/Arslan self-author skills.", _S, _REG),
    ("writing-skills", "writing-skills", "meta",
     "TDD-for-skills: baseline-test → write → close loopholes; how to author/verify a SKILL.md.", _S, _REG),
    # COLLABORATION (methodology — adapted from obra/superpowers, MIT; see THIRD_PARTY_NOTICES.md)
    ("brainstorming", "brainstorming", "collaboration",
     "Explore an idea into a design before any implementation: one question at a time, approval-gated.", _S, _REG),
    ("receiving-code-review", "receiving-code-review", "collaboration",
     "Evaluate review feedback technically: verify before implementing, no performative agreement.", _S, _REG),
    # COLLABORATION (methodology — adapted from mattpocock/skills, MIT; see THIRD_PARTY_NOTICES.md)
    ("resolving-merge-conflicts", "resolving-merge-conflicts", "collaboration",
     "Resolve a git merge/rebase conflict by intent: trace each side's original purpose, reconcile, verify, finish.", _S, _REG),
    ("domain-modeling", "domain-modeling", "collaboration",
     "Actively sharpen a project's domain model: ubiquitous-language glossary (CONTEXT.md) + sparing ADRs.", _S, _REG),
    # FINANCE (migrated from anthropics/financial-services · market-researcher, Apache-2.0; see THIRD_PARTY_NOTICES.md)
    ("sector-overview", "sector-overview", "finance",
     "Board a sector/theme primer: market size & growth, structure, value chain, drivers, landscape, valuation.", _S, _REG),
    ("competitive-analysis", "competitive-analysis", "finance",
     "Map a competitive landscape: industry metrics, peer deep-dives, positioning, moats, strategic synthesis.", _S, _REG),
    ("comps-analysis", "comps-analysis", "finance",
     "Build a trading-comps spread: pick peers, per-industry multiples, consistent definitions, outlier flags.", _S, _REG),
    ("idea-generation", "idea-generation", "finance",
     "Source investment ideas: quant screens by style, thematic sweep, shortlist with thesis hooks and risks.", _S, _REG),
    # CREATIVE — presentation storytelling (HTML deck by default; pairs with render_deck for .pptx)
    ("deck-authoring", "deck-authoring", "creative",
     "Turn content into a storytelling deck: one idea per slide, assertion-evidence titles, narrative arc; "
     "ships a designed single-file HTML presentation by default, native editable .pptx via render_deck on explicit request.", _S, _REG),
    # WRITING (adapted from anthropics/skills, Apache-2.0)
    ("internal-comms", "internal-comms", "writing",
     "Write internal comms in company formats: 3P updates, newsletters, FAQs, status/incident reports.", _S, _REG),
    # MARKETING (adapted from anthropics/skills, Apache-2.0)
    ("brand-guidelines", "brand-guidelines", "marketing",
     "Apply a consistent brand palette + typography to any artifact (Anthropic brand as reference).", _S, _REG),
    # CREATIVE (adapted from anthropics/skills, Apache-2.0)
    ("frontend-design", "frontend-design", "creative",
     "Distinctive, opinionated UI visual design: palette, typography, layout, one justified risk.", _S, _REG),
    ("theme-factory", "theme-factory", "creative",
     "Apply a consistent color+font theme to artifacts from presets, or generate one on the fly.", _S, _REG),
    ("canvas-design", "canvas-design", "creative",
     "Design-philosophy method for original static visual art (poster/artwork): 90% visual, 10% text.", _S, _REG),
    ("algorithmic-art", "algorithmic-art", "creative",
     "Algorithmic-philosophy method for p5.js generative art with seeded, reproducible randomness.", _S, _REG),
    # AUTONOMOUS-AI-AGENTS (decision §9: registered, orchestrator-only, unwired)
    ("claude-code", "claude-code", "autonomous-ai-agents", "Delegate coding to Claude Code CLI.", _O, _REG),
    ("codex", "codex", "autonomous-ai-agents", "Delegate coding to OpenAI Codex CLI.", _O, _REG),
    ("opencode", "opencode", "autonomous-ai-agents", "Delegate coding to OpenCode CLI.", _O, _REG),
    # CREATIVE
    ("architecture-diagram", "architecture-diagram", "creative", "SVG architecture diagrams as HTML.", _S, _REG),
    ("ascii-art", "ascii-art", "creative", "ASCII art.", _S, _REG),
    ("baoyu-infographic", "baoyu-infographic", "creative", "Infographics: 21 layouts x 21 styles.", _S, _REG),
    ("claude-design", "claude-design", "creative", "One-off HTML artifacts (landing, deck).", _S, _REG),
    ("design-md", "design-md", "creative", "Author/validate DESIGN.md token specs.", _S, _REG),
    ("designed-html-report", "designed-html-report", "creative",
     "设计版报告:报告/简报/方案等长篇交付物产出自带设计系统的单文件 HTML(Designed HTML Report),而非 markdown 长文。", _S, _REG),
    ("excalidraw", "excalidraw", "creative", "Hand-drawn Excalidraw JSON diagrams.", _S, _REG),
    ("humanizer", "humanizer", "creative", "Strip AI-isms, add real voice.", _S, _REG),
    ("p5js", "p5js", "creative", "p5.js sketches.", _S, _REG),
    ("pretext", "pretext", "creative", "DOM-free text layout / kinetic typography HTML demos.", _S, _REG),
    ("sketch", "sketch", "creative", "Throwaway HTML mockups, 2-3 variants.", _S, _REG),
    ("songwriting-and-ai-music", "songwriting-and-ai-music", "creative", "Songwriting + Suno prompts.", _S, _REG),
    # GITHUB
    ("github-auth", "github-auth", "github", "GitHub auth setup (credentials).", _O, _REG),
    ("github-code-review", "github-code-review", "github", "Review PR diffs; posting comments needs orchestrator tools.", _S, _REG),
    ("github-issues", "github-issues", "github", "Create/triage issues (repo writes).", _O, _REG),
    ("github-pr-workflow", "github-pr-workflow", "github", "PR lifecycle (repo mutation).", _O, _REG),
    ("github-repo-management", "github-repo-management", "github", "Clone/fork/releases (repo mutation).", _O, _REG),
    # MEDIA
    ("youtube-content", "youtube-content", "media", "YouTube transcripts → summaries/threads.", _S, _REG),
    # RESEARCH
    ("arxiv", "arxiv", "research", "Search arXiv papers.", _S, _REG),
    ("blogwatcher", "blogwatcher", "research", "Monitor blogs/RSS feeds.", _S, _REG),
    ("llm-wiki", "llm-wiki", "research", "Build/query interlinked markdown KB.", _S, _REG),
    ("research-paper-writing", "research-paper-writing", "research", "Write ML papers (NeurIPS/ICML).", _S, _REG),
    # SOFTWARE-DEVELOPMENT
    ("verification-before-completion", "verification-before-completion", "software-development",
     "Run verification and read output before claiming done/fixed/passing (analysis discipline).", _S, _REG),
    ("finishing-a-development-branch", "finishing-a-development-branch", "software-development",
     "Verify tests, then present 4 options (merge/PR/keep/discard) and execute + worktree cleanup.", _O, _REG),
    ("mcp-builder", "mcp-builder", "software-development",
     "Design high-quality MCP servers: tool design, naming, error messages, evaluations.", _S, _REG),
    ("webapp-testing", "webapp-testing", "software-development",
     "Playwright web-app testing methodology: reconnaissance-then-action, wait-for-networkidle.", _S, _REG),
    ("codebase-audit", "codebase-audit", "software-development", "Audit + risk classify (read/plan only).", _S, _REG),
    ("node-inspect-debugger", "node-inspect-debugger", "software-development", "Debug Node via CDP (attaches/executes).", _O, _REG),
    ("plan", "plan", "software-development", "Plan mode: markdown plan, no execution.", _S, _REG),
    ("python-debugpy", "python-debugpy", "software-development", "Debug Python (executes/attaches).", _O, _REG),
    ("requesting-code-review", "requesting-code-review", "software-development", "Request a code review with clean work-product context; severity-based action (methodology).", _S, _REG),
    ("simplify-code", "simplify-code", "software-development", "3-agent cleanup (mutates code).", _O, _REG),
    ("spike", "spike", "software-development", "Throwaway experiments (runs code).", _O, _REG),
    ("systematic-debugging", "systematic-debugging", "software-development", "4-phase root-cause analysis (analysis-only).", _S, _REG),
    ("test-driven-development", "test-driven-development", "software-development", "TDD (runs tests/writes code).", _O, _REG),
]
