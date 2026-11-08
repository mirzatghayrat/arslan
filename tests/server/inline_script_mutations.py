"""Opt-in measurement/mutation controls; generated strings never leave assess.

Mutations run the entire default sample, including its full-input digest.
ARSLAN_INLINE_FULL=1 also applies here when an exhaustive mutation run is wanted.
"""


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
