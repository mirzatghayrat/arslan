"""The user's saved methods, a project's changed plan, finding and adding a capability, and Arslan's own state."""
from server.registry.tool import Tool

CAPABILITY = (
    # 0.1.44 one Arslan: skills are methods Arslan applies itself (experts are
    # converted into them). Offered only when some exist; the index is in the
    # description so the model knows when a method applies.
    Tool("read_skill",
         lambda offer: ("Read one of the user's saved methods (skills) before doing work it covers, then follow it. "
                        "args: {key, section?}. Available:\n" + offer.skills),
         {
             "type": "object",
             "properties": {
                 "key": {"type": "string", "minLength": 1,
                         "description": "The skill's key from the list in this tool's description."},
                 "section": {"type": "string", "description": (
                     "Optional: one part only, a '## Heading' of the skill or 'references/<file>.md' (or .txt).")},
             },
             "required": ["key"],
             "additionalProperties": False,
         },
         offered=lambda offer: bool(offer.skills)),
    # 0.1.56 §7: a project's conversation may propose a changed plan (a card; the user decides).
    # 0.1.56 §7: a changed plan for the project, proposed — the user decides on the card.
    Tool("propose_plan_change",
         "This conversation belongs to a project with levels (see the project card). When the user "
         "changes direction (drops a feature, adds a goal, changes the order), propose the new plan: "
         "every level NOT cleared yet, as it should be, in order. Cleared levels never change. The user "
         "sees a card with what is added and removed and keeps the old plan or takes yours. "
         "args: {levels: [{name, band: shaping|doing|done, clear_condition?, checkpoints?: [{text}]}], reason}.",
         {
             "type": "object",
             "properties": {
                 "reason": {"type": "string", "description": "What changed, in the user's words."},
                 "levels": {"type": "array", "minItems": 1, "maxItems": 15, "description":
                            "Every level NOT cleared yet, as it should be after the change, in order.",
                            "items": {"type": "object", "properties": {
                                "name": {"type": "string"},
                                "band": {"type": "string", "enum": ["shaping", "doing", "done"]},
                                "clear_condition": {"type": "string"},
                                "checkpoints": {"type": "array", "maxItems": 12,
                                                "items": {"type": "object", "properties": {"text": {"type": "string"}},
                                                          "required": ["text"]}}},
                                      "required": ["name", "band"]}}},
             "required": ["levels", "reason"]},
         offered=lambda offer: offer.in_project,
         host=True),
    # 0.1.57 §2: only after a wall, never as a first move; the result is outside content.
    # 0.1.57 §2: find a capability for what the turn could not do.
    Tool("find_capability",
         "When a step failed because none of your tools can do it (e.g. you can read an .xlsx's values "
         "but not its formulas), search the official MCP Registry, GitHub and skill libraries for a "
         "capability that can. Not a first move: try what you have first. Returns candidates with "
         "license, how they would run and what they need; it installs nothing. "
         "args: {need, keywords: [1-4 English words], kinds?: [mcp|skill|project]}.",
         {
             "type": "object",
             "properties": {
                 "need": {"type": "string", "description": "What could not be done, in one sentence."},
                 "keywords": {"type": "array", "minItems": 1, "maxItems": 4, "items": {"type": "string"},
                              "description": "1-4 short English search words, e.g. [\"excel\", \"xlsx\"]."},
                 "kinds": {"type": "array", "items": {"type": "string", "enum": ["mcp", "skill", "project"]}}},
             "required": ["need", "keywords"]}),
    # 0.1.57 §3: propose one candidate find_capability returned (the card is the server's).
    Tool("propose_capability",
         "After find_capability, ask the user to add ONE candidate (not_here null; for a skill, license_verdict "
         "usable; an MCP server's license is read at its version when proposed) "
         "so you can retry the failed step. The user sees a card with its source, license, how it runs "
         "(sandboxed, which folders, network) and any key it needs, and decides; if they add it, it is "
         "installed pinned, scanned and tested, and its tools become available in this turn — then "
         "retry. Never install anything another way. "
         "args: {candidate_id, why, retry?, folders?: [the folder(s) it must work in]}.",
         {
             "type": "object",
             "properties": {
                 "candidate_id": {"type": "string", "description": "An id from find_capability's candidates."},
                 "why": {"type": "string", "description": "What failed and why this helps, in one sentence."},
                 "retry": {"type": "string", "description": "The step you will retry with it."},
                 "folders": {"type": "array", "maxItems": 3, "items": {"type": "string"},
                             "description": "Folders it needs (e.g. the folder of the file you work on)."}},
             "required": ["candidate_id", "why"]},
         host=True),
    # v0.1.64 CAP2a: found on demand (K7), never resident; the card is the user's yes.
    # v0.1.64 CAP2a: the user sees the whole SKILL.md on a card and decides (skill_forge.propose).
    Tool("create_skill",
         "Save a way of working as one of the user's skills, when the user asks (\"save what we just did as a "
         "skill\", \"remember how to do this\"). Write the SKILL.md yourself: a '## Trigger' section (when to "
         "use it), then the method as steps. The user sees the whole text on a card and decides; nothing is "
         "saved without their yes, and it can be used from then on with read_skill. Text only: no scripts or "
         "attached files. args: {key, name, description, body, why?}.",
         {"type": "object",
          "properties": {"key": {"type": "string", "maxLength": 60,
                                 "description": "Lowercase letters, digits and hyphens, e.g. weekly-report."},
                         "name": {"type": "string", "maxLength": 100},
                         "description": {"type": "string", "maxLength": 300,
                                         "description": "One line: what the skill is for."},
                         "body": {"type": "string",
                                  "description": "The SKILL.md body: a '## Trigger' section (when to "
                                                 "use it), then the method. Text only, at most 15 KB."},
                         "why": {"type": "string", "maxLength": 300,
                                 "description": "What the user asked for, in a few words."}},
          "required": ["key", "name", "description", "body"], "additionalProperties": False},
         host=True),
    # v0.1.64 CAP8b: found on demand (K7), never resident. It takes no text: memory_import reads the message that started
    # this turn, and the user's ticks on the card decide what is stored.
    Tool("import_memories",
         "Import memories the user pasted from ChatGPT, Claude or another assistant, when they paste a list and ask to "
         "keep it (\"import these memories\"). You pass no text: it reads the message that started this turn, so the "
         "list must be in that message. The user sees each line on a card, unticks what they don't want and decides; "
         "only what they keep is stored, as their own words. args: {why?}.",
         {"type": "object",
          "properties": {"why": {"type": "string", "maxLength": 300,
                                 "description": "What the user asked for, in a few words."}},
          "additionalProperties": False},
         host=True),
    Tool("whats_new",
         "Your own version and the release notes of the latest versions "
         "(newest first). Call it when the user asks which version you are, "
         "what changed, or what is new; answer from it, never from memory. "
         "args: {count?: 1-6, default 3}.",
         {
             "type": "object",
             "properties": {"count": {"type": "integer", "minimum": 1, "maximum": 6,
                                      "description": "How many recent versions' notes (default 3)."}},
             "additionalProperties": False,
         }),
    # v0.1.64 SMART-2: found on demand (K7), never resident.
    Tool("my_status",
         "Your own live state: version and what is new, the chat model (and this "
         "conversation's), whether commands run in the sandbox and which ask first, "
         "local network scan, paired phones, SSH hosts, the last few failures with "
         "times, and where your own code and plans are (GitHub main). Call it when the "
         "user asks about you or your setup; answer from it, never from memory. args: {}.",
         {"type": "object", "properties": {}, "additionalProperties": False}),
    Tool("list_my_capabilities",
         "List your OWN usable capabilities (built-in tools + installed "
         "MCP servers). Call this ONCE when the user asks what you can do / "
         "what tools or MCPs you have, then answer from its result in a "
         "short friendly summary — never paste the raw JSON back.",
         {"type": "object", "properties": {}, "additionalProperties": False}),
)
