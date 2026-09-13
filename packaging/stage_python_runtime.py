"""Stage a relocatable CPython + locked analysis wheels before Mach-O signing.

Run with the uv-managed build interpreter, not a framework/Homebrew Python.
The destination must not exist. All symlinks are flattened just like the sidecar;
licenses and wheel dist-info are retained. No build-machine site packages are copied.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import tempfile


def stage(destination: Path) -> None:
    source = Path(sys.base_prefix).resolve()
    if sysconfig.get_config_var("PYTHONFRAMEWORK") or not (source / "lib").is_dir():
        raise RuntimeError("Build with uv-managed standalone CPython, not a framework Python")
    if destination.exists() or destination.is_symlink():
        raise RuntimeError("Runtime staging destination must be new")
    root = Path(__file__).resolve().parent.parent
    shutil.copytree(source, destination, symlinks=False,
                    ignore=shutil.ignore_patterns("site-packages", "__pycache__"))
    python = destination / "bin" / "python3"
    if not python.is_file() or any(destination.rglob("*.framework")):
        raise RuntimeError("Standalone Python layout required")
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    with tempfile.TemporaryDirectory(prefix="arslan-runtime-") as temp:
        # Validate relocation BEFORE allowing installation into this copied prefix.
        subprocess.run([str(python), "-I", "-c",
                        "import sys,pathlib; assert pathlib.Path(sys.prefix).resolve() == "
                        "pathlib.Path(sys.argv[1]).resolve()", str(destination.resolve())],
                       cwd=temp, env={"PATH": "/usr/bin:/bin", "HOME": temp},
                       check=True, timeout=10)
        requirements = Path(temp) / "requirements.txt"
        subprocess.run(["uv", "export", "--frozen", "--only-group", "sandbox",
                        "--output-file", str(requirements)], cwd=root, env=env, check=True,
                       stdout=subprocess.DEVNULL)
        subprocess.run(["uv", "pip", "install", "--python", str(python),
                        "--require-hashes", "--no-build", "--link-mode", "copy",
                        "--break-system-packages",
                        "-r", str(requirements)], cwd=temp, env=env, check=True)
        # -I and a different cwd expose accidental build-tree/venv dependencies.
        subprocess.run([str(python), "-I", "-c",
                        "import sys, pathlib, ssl, sqlite3, numpy, pandas, matplotlib; "
                        "matplotlib.use('Agg'); import matplotlib.pyplot as p; "
                        "assert pathlib.Path(sys.prefix).resolve() == pathlib.Path(sys.argv[1]).resolve(); "
                        "assert pandas.DataFrame({'x':[1,2]}).x.sum() == 3; "
                        "p.plot([1,2]); p.savefig('canary.png'); "
                        "assert pathlib.Path('canary.png').stat().st_size > 0",
                        str(destination.resolve())], cwd=temp,
                       env={"PATH": "/usr/bin:/bin", "HOME": temp, "MPLCONFIGDIR": temp},
                       check=True, timeout=60)
    if any(p.is_symlink() for p in destination.rglob("*")):
        raise RuntimeError("Runtime contains symlinks; resource signing would be unstable")
    print(f"Verified standalone compute runtime: {destination}")


if __name__ == "__main__":
    stage(Path(sys.argv[1]).absolute())
