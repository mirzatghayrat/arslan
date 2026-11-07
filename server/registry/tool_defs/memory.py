"""The user's second brain and earlier conversations."""
from server.registry.tool import Tool

# INB2 (#475 F4): Arslan's own mark on a memory write; it only ever makes the write stricter.
_SENSITIVE_FLAG = {"type": "boolean", "description": "true if private"}

MEMORY = (
    Tool("recall",
         "Search the user's second brain (facts, learnings, notes) for relevant "
         "context before answering.",
         {"type": "object",
          "properties": {"query": {"type": "string"},
                         "kind": {"type": "string",
                                  "enum": ["fact", "material", "learning", "note"]}},
          "required": ["query"]}),
    Tool("remember",
         "Write to the user's second brain: a fact/learning/note worth remembering.",
         {"type": "object",
          "properties": {
              "kind": {"type": "string",
                       "enum": ["fact", "learning", "note", "preference"]},
              "action": {"type": "string",
                         "enum": ["append", "supersede", "mark_stale", "delete"]},
              "content": {"type": "string"},
              "target_id": {"type": "integer"},
              "sensitive": _SENSITIVE_FLAG,
          },
          "required": ["kind", "action", "content"]}),
    Tool("conversation_search",
         "Find what was said in earlier conversations with the user — their own "
         "words and your replies — as original snippets with date and a link. "
         "args: {query, since?, until? (YYYY-MM-DD), limit?}. Use it when the user "
         "refers to something from before (\"what did I say about…\", \"last week we…\").",
         {"type": "object",
          "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 200,
                                   "description": "Words to find, e.g. \"weekly report\" or \"landlord\"."},
                         "since": {"type": "string", "description": "YYYY-MM-DD, optional."},
                         "until": {"type": "string", "description": "YYYY-MM-DD, optional."},
                         "limit": {"type": "integer", "minimum": 1, "maximum": 20}},
          "required": ["query"], "additionalProperties": False}),
    Tool("memory_note",
         "Edit the two memory sets that are always in view, by entry id. set \"about_you\": "
         "lasting facts and preferences about the user; set \"notes\": what you learned about this "
         "Mac and setup (paths, tools, quirks). args: {action: add|replace|remove, set, id?, text?, "
         "sensitive?}. Keep entries short. Add sensitive: true for anything private (health, beliefs, "
         "relationships, money); the user is asked first. Changes apply from the next turn; a full set "
         "returns its entries so you can replace or remove one.",
         {"type": "object",
          "properties": {"action": {"type": "string", "enum": ["add", "replace", "remove"]},
                         "set": {"type": "string", "enum": ["about_you", "notes"]},
                         "id": {"type": "string", "description": "Entry id, for replace or remove."},
                         "text": {"type": "string", "maxLength": 600,
                                  "description": "The entry, for add or replace. One short line."},
                         "sensitive": _SENSITIVE_FLAG},
          "required": ["action", "set"], "additionalProperties": False}),
)
