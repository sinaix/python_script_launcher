"""Python App Launcher - Package Python scripts into standalone exe.

This package is normally built by publish.py from the top-level source files
(app.py, client.py, tasks.py, __init__.py, __main__.py). Importing this
package makes the sibling `app` / `client` / `launcher` modules available under
their bare names, so `from app import ...` works both from the repo root and
from an installed wheel.
"""
import os
import sys
from pathlib import Path

# Make sibling modules (app.py, client.py, tasks.py) importable by bare
# name, matching how they are used from the repo root and inside a frozen exe.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

# When installed from a wheel, the version comes from package metadata.
# When running from the source repo, fall back to the VERSION file at the
# project root (which publish.py maintains).
try:
    from importlib.metadata import version as _pkg_version, PackageNotFoundError
    try:
        __version__ = _pkg_version("python-script-launcher")
    except PackageNotFoundError:
        _version_file = Path(_here).parent / "VERSION"
        __version__ = _version_file.read_text(encoding="utf-8").strip() if _version_file.exists() else "0.0.0"
except Exception:
    __version__ = "0.0.0"

from app import create_app, scan_scripts, find_python, ScriptInfo, ParamInfo  # noqa: E402
from client import start_desktop  # noqa: E402
from tasks import task, run_cli, collect_tasks, TaskSpec, TaskParam  # noqa: E402

__all__ = [
    "create_app",
    "scan_scripts",
    "find_python",
    "start_desktop",
    "ScriptInfo",
    "ParamInfo",
    "task",
    "run_cli",
    "collect_tasks",
    "TaskSpec",
    "TaskParam",
    "__version__",
]
