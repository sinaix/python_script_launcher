"""
Python App Launcher - packager.

Usage from the repo root:
    python make_exe.py [--web] [--client] [--both] [--onefile] [--clean]

Design:
    - Default mode is --onedir (fast startup, one exe per <name>/ folder).
    - --onefile packs a single-file exe (easier to ship, slower cold start).
    - --clean drops build/<name> cache to force a full rebuild.
    - No import scanning: every third-party package in the current environment
      is passed to PyInstaller via `--collect-all` so the resulting exe is
      self-contained. Useful for shipping arbitrary user scripts.

Callable API:
    build_exe(entry, name, *, project=None, dist=None, static=None,
              noconsole=False, onefile=False, clean=False)
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from importlib.metadata import distributions
from pathlib import Path

PROJECT = Path.cwd()
DIST = PROJECT / "dist"
BUILD = PROJECT / "build"
STATIC = PROJECT / "static"

# Packages that should NOT be shipped inside the exe (build tooling & self).
SKIP_PACKAGES = {
    "pyinstaller", "pyinstaller-hooks-contrib", "altgraph", "pefile",
    "pywin32-ctypes", "setuptools", "pip", "wheel", "uv", "build",
    "pyproject-hooks", "packaging",
    "python-script-launcher",
}

# Files copied into the on-the-fly `python_script_launcher/` package so user
# scripts can `from python_script_launcher.tasks import task` inside the
# frozen exe (mirrors publish.py's wheel layout).
_STAGE_PACKAGE_FILES = (
    "app.py", "client.py", "tasks.py", "__init__.py", "__main__.py",
)
_STAGE_PACKAGE_NAME = "python_script_launcher"


def _norm(name: str) -> str:
    return (name or "").strip().lower().replace("_", "-")


def get_installed_packages():
    """Return sorted top-level import names of third-party packages installed
    in the current interpreter environment.
    """
    names = set()
    skip = {_norm(x) for x in SKIP_PACKAGES}
    for dist in distributions():
        pkg_name = (dist.metadata["Name"] or "").strip()
        if not pkg_name or _norm(pkg_name) in skip:
            continue
        top_level = dist.read_text("top_level.txt")
        if top_level:
            for line in top_level.splitlines():
                mod = line.strip()
                if mod and not mod.startswith("_"):
                    names.add(mod)
        else:
            names.add(pkg_name.replace("-", "_"))
    return sorted(names)


def _clean_target(name: str, dist_dir: Path, build_dir: Path, project: Path,
                  drop_cache: bool = False):
    targets = [dist_dir / f"{name}.exe", dist_dir / name, project / f"{name}.spec"]
    if drop_cache:
        targets.append(build_dir / name)
    for p in targets:
        if p.is_file():
            p.unlink()
        elif p.is_dir():
            shutil.rmtree(p, ignore_errors=True)


def _stage_launcher_package(project: Path) -> Path:
    """Materialize a temporary `python_script_launcher/` package next to the
    top-level source files so PyInstaller can pick it up via `--paths`.

    Returns the *root* directory to add to PyInstaller search paths; the
    caller is responsible for removing it once the build is done.
    """
    stage_root = Path(tempfile.mkdtemp(prefix="psl-exe-"))
    pkg_dir = stage_root / _STAGE_PACKAGE_NAME
    pkg_dir.mkdir(parents=True, exist_ok=True)
    for name in _STAGE_PACKAGE_FILES:
        src = project / name
        if src.exists():
            shutil.copy2(src, pkg_dir / name)
    return stage_root


def build_exe(entry, name, *, project=None, dist=None, static=None,
              noconsole=False, onefile=False, clean=False):
    """Build a single PyInstaller exe.

    Parameters
    ----------
    entry: str | Path
        Path to the entry .py file. Relative paths resolve against `project`.
    name: str
        Application name (produces <name>.exe or <name>/<name>.exe).
    project: Path | None
        Project root (defaults to the current working directory). Also used
        for build/ and spec placement.
    dist: Path | None
        Output directory (defaults to <project>/dist).
    static: Path | None
        If given and exists, is packaged as `--add-data <static>:static`.
        If None, defaults to <project>/static.
    noconsole, onefile, clean:
        PyInstaller options (`--noconsole`, `--onefile`, `--clean`).
    """
    project = Path(project).resolve() if project else PROJECT
    dist_dir = Path(dist).resolve() if dist else project / "dist"
    build_dir = project / "build"
    static_dir = Path(static).resolve() if static else project / "static"

    mode = "onefile" if onefile else "onedir"
    print(f"=== build {name} ({mode}) ===\n")
    icon = project / "icon.ico"
    icon_arg = str(icon) if icon.exists() else None

    _clean_target(name, dist_dir, build_dir, project, drop_cache=clean)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onefile" if onefile else "--onedir",
        "--name", name,
        "--distpath", str(dist_dir),
        "--workpath", str(build_dir),
        "--specpath", str(project),
    ]
    if clean:
        cmd.append("--clean")
    if noconsole:
        cmd.append("--noconsole")

    if static_dir.exists():
        cmd += ["--add-data", f"{static_dir}{os.pathsep}static"]
    scripts_dir = project / "scripts"
    if scripts_dir.exists():
        cmd += ["--add-data", f"{scripts_dir}{os.pathsep}scripts"]

    # Make both `tasks` (top-level) and `python_script_launcher.tasks`
    # (wheel-style dotted import) usable from user scripts inside the exe.
    # - `--paths <project>` lets `from tasks import task` resolve.
    # - We also stage a temporary `python_script_launcher/` package that
    #   mirrors publish.py wheel layout and add its parent to `--paths`, so
    #   `from python_script_launcher.tasks import task` resolves the same
    #   way it does when installed from the wheel.
    # If the caller already staged a python_script_launcher/ package into
    # `project` (e.g. via __main__.cmd_build), reuse it verbatim so we do
    # not end up with two competing copies of the same package on --paths.
    if (project / "python_script_launcher" / "__init__.py").exists():
        stage_root = None
    else:
        stage_root = _stage_launcher_package(project)
    try:
        cmd += ["--paths", str(project)]
        if stage_root is not None:
            cmd += ["--paths", str(stage_root)]
        if (project / "tasks.py").exists():
            cmd += ["--hidden-import", "tasks"]
        cmd += [
            "--hidden-import", _STAGE_PACKAGE_NAME,
            "--hidden-import", f"{_STAGE_PACKAGE_NAME}.tasks",
            "--collect-submodules", _STAGE_PACKAGE_NAME,
        ]

        for pkg in get_installed_packages():
            cmd += ["--collect-all", pkg]

        if icon_arg:
            cmd += ["--icon", icon_arg]

        entry_path = Path(entry)
        if not entry_path.is_absolute():
            entry_path = (project / entry_path).resolve()
        cmd.append(str(entry_path))

        print(f"  entry: {entry_path}")
        subprocess.run(cmd, check=True, cwd=str(project))
        out = f"{dist_dir}/{name}.exe" if onefile else f"{dist_dir}/{name}/{name}.exe"
        print(f"  [OK] {name} -> {out}\n")
    finally:
        if stage_root is not None:
            shutil.rmtree(stage_root, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description="Python App Launcher packager")
    parser.add_argument("--web", action="store_true", help="build web exe (app.py)")
    parser.add_argument("--client", action="store_true", help="build desktop exe (client.py)")
    parser.add_argument("--both", action="store_true", help="build both web and desktop")
    parser.add_argument("--onefile", action="store_true", help="single-file exe (slower start)")
    parser.add_argument("--clean", action="store_true", help="drop build/ cache")
    args = parser.parse_args()

    do_web = args.web or args.both or not (args.web or args.client)
    do_client = args.client or args.both or not (args.web or args.client)

    pkgs = get_installed_packages()
    kind = "onefile (single file, slower)" if args.onefile else "onedir (folder, faster)"
    print(f"\n  Python App Launcher packager")
    print(f"  mode: {kind}")
    print(f"  packages to bundle ({len(pkgs)}): {', '.join(pkgs)}\n")

    if do_web:
        build_exe("app.py", "PythonAppLauncher", noconsole=False,
                  onefile=args.onefile, clean=args.clean)
    if do_client and (PROJECT / "client.py").exists():
        build_exe("client.py", "PythonAppDesktop", noconsole=True,
                  onefile=args.onefile, clean=args.clean)

    print("=" * 40)
    print(f"  All done. Output: {DIST}")
    print("=" * 40)


if __name__ == "__main__":
    main()