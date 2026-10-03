"""List the Reminders lists the bench created (names starting with the bench
prefixes: the comparison rounds and the 0.1.52 acceptance runs). Deleting them
deletes the user's data: only with --delete --yes, which the user runs themselves."""
import subprocess
import sys

PREFIXES = ("对比测试-", "验收-0152-")
_LIST = "Application('Reminders').lists().map(l => l.name()).join('\\n')"
_DELETE = "function run(a){const app=Application('Reminders');app.lists.whose({name:a[0]})()[0].delete();}"


def bench_lists() -> list[str]:
    out = subprocess.run(["osascript", "-l", "JavaScript", "-e", _LIST], capture_output=True, text=True, check=True)
    return [n for n in out.stdout.splitlines() if n.startswith(PREFIXES)]


if __name__ == "__main__":
    names = bench_lists()
    print("\n".join(names) or "(no bench lists)")
    if names and sys.argv[1:] == ["--delete", "--yes"]:
        for name in names:
            subprocess.run(["osascript", "-l", "JavaScript", "-e", _DELETE, name], check=True)
        print(f"deleted {len(names)} list(s)")
