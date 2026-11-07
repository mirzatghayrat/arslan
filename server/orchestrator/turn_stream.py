"""A turn's text on its way to the user: what it showed, one step's text as it arrives, and what a guard does to text
already out (split from tool_loop, LOOP1 c1b)."""
from __future__ import annotations

import re
from collections.abc import Callable

from server.orchestrator.answer_guards import _DEFERRAL_MAX, _PROTOCOL_PATTERNS, _embeds_protocol


# 0.1.63 K8a–K8c: the answer goes out while it is written (OpenAI-compatible endpoints that stream, Claude
# on Anthropic's host, Gemini on Google's). An answer that was not streamed (an endpoint that cannot, the
# "show answers when complete" setting, a wrap-up written whole) goes out as one piece, at once: K8c removed
# the simulated typing (_reveal_streamed) that used to pace it out. A step's text is held until it passes
# _DEFERRAL_MAX (a short answer is judged whole, exactly as before), then shown as it arrives, except:
_STREAM_HOLD = 64      # the tail kept back: longer than any text _PROTOCOL_PATTERNS need to decide
_JSON_HOLD = 1500      # a JSON object kept back until it closes (at most this long): its keys decide
_JSON_START = re.compile(r'\{\s*"')
#: Model names whose steps are shown only when complete (the guards bounce instead of correcting), as
#: M1 decides (D6). Empty: every streaming model streams. Reviewed in v0.1.65; deleted when still empty.
BUFFERED_MODELS: frozenset[str] = frozenset()


#: K8a (⓪Plan Q4): an answer that claims what no tool did is sent back at most this often per turn, then
#: written from the findings (the same-failure count of policy.observe used to end it; guards no longer
#: count toward "no progress").
_UNVERIFIED_BOUNCES = 2


def _shown(turn_text: "_TurnText | None") -> str | None:
    """What this turn already showed, for an answer that ends another way (a choice card, an escalation)."""
    return turn_text.text if turn_text is not None and turn_text.parts else None


#: The reply languages (arslan.reply_language) that have a runtime_messages table.
_LABEL_LOCALES = {"English": "en", "Chinese": "zh", "Japanese": "ja", "Spanish": "es", "German": "de", "French": "fr"}


def _label_locale(text: str) -> str | None:
    """The locale of the language `text` is written in, or None when it can't be told or has no table."""
    from server.orchestrator.arslan import reply_language
    return _LABEL_LOCALES.get(reply_language(text))


async def _correct(turn_text: "_TurnText | None", shown: bool) -> None:
    """K8a: once a step's text went out, a guard that sends it back replaces that step's text with the text that
    follows. Until 2026-11-03 a correction line and the new text followed it, so one message could hold the same
    answer four times (user report via ①iOS). The label is in the language of the text it replaces (the interface
    language only when that can't be told)."""
    if shown and turn_text is not None and turn_text.step_text:
        from server.services import runtime_messages
        locale = _label_locale(turn_text.step_text) or await runtime_messages.selected_locale()
        turn_text.replace_step(runtime_messages.render("stream_correction", locale))


async def _kept_note(turn_text: "_TurnText") -> str:
    """K8a (#694 review, ⓪Plan's decision): nothing usable replaced a step that was sent back, so what the user saw
    stays, followed by this one note in its language (never a bare generic answer instead)."""
    from server.services import runtime_messages
    return runtime_messages.render("stream_unverified_note",
                                   _label_locale(turn_text.text) or await runtime_messages.selected_locale())


async def _not_verified(turn_text: "_TurnText", links: list[str]) -> None:
    from server.services import runtime_messages
    new = [link for link in links if link not in turn_text.listed]
    if new:
        turn_text.listed.update(new)
        turn_text.append(runtime_messages.render("links_not_verified", await runtime_messages.selected_locale(),
                                                 links=", ".join(new)), answer=False)


class TextShown(Exception):
    """K8a: a model request failed after part of its answer was shown. It is never sent again (the text
    would show twice); the turn ends with what was shown and says it was interrupted."""


class _TurnText:
    """K8a: what this turn showed through on_chunk: the stored answer is this. Every joiner (the window, the phone's
    Bridge, the run record, a window that reattaches) concatenates the chunks; at a `stream_restart` frame it starts
    over from the frame's `keep` (what earlier steps showed). The frame's label is what the window shows on the text
    it replaced, kept there as a collapsed earlier draft.

    A replaced step goes only when the text that replaces it is shown (`replace_step` waits): a turn that ends with
    nothing better keeps what the user saw (#694 review, finding 2)."""

    def __init__(self, on_chunk: Callable[[str], None], on_restart: Callable[[str, str], None] | None = None):
        self.on_chunk, self.on_restart, self.parts = on_chunk, on_restart, []
        self.listed: set[str] = set()       # links already said to be unverified
        self.step_at = 0                    # where the current step's text begins in `parts`
        self.pending: tuple[str, int] | None = None     # a replaced step waiting for its replacement: (label, at)

    def begin_step(self) -> None:
        self.step_at = len(self.parts)

    @property
    def step_text(self) -> str:
        return "".join(self.parts[self.step_at:])

    def replace_step(self, label: str) -> None:
        """The current step's text goes once the text replacing it is shown; earlier steps' text stays."""
        if self.pending is None:
            self.pending = (label, self.step_at)

    def after(self, text: str) -> str:
        """The answer once `text` is appended as answer text (a step waiting to be replaced goes then)."""
        base = "".join(self.parts[:self.pending[1]] if text and self.pending is not None else self.parts)
        return base + ("\n\n" if base and text else "") + text

    def keep_shown(self) -> None:
        """Nothing replaces it after all: what was shown stays."""
        self.pending = None

    def _restart(self) -> None:
        label, at = self.pending
        keep = "".join(self.parts[:at])
        if self.on_restart is not None:
            self.on_restart(label, keep)
        self.parts, self.listed, self.pending = ([keep] if keep else []), set(), None
        self.step_at = len(self.parts)

    def show(self, text: str) -> None:
        if text:
            self.on_chunk(text)
            self.parts.append(text)

    def append(self, text: str, *, answer: bool = True) -> None:
        """A new part of the answer (a step's text, a note): after a blank line. Answer text replaces a step
        waiting to be replaced (a step's first text always comes here); a note doesn't."""
        if text and answer and self.pending is not None:
            self._restart()
        self.show(("\n\n" if self.parts and text else "") + text)

    @property
    def text(self) -> str:
        return "".join(self.parts)


def _json_end(text: str, start: int) -> int | None:
    """Just past the JSON object opening at `start`, or None while it is still open."""
    depth, in_string, escaped = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            escaped, in_string = (False, True) if escaped else (ch == "\\", ch != '"')
        elif ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    return None


class _StepStream:
    """K8a: one model step's text on its way out. Held until it passes the window; then shown as it
    arrives, except a tool call written as text (_PROTOCOL_PATTERNS: never shown, and this step's stream
    stops there) and host bookkeeping (agent_status.ECHO_BLOCK: dropped)."""

    def __init__(self, turn: _TurnText, window: int = _DEFERRAL_MAX):
        self.turn, self.window = turn, window
        turn.begin_step()
        self.held = self.pending = ""
        self.released = self.stopped = False
        self._started = False

    def feed(self, piece: str) -> None:
        if self.stopped:
            return
        if not self.released:
            self.held += piece
            if len(self.held) < self.window:
                return
            self.released, self.pending, self.held = True, self.held, ""
        else:
            self.pending += piece
        self._drain(final=False)

    def retry_ok(self) -> bool:
        """A failed request may be sent again only while nothing of it went out (what it held is dropped)."""
        if self.released:
            return False
        self.held = ""
        return True

    def finish(self) -> None:
        if self.released and not self.stopped:
            self._drain(final=True)

    def _show(self, text: str) -> None:
        if text:
            if self._started:
                self.turn.show(text)
            else:
                self._started = True
                self.turn.append(text)

    def _drain(self, final: bool) -> None:
        from server.orchestrator import agent_status
        text = agent_status.ECHO_BLOCK.sub("", self.pending)
        opened = [i for tag in agent_status.ECHO_TAGS if (i := text.find(tag)) >= 0]
        cut = min(opened) if opened else len(text)   # a block still open: never shown; dropped if it never closes
        hits = [m.start() for pattern in _PROTOCOL_PATTERNS if (m := pattern.search(text)) is not None]
        start = 0
        while (opening := _JSON_START.search(text, start)) is not None and opening.start() < cut:
            end = _json_end(text, opening.start())
            if end is None:
                if not final and len(text) - opening.start() < _JSON_HOLD:
                    cut = opening.start()
                break
            if _embeds_protocol(text[opening.start():end]):
                hits.append(opening.start())
                break
            start = end
        if hits and min(hits) < cut:
            self._show(text[:min(hits)])
            self.pending, self.stopped = "", True
            return
        if not final:
            cut = min(cut, max(0, len(text) - _STREAM_HOLD))
        self._show(text[:cut])
        self.pending = "" if final else text[cut:]


# Claude's documented stand-in for an update a limit cut short (claude-api model-migration guide): not news.
_UPDATE_CUT = "This part of the response was interrupted before it finished."


def _progress_updates(a, resp) -> list[str]:
    """K8b: the non-empty thinking blocks of a Claude step whose answered request carried
    `display: "updates"` (the provider marks the continuation): under that display such a block is an
    update, never the model's reasoning."""
    continuation = getattr(resp, "continuation", None) or {}
    if continuation.get("protocol") != "anthropic" or not continuation.get("updates"):
        return []
    texts = [str(b.get("thinking") or "").strip() for b in continuation.get("content") or []
             if b.get("type") == "thinking"]
    return [text for text in texts if text and text != _UPDATE_CUT]


def _streams_answer(a, acceptance_runtime) -> bool:
    """K8a: whether this turn's answer is shown as it is written. Not for work with explicit acceptance
    criteria (background jobs and the like: a failed check rewrites what was written; ⓪Plan Q1), not for
    a model in BUFFERED_MODELS."""
    from server.orchestrator.model_step import _model_key      # model_step imports TextShown from here
    from server.services import task_service
    return not ((acceptance_runtime is not None and not task_service.answer_only())
                or _model_key(a)[1] in BUFFERED_MODELS)
