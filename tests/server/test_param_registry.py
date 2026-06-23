from arslan.core.param_registry import DEFAULT_REGISTRY, ParamRegistry


class _Spawn:
    def __init__(self):
        self.system_prompt = "old"


def test_default_registry_system_prompt_get_set():
    s = _Spawn()
    assert DEFAULT_REGISTRY.fields() == ["system_prompt"]
    assert DEFAULT_REGISTRY.get("system_prompt", s) == "old"
    DEFAULT_REGISTRY.set("system_prompt", s, "new")
    assert s.system_prompt == "new"


def test_register_additional_field():
    r = ParamRegistry()
    r.register("x", get=lambda o: o.system_prompt, set=lambda o, v: setattr(o, "system_prompt", v))
    s = _Spawn()
    r.set("x", s, "z")
    assert r.get("x", s) == "z"
