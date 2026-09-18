"""Encrypted storage locations, shared by boot diagnosis and offline preflight."""

CIPHERTEXT_SITES = (
    ("settings", "value",
     "key IN ('llm_api_key', 'search_api_key', 'github_token', '_ssh_identity_private') "
     "OR key GLOB 'mcp_oauth_tokens_*' OR key GLOB 'mcp_oauth_client_*'"),
    ("provider_configs", "api_key", None),
    ("mcp_servers", "env", None),
)
