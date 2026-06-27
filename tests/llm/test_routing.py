from arslan.llm import routing

CFGS = [
    {"id": 1, "provider": "anthropic", "model": "claude-sonnet-4-6", "base_url": "", "is_primary": True},
    {"id": 2, "provider": "qwen", "model": "qwen-max", "base_url": "", "is_primary": False},
    {"id": 3, "provider": "deepseek", "model": "deepseek-chat", "base_url": "", "is_primary": False},
]


def test_judgment_role_always_primary():
    for strat in ("cost", "balanced", "performance"):
        assert routing.select("router", strat, CFGS, "en")["id"] == 1
        assert routing.select("converse", strat, CFGS, "en")["id"] == 1
        assert routing.select("critical", strat, CFGS, "en")["id"] == 1


def test_single_strategy_always_primary():
    assert routing.select("execute", "single", CFGS, "en")["id"] == 1


def test_cost_worker_picks_cheapest():
    assert routing.select("execute", "cost", CFGS, "en")["id"] == 3


def test_performance_worker_picks_strongest():
    assert routing.select("execute", "performance", CFGS, "en")["id"] == 1


def test_language_fit_breaks_a_tie():
    two = [
        {"id": 1, "provider": "anthropic", "model": "x", "base_url": "", "is_primary": True},
        {"id": 2, "provider": "qwen", "model": "y", "base_url": "", "is_primary": False},
    ]
    assert routing.select("execute", "balanced", two, "zh")["id"] == 2
    assert routing.select("execute", "balanced", two, "en")["id"] == 1


def test_fewer_than_two_configs_returns_primary():
    one = [CFGS[0]]
    assert routing.select("execute", "cost", one, "en")["id"] == 1


def test_suggest_primary_quality_first():
    assert routing.suggest_primary(CFGS, "zh")["id"] == 1


def test_execute_role_routes_to_stronger_non_primary_model():
    """Tool-forcing spec §5: the execute (worker) role can be served by a STRONGER
    non-primary model. With a weak primary (ollama: reasoning 6, tool_calling 5) and a
    strong non-primary (anthropic: reasoning 10, tool_calling 9), the `performance`
    strategy must route execute to the strong NON-PRIMARY model — proving the per-role
    leverage already exists in the routing engine."""
    configs = [
        {"id": 1, "provider": "ollama", "model": "llama3", "base_url": "", "is_primary": True},
        {"id": 2, "provider": "anthropic", "model": "claude-opus-4-8", "base_url": "", "is_primary": False},
    ]
    chosen = routing.select("execute", "performance", configs, "en")
    assert chosen is not None
    assert chosen["is_primary"] is False
    assert chosen["id"] == 2
    assert chosen["provider"] == "anthropic"
