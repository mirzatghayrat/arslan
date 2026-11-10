"""Opt-in process-local mutations; no product file is edited and no shell text runs.

Load with -p tests.server.quoted_args_file_run_mutations and choose
--quoted-file-mutation. Select only this change's text-only regression file.
ALLOW-PROGRAM-PATHS selects every_program_path; ALLOW-FILE-SCRIPTS selects
interpreter_file_families; DROP-NAMED-COMMANDS selects named_rules_read.
"""
import importlib.machinery
import inspect
from pathlib import Path
import textwrap

import pytest

MODES = ("ALLOW-PROGRAM-PATHS", "ALLOW-FILE-SCRIPTS", "DROP-NAMED-COMMANDS",
         "FLATTEN-OPERANDS", "DROP-REFUSED-PREFIX", "REFUSE-NON-SCRIPT-SUBCOMMANDS",
         "DROP-SECURITY-PASSWORD-TUPLE", "DROP-GSUTIL-UPLOAD-TUPLE", "DROP-GH-API-TUPLE",
         "DROP-PROGRAM-ARITIES", "DROP-SECURITY-GLOBAL-PARSE", "DROP-ATTACHED-SHORT",
         "DROP-RAW-ASSIGNMENT", "DROP-FALLBACK-RULE", "DROP-CLUSTER-SPLIT",
         "LOWERCASE-OPTION-VALUES", "REMOVE-AWS-COLOR", "REMOVE-RCLONE-RETRIES",
         "REMOVE-RCLONE-BANDWIDTH", "REMOVE-S3CMD-ENCODING", "DROP-XURL-GLOBAL-PARSE",
         "REMOVE-AWS-PROFILE", "FLIP-GCLOUD-QUIET", "DROP-SECURITY-ATTACHED-PROMPT",
         "REMOVE-GSUTIL-OVERRIDE", "FLIP-CURL-SILENT",
         "DROP-CLUSTER-SEPARATE-VALUE", "DROP-VERCEL-OPERATION-FLAG", "DROP-END-BOUNDARY",
         "SENTINEL-AS-VALUE", "IMPORT-TRUST-FROM-FIXTURE",
         "SKIP-CURRENT-SOURCE-HASH", "SKIP-SOURCE-COMMITS",
         "COLLAPSE-DUPLICATE-KEYS", "FIRST-COMMIT-ONLY", "ORIGINAL-COMMIT-ONLY")
OPTION_MODES = frozenset(MODES[6:])
LOADER_MODES = frozenset(MODES[-7:])


def mutate_loader(source, mode):
    """Transform Python definitions in memory, including fresh scratch imports."""
    if mode == "COLLAPSE-DUPLICATE-KEYS":
        line = '    header = _header_value(json.loads(lines[1][2:], object_pairs_hook=_HeaderObject))\n'
        assert source.count(line) == 1
        return source.replace(line, '    header = json.loads(lines[1][2:])\n')
    if mode == "IMPORT-TRUST-FROM-FIXTURE":
        marker = "# END GENERATED SOURCE HASHES\n"
        assert source.count(marker) == 1
        return source.replace(marker, marker + (
            'SOURCE_SHA256 = json.loads(Path(__file__).with_name("quoted_args_baselines.txt")'
            '.read_text().splitlines()[1][2:])["source_sha256"]\n'))
    if mode in {"SKIP-SOURCE-COMMITS", "FIRST-COMMIT-ONLY", "ORIGINAL-COMMIT-ONLY"}:
        line = '    assert header["source_commits"] == SOURCE_COMMITS, "Unexpected baseline sources"\n'
        assert source.count(line) == 1
        replacement = ""
        if mode != "SKIP-SOURCE-COMMITS":
            key = "main" if mode == "FIRST-COMMIT-ONLY" else "original"
            replacement = (f'    assert header["source_commits"]["{key}"] == SOURCE_COMMITS["{key}"], '
                           '"Unexpected baseline sources"\n')
        return source.replace(line, replacement)
    start = source.index("    # The current source is independently pinned")
    end = source.index("\n\ndef decode", start)
    if mode == "SKIP-CURRENT-SOURCE-HASH":
        return source[:start] + source[end:]
    # Restore the previous comparison, including its string-sentinel collision.
    begin = source.index("    # Complete both directions of membership")
    old = '''    for source in sorted(SOURCE_SHA256.keys() | recorded.keys()):
        expected = SOURCE_SHA256.get(source, {})
        actual = recorded.get(source, {})
        assert source in SOURCE_SHA256 and isinstance(actual, dict), (
            f"Baseline source hash mismatch: {source}/<mapping>: expected {expected!r}, recorded {actual!r}")
        for name in sorted(expected.keys() | actual.keys()):
            wanted, found = expected.get(name, "<absent>"), actual.get(name, "<missing>")
            assert wanted == found, (
                f"Baseline source hash mismatch: {source}/{name}: expected {wanted}, recorded {found}")
'''
    return source[:begin] + old + source[start:]


def install_loader_mutation(config, mode):
    original = importlib.machinery.SourceFileLoader.get_code
    def get_code(loader, fullname):
        if Path(loader.path).name == "quoted_args_baseline_data.py":
            source = mutate_loader(Path(loader.path).read_text(), mode)
            return compile(source, loader.path, "exec")
        return original(loader, fullname)
    patch = pytest.MonkeyPatch()
    patch.setattr(importlib.machinery.SourceFileLoader, "get_code", get_code)
    config.add_cleanup(patch.undo)


def pytest_addoption(parser):
    parser.addoption("--quoted-file-mutation", choices=MODES)


def pytest_configure(config):
    from server.services import shell_grammar as sg, terminal_policy as tp
    mode = config.getoption("--quoted-file-mutation")
    if mode is None:
        raise pytest.UsageError("choose --quoted-file-mutation when loading this plugin")
    if mode in LOADER_MODES:
        install_loader_mutation(config, mode)
        return
    if mode == "DROP-CLUSTER-SEPARATE-VALUE":
        source = inspect.getsource(tp._fully_accounted)
        assert "consumes = offset == len(word)" in source
        source = source.replace("consumes = offset == len(word)", "consumes = False")
        exec(compile(source, "<DROP-CLUSTER-SEPARATE-VALUE>", "exec"), vars(tp))
    elif mode == "DROP-VERCEL-OPERATION-FLAG":
        original_dispatch = tp._dispatch_args
        tp._dispatch_args = lambda program, args: (original_dispatch(program, args)[0], frozenset())
    elif mode == "DROP-END-BOUNDARY":
        original_dispatch = tp._dispatch_args
        def dispatch(program, args):
            stripped, operations = original_dispatch(program, args)
            return stripped, operations | (set(args) & tp._OPERATION_FLAGS[program])
        tp._dispatch_args = dispatch
    elif mode == "DROP-FALLBACK-RULE":
        tp._fully_accounted = lambda program, args: True
    elif mode.startswith("REMOVE-"):
        program, option = {
            "REMOVE-AWS-COLOR": ("aws", "--color"),
            "REMOVE-RCLONE-RETRIES": ("rclone", "--retries"),
            "REMOVE-RCLONE-BANDWIDTH": ("rclone", "--bwlimit"),
            "REMOVE-S3CMD-ENCODING": ("s3cmd", "--encoding"),
            "REMOVE-AWS-PROFILE": ("aws", "--profile"),
            "REMOVE-GSUTIL-OVERRIDE": ("gsutil", "-o"),
        }[mode]
        tp._OPTION_VALUES[program] -= {option}
    elif mode in {"FLIP-GCLOUD-QUIET", "FLIP-CURL-SILENT"}:
        program, flag = ("gcloud", "--quiet") if mode == "FLIP-GCLOUD-QUIET" else ("curl", "-s")
        tp._OPTION_VALUES[program] |= {flag}
    elif mode == "DROP-CLUSTER-SPLIT":
        def verb(args, values=frozenset()):
            i = 0
            while i < len(args) and args[i].startswith("-"):
                if args[i] == "--":
                    return args[i + 1:]
                i += 2 if args[i] in values else 1
            return args[i:]
        tp._verb = verb
    elif mode == "LOWERCASE-OPTION-VALUES":
        original_uploads = tp._uploads
        tp._uploads = lambda program, args: original_uploads(program, tuple(word.lower() for word in args))
    elif mode == "DROP-XURL-GLOBAL-PARSE":
        original_verb = tp._verb
        tp._verb = lambda args, values=frozenset(): args if values == tp._OPTION_VALUES["xurl"] else original_verb(args, values)
    elif mode == "DROP-SECURITY-ATTACHED-PROMPT":
        original_security = tp._security_verb
        tp._security_verb = lambda args: args if args and args[0].startswith("-p") and len(args[0]) > 2 else original_security(args)
    elif mode in {"DROP-SECURITY-PASSWORD-TUPLE", "DROP-GSUTIL-UPLOAD-TUPLE", "DROP-GH-API-TUPLE"}:
        original_rules = tp._named_rules
        def rules(words):
            found = original_rules(words)
            program, args = words[0].lower(), words[1:]
            if mode == "DROP-SECURITY-PASSWORD-TUPLE" and program == "security":
                operation = tp._security_verb(args)
                if operation and operation[0] in {"find-generic-password", "find-internet-password"}:
                    found.discard("keychain-secrets")
            elif mode == "DROP-GSUTIL-UPLOAD-TUPLE" and program == "gsutil":
                found.discard("upload")
            elif mode == "DROP-GH-API-TUPLE" and program == "gh" and args[:1] == ("api",):
                found.discard("publish")
            return found
        tp._named_rules = rules
    elif mode == "DROP-PROGRAM-ARITIES":
        # Restore the three conflicting entries from the shared value tables.
        for program, flag in (("curl", "-O"), ("wget", "-H"), ("gsutil", "-m")):
            tp._OPTION_VALUES[program] |= {flag}
    elif mode == "DROP-SECURITY-GLOBAL-PARSE":
        tp._security_verb = lambda args: args
    elif mode in {"DROP-ATTACHED-SHORT", "DROP-RAW-ASSIGNMENT"}:
        original_options = tp._options
        def options(args, values):
            # Drop only recognition of these attached forms; separate values,
            # raw matching and every unrelated tuple operation remain intact.
            args = tuple("--unrecognized" if (
                mode == "DROP-ATTACHED-SHORT" and len(word) > 2 and word[:2] in {"-X", "-f", "-F"}
                or mode == "DROP-RAW-ASSIGNMENT" and word.startswith("--raw=")) else word for word in args)
            return original_options(args, values)
        tp._options = options
    elif mode == "DROP-NAMED-COMMANDS":
        tp._command_words = lambda text: ()
    elif mode == "DROP-REFUSED-PREFIX":
        tp._command_words = lambda text: sg.read(text).commands
    elif mode == "REFUSE-NON-SCRIPT-SUBCOMMANDS":
        sg._NON_SCRIPT_SUBCOMMANDS = {}
    elif mode == "FLATTEN-OPERANDS":
        def flattened(words):
            command = " ".join(words)
            found = {key for key, pattern, _, masked in tp._FORBID_C
                     if not masked and key != "arslan-keys" and pattern.match(command)}
            found.update(key for key, pattern, _ in tp._ASK_C if pattern.match(command))
            if ((tp._DELETE_LINE.match(command) or tp._FIND_DELETE.match(command))
                    and tp._deletes_outside((command,))):
                found.add("delete-outside")
            return found
        tp._named_rules = flattened
    elif mode == "ALLOW-PROGRAM-PATHS":
        source = textwrap.dedent(inspect.getsource(sg._Reader._started))
        source = source.replace('if "/" in name:', 'if False:', 1)
        namespace = {}
        exec(compile(source, "<ALLOW-PROGRAM-PATHS>", "exec"), vars(sg), namespace)
        sg._Reader._started = namespace["_started"]
    else:
        original = sg._Reader._program
        def program(self, base, args):
            if sg._INTERPRETER.fullmatch(base) and sg._names_something(args) and args[0].text != "eval":
                return
            return original(self, base, args)
        sg._Reader._program = program


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    mode = config.getoption("--quoted-file-mutation")
    if mode in OPTION_MODES:
        if any(item.path.name not in {"test_quoted_args_file_run.py", "quoted_args_file_run_evidence.py"} for item in items):
            raise pytest.UsageError("select only the text-only regression or evidence module")
        return
    expected = {
        "ALLOW-PROGRAM-PATHS": "test_every_program_path_is_unread",
        "ALLOW-FILE-SCRIPTS": "test_interpreter_file_families_are_unread",
        "DROP-NAMED-COMMANDS": "test_named_rules_read_quoted_words",
        "FLATTEN-OPERANDS": "test_same_program_operands_keep_their_roles",
        "DROP-REFUSED-PREFIX": "test_quoted_rules_hold_before_every_refused_tail",
        "REFUSE-NON-SCRIPT-SUBCOMMANDS": "test_non_script_subcommands_stay_understood",
    }[mode]
    if any(item.path.name != "test_quoted_args_file_run.py" or item.originalname != expected for item in items):
        raise pytest.UsageError("select only the mutation's named text-only family")
