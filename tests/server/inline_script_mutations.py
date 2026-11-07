"""Opt-in measurement/mutation controls; generated strings never leave assess."""


def pytest_addoption(parser):
    parser.addoption('--inline-measure', choices=('main', 'head'))
    parser.addoption('--inline-mutation', choices=('DROP-REACH', 'DROP-STARTUP', 'ASK-ALL', 'ONLY-MOST-LINES', 'DRIFT-GENERATOR'))


def pytest_configure(config):
    mode = config.getoption('--inline-mutation')
    if mode is None:
        return
    import re
    from server.services import terminal_policy as tp
    from tests.server import test_inline_script_asks as gates
    if mode == 'DROP-REACH':
        tp._SCRIPT_REACH = re.compile(r'(?!)')
    elif mode == 'DROP-STARTUP':
        tp._script_names_protected = lambda text: False
    elif mode == 'ASK-ALL':
        tp.assess = lambda text: tp.Assessment('ask', 'mutation', 'all text asks')
    elif mode == 'ONLY-MOST-LINES':
        tp._split_forms = lambda text: (max(tp._forms(text), key=lambda form: form.count('\n')),)
    else:
        original = gates.text_for
        gates.text_for = lambda spec: original(spec) + '\necho neutral'


def pytest_collection_modifyitems(config, items):
    mode = config.getoption('--inline-mutation')
    if not mode:
        return
    selected, deselected = [], []
    families = {'DROP-REACH': {'network-import', 'process-import'}, 'DROP-STARTUP': {'protected-startup'},
                'ASK-ALL': {'harmless', 'data'},
                'ONLY-MOST-LINES': {'network-import', 'process-import', 'protected-startup'}}
    for item in items:
        spec = getattr(getattr(item, 'callspec', None), 'params', {}).get('spec')
        keep = False
        if mode == 'DRIFT-GENERATOR':
            keep = item.originalname == 'test_frozen_main_inputs'
        elif spec:
            keep = spec[0] in families[mode] and spec[1] in {'bash', 'watch', 'nested-c'} and spec[4] == 'none'
        if keep:
            selected.append(item)
        else:
            deselected.append(item)
    items[:] = selected
    config.hook.pytest_deselected(items=deselected)
