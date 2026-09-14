"""Conservative credential screening for ordinary memory, without echoing values."""
import re
import unicodedata

_SECRET_PATTERNS = tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
    r"-----BEGIN (?:[A-Z ]*PRIVATE KEY|OPENSSH PRIVATE KEY)-----",
    r"\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|AIza[A-Za-z0-9_-]{30,})\b",
    r"\bBearer\s+[A-Za-z0-9_.~+/-]{16,}",
    r"(?:password|passwd|api[_ -]?key|access[_ -]?token|refresh[_ -]?token|session[_ -]?cookie)"
    r"[\"']?\s*(?:is|=|:)\s*[^\s]{4,}",
    r"(?:密码|密钥|验证码|令牌|Cookie)\s*(?:是|为|=|:|：)\s*[^\s，。]{4,}",
))


def contains_credential(content: str) -> bool:
    """A safety screen, not a guarantee that every possible secret is detectable."""
    normalized = unicodedata.normalize("NFKC", content)
    return any(pattern.search(normalized) for pattern in _SECRET_PATTERNS)


def contains_credential_data(value: object) -> bool:
    """Screen structured arguments before execution; never log detected values."""
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = re.sub(r"[\s_-]", "", unicodedata.normalize("NFKC", str(key))).casefold()
            if normalized in {"password", "passwd", "apikey", "accesstoken", "refreshtoken",
                              "sessioncookie", "authorization", "privatekey", "密码", "密钥", "令牌"}:
                if item not in (None, "", False):
                    return True
            if contains_credential_data(item):
                return True
        return False
    if isinstance(value, (list, tuple)):
        return any(contains_credential_data(item) for item in value)
    return isinstance(value, str) and contains_credential(value)


def normalized_memory(content: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", content).casefold().split())
