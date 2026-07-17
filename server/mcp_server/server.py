"""Build the inbound FastMCP server (spec §Architecture 1 + Q1).

Read-only, metadata-only. stateless_http=True → every request is independently
re-authorized (disable/rotate is immediate). json_response=True → plain JSON
responses (no SSE), which real MCP clients accept and tests can assert directly.
transport_security is loopback-only with DNS-rebinding protection on."""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from server.mcp_server import tools

# With enable_dns_rebinding_protection an EMPTY allowed_hosts rejects EVERY request
# (421). v1 is localhost-only by design; cross-network exposure is the user's
# reverse-proxy/TLS responsibility (spec §Known limitations).
LOOPBACK_HOSTS = ["127.0.0.1", "127.0.0.1:*", "localhost", "localhost:*", "[::1]", "[::1]:*"]


def build_mcp_server() -> FastMCP:
    mcp = FastMCP(
        name="arslan",
        instructions="Arslan personal AI orchestrator — read-only metadata tools "
                     "(spawns, capabilities, run status).",
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",  # mounted at /mcp-server → endpoint is /mcp-server/
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=LOOPBACK_HOSTS,
            allowed_origins=[],  # any present browser Origin is rejected (DNS-rebinding defense)
        ),
    )
    mcp.add_tool(
        tools.list_spawns, name="list_spawns",
        description="List the user's agents (spawns): id, name, domain, capabilities, "
                    "and equipment keys. Metadata only — no persona or output bodies.")
    mcp.add_tool(
        tools.list_capabilities, name="list_capabilities",
        description="List available built-in tools, connected MCP servers, and skills. "
                    "Labels/descriptions only.")
    mcp.add_tool(
        tools.get_run_status, name="get_run_status",
        description="Get run status/metadata by run_id, or the recent runs of a spawn by "
                    "spawn_id. Status/tokens/model only — never the run's output.")
    return mcp
