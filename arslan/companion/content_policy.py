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
    """Screen structured arguments before execution; never log detected values. Screens raw values,
    never JSON-encoded text (D6: an encoded newline is a literal `\\n`, not whitespace, so a rule's value
    ran on into the next line and refused a note)."""
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = re.sub(r"[\s_-]", "", unicodedata.normalize("NFKC", str(key))).casefold()
            if normalized in {"password", "passwd", "apikey", "accesstoken", "refreshtoken",
                              "sessioncookie", "authorization", "privatekey", "密码", "密钥", "令牌"}:
                if item not in (None, "", False):
                    return True
            # D6: what the check on encoded text caught as a side effect, where the rule ran across
            # `"key":"value"`: a key that is itself a secret, a key that contains a credential word with
            # its value ("db_password: hunter22"), and a structure under such a key (checked with a
            # placeholder: its JSON would bring the escape back). A true/false is not a secret.
            if contains_credential(str(key)):
                return True
            if isinstance(item, (str, int, float)) and not isinstance(item, bool):
                if contains_credential(f"{key}: {item}"):
                    return True
            elif isinstance(item, (dict, list, tuple)) and item and contains_credential(f"{key}: <value>"):
                return True
            if contains_credential_data(item):
                return True
        return False
    if isinstance(value, (list, tuple)):
        return any(contains_credential_data(item) for item in value)
    return isinstance(value, str) and contains_credential(value)


def normalized_memory(content: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", content).casefold().split())


#: What shows nothing, or only blank space: white space, Unicode's default-ignorable code points
#: (DerivedCoreProperties.txt) and the blank braille pattern. A line of only these is blank, and a long run of
#: them is padding (#472 review F5, #526 review 1). UNI1's table, moved here from `server.orchestrator.untrusted`
#: (which imports it) so memory's keyword hold can read past them.
BLANK = (r"[\s\U000000ad\U0000034f\U0000061c\U0000115f\U00001160\U000017b4\U000017b5\U0000180b-\U0000180f"
         r"\U0000200b-\U0000200f\U0000202a-\U0000202e\U00002060-\U0000206f\U00002800\U00003164\U0000fe00-\U0000fe0f"
         r"\U0000feff\U0000ffa0\U0000fff0-\U0000fff8\U0001bca0-\U0001bca3\U0001d173-\U0001d17a\U000e0000-\U000e0fff]")
_INVISIBLE = re.compile(r"(?!\s)" + BLANK)
#: Of those, the ones that draw a gap: the blank braille pattern and the Hangul fillers. One in place of a space
#: still shows two words (#749 review).
_GAP = re.compile(r"[\U0000115f\U00001160\U00002800\U00003164\U0000ffa0]")


def visible_only(text: str) -> str:
    """`text` without any character that shows nothing (`BLANK` but white space), and a space for one that draws a
    gap."""
    return _INVISIBLE.sub("", _GAP.sub(" ", text))
