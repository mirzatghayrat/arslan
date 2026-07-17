from server.mcp_server.server import build_mcp_server


def test_transport_security_is_loopback_and_rebinding_on():
    mcp = build_mcp_server()
    ts = mcp.settings.transport_security
    assert ts.enable_dns_rebinding_protection is True
    assert ts.allowed_origins == []                 # any browser Origin rejected
    assert "127.0.0.1" in ts.allowed_hosts and "localhost:*" in ts.allowed_hosts
    assert mcp.settings.stateless_http is True and mcp.settings.json_response is True


async def test_lists_exactly_three_tools_with_valid_input_schema():
    mcp = build_mcp_server()
    listed = await mcp.list_tools()
    names = {t.name for t in listed}
    assert names == {"list_spawns", "list_capabilities", "get_run_status"}
    for t in listed:
        assert isinstance(t.inputSchema, dict)
        assert t.inputSchema.get("type") == "object"     # valid JSON-Schema object
        assert t.description                              # every tool documents itself
