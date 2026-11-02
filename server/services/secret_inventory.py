"""Encrypted storage locations, shared by boot diagnosis and offline preflight.

A table may hold more than one encrypted column, and a database from before a column's migration does not have it
yet (mcp_servers.secrets came with 0081): every reader skips a site whose column is not there (`has_column`)."""

CIPHERTEXT_SITES = (
    ("settings", "value",
     "key IN ('llm_api_key', 'search_api_key', 'github_token', '_ssh_identity_private') "
     "OR key GLOB 'mcp_oauth_tokens_*' OR key GLOB 'mcp_oauth_client_*'"),
    ("provider_configs", "api_key", None),
    ("mcp_servers", "env", None),
    # SEC1 (migration 0081): the secrets moved out of a connection's address or arguments, by `${NAME}`.
    ("mcp_servers", "secrets", None),
)


def has_column(execute, table: str, column: str) -> bool:
    """`execute` is the caller's own (an SQLAlchemy connection's exec_driver_sql, or sqlite3's execute)."""
    return any(row[1] == column for row in execute(f"PRAGMA table_info({table})"))
