"""Bounded navigation links; never proof that a claim is supported by a source."""
import re
from urllib.parse import parse_qsl, quote, urlsplit

from arslan.companion.research import admitted_sources

LABELS = {
    "en": ("Source links (not claim verification)", "Read this turn", "Supplied link; not independently read", "Partially read; content truncated"),
    "zh": ("来源链接（不等于结论已核实）", "本轮已读取", "提供的链接；本轮未独立读取", "仅部分读取；内容已截断"),
    "ja": ("参照リンク（主張の検証ではありません）", "今回取得済み", "提供されたリンク・未取得", "部分取得・内容は省略されています"),
    "de": ("Quellenlinks (keine Aussagenprüfung)", "In diesem Durchlauf gelesen", "Bereitgestellter Link; nicht gelesen", "Teilweise gelesen; Inhalt gekürzt"),
    "es": ("Enlaces de fuentes (no verifican las afirmaciones)", "Leído en este turno", "Enlace proporcionado; no leído", "Lectura parcial; contenido truncado"),
    "fr": ("Liens sources (ne valident pas les affirmations)", "Lu pendant ce tour", "Lien fourni ; non consulté", "Lecture partielle ; contenu tronqué"),
}
_URL = re.compile(r"https?://[^\s<>\"'`]+")
_SECRET = re.compile(r"token|secret|password|signature|api.?key|authorization|credential", re.I)


def _safe(url):
    if not isinstance(url, str) or len(url) > 4000 or any(ord(char) < 32 for char in url):
        return None
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return None
        if any(_SECRET.search(key) for key, _ in parse_qsl(parsed.query)):
            return None
        # Markdown delimiters must not become a second link/image or HTML tag.
        return quote(url, safe=":/?#=&%+~._-")
    except ValueError:
        return None


def source_link_footer(provided: str, trace: list[dict], *, language="en") -> str:
    labels = LABELS.get((language or "en").split("-")[0], LABELS["en"])
    links = {}
    for source, _ in admitted_sources(trace).values():
        safe = _safe(source.url)
        if safe:
            links[safe] = labels[3] if source.truncated else labels[1]
    # Only inspect bounded user-supplied context, never model-written links.
    for match in _URL.finditer(provided[:200_000]):
        candidate = match.group().rstrip(".,;:!?，。；：！？")
        pairs = {")": "(", "]": "[", "}": "{"}
        while candidate and candidate[-1] in pairs and candidate.count(candidate[-1]) > candidate.count(pairs[candidate[-1]]):
            candidate = candidate[:-1]
        safe = _safe(candidate)
        if safe and safe not in links:
            links[safe] = labels[2]
        if len(links) >= 12:
            break
    if not links:
        return ""
    entries = [f"- [{index}]({url}) — {label}" for index, (url, label) in enumerate(list(links.items())[:12], 1)]
    return "\n\n---\n\n" + labels[0] + "\n\n" + "\n".join(entries)
