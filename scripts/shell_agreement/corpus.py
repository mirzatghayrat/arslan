"""Where the commands come from: the repository's own tests (default) or a file."""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEST_DIRS = (ROOT / "tests" / "server", ROOT / "tests")


def _rows(values: ast.expr, constants: dict) -> list:
    if isinstance(values, ast.Name):
        return list(constants.get(values.id, ()))
    try:
        return list(ast.literal_eval(values))
    except (ValueError, TypeError, SyntaxError):
        pass
    rows = []
    for element in getattr(values, "elts", ()):
        try:
            rows.append(eval(compile(ast.Expression(element), "<parametrize>", "eval"), {"__builtins__": {}}))
        except Exception:   # noqa: BLE001 — a row that needs the module's names is left out
            continue
    return rows


def from_tests(folders: tuple[Path, ...] = TEST_DIRS) -> list[str]:
    """Every string a test file passes as its `command` parameter, read from the source (not imported:
    importing a test module would build the server's settings outside pytest's guards)."""
    commands: dict[str, None] = {}
    for folder in folders:
        for path in sorted(folder.glob("test_*.py")):
            tree = ast.parse(path.read_text("utf-8"))
            constants: dict = {}
            for node in tree.body:
                if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                    try:
                        constants[node.targets[0].id] = ast.literal_eval(node.value)
                    except (ValueError, TypeError):
                        continue
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "parametrize" and len(node.args) >= 2):
                    continue
                try:
                    names = ast.literal_eval(node.args[0])
                except (ValueError, TypeError):
                    continue
                names = [n.strip() for n in names.split(",")] if isinstance(names, str) else list(names)
                if "command" not in names:
                    continue
                index = names.index("command")
                for row in _rows(node.args[1], constants):
                    command = row[index] if len(names) > 1 else row
                    if isinstance(command, str) and command.strip():
                        commands.setdefault(command)
    return list(commands)


def from_file(path: Path) -> list[str]:
    """One command per line, or JSON lines with a "command" field (a line's `\\n` escapes stay JSON)."""
    commands: dict[str, None] = {}
    for line in path.read_text("utf-8").splitlines():
        if not line.strip():
            continue
        if line.lstrip().startswith("{"):
            try:
                command = json.loads(line).get("command")
            except (ValueError, AttributeError):
                continue
        else:
            command = line
        if isinstance(command, str) and command.strip():
            commands.setdefault(command)
    return list(commands)
