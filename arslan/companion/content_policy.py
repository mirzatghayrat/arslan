"""Conservative credential screening for ordinary memory, without echoing values."""
import re
import unicodedata

_SECRET_PATTERNS = tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
    r"-----BEGIN (?:[A-Z ]*PRIVATE KEY|OPENSSH PRIVATE KEY)-----",
    r"\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|AIza[A-Za-z0-9_-]{30,})\b",
    r"\bBearer\s+[A-Za-z0-9_.~+/-]{16,}",
    r"(?:password|passwd|api[_ -]?key|access[_ -]?token|refresh[_ -]?token|session[_ -]?cookie)"
    r"\s*(?:is|=|:)\s*[^\s]{4,}",
    r"(?:密码|密钥|验证码|令牌|Cookie)\s*(?:是|为|=|:|：)\s*[^\s，。]{4,}",
))


def contains_credential(content: str) -> bool:
    """A safety screen, not a guarantee that every possible secret is detectable."""
    normalized = unicodedata.normalize("NFKC", content)
    return any(pattern.search(normalized) for pattern in _SECRET_PATTERNS)


def normalized_memory(content: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", content).casefold().split())
