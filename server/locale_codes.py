"""Display-only language normalization without config, storage or key bootstrap."""

SUPPORTED = ("en", "zh", "ja", "es", "de", "fr")


def normalize(locale):
    locale = {"English (US)": "en", "Chinese (Simplified)": "zh", "Japanese": "ja", "German": "de"}.get(locale, locale)
    code = str(locale or "en").replace("_", "-").split("-")[0].lower()
    return code if code in SUPPORTED else "en"
