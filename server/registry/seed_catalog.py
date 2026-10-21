"""Arslan's capability catalog, seeded into the registry (spec §1.3). It began as the Hermes
toolset catalog (NousResearch/hermes-agent, MIT); what remains from it is shared tool names and
grouping, credited in THIRD_PARTY_NOTICES.md (checked at source, C9). Descriptions are Arslan's.

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
        "key": "task_collaboration", "name": "Task Collaboration",
        "description": "Task-local, read-only professional collaboration. Shared budget; no recursive delegation.",
        "tier": "orchestrator", "status": "wired",
        "tools": [("delegate_work", "Assign independent bounded subtasks to temporary collaborators.",
                   "orchestrator", "wired")],
    },
    {
        "key": "task_recovery", "name": "Task Recovery",
        "description": "Inspect saved progress and prior outputs of the current task only.",
        "tier": "orchestrator", "status": "wired",
        "tools": [("task_progress", "Read the current task's saved progress and owned prior outputs.",
                   "orchestrator", "wired")],
    },
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
        "key": "second_brain",
        "name": "Second Brain",
        "description": "recall — search the user's memory; remember — write to it "
                       "(append/supersede/mark_stale; deletes propose for human confirm).",
        "tier": "safe",
        "status": "wired",
        "tools": [
            ("recall", "Search the user's second brain (facts, learnings, notes) and "
             "return active matches with provenance.", "safe", "wired"),
            ("remember", "Write to the second brain: append a fact/learning/note/preference, "
             "supersede an outdated one, or mark stale. Destructive edits/deletes are "
             "proposed for the user to confirm, not executed.", "safe", "wired"),
            ("conversation_search", "Search earlier conversations and return original snippets "
             "with date and an in-app link (0.1.52).", "safe", "wired"),
            ("memory_note", "Edit the always-in-view memory by entry id: \"About you\" and Arslan's "
             "notes about this Mac and setup (0.1.52).", "safe", "wired"),
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
    # C9 (v0.1.63, U13 item 3): two skills ship with Arslan; the other 53 are retired (seeder.py).
    # META (adapted from anthropics/skills, Apache-2.0; see THIRD_PARTY_NOTICES.md)
    ("skill-creator", "skill-creator", "meta",
     "Package a reusable method into a high-quality SKILL.md; lets users/Arslan self-author skills.", _S, _REG),
    # CREATIVE (Arslan's own)
    ("designed-html-report", "designed-html-report", "creative",
     "设计版报告:报告/简报/方案等长篇交付物产出自带设计系统的单文件 HTML(Designed HTML Report),而非 markdown 长文。", _S, _REG),
]
