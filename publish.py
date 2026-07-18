"""
Python App Launcher - Publish helper.
Usage:
    python publish.py [--version 1.2.3] [--wheel] [--exe] [--zip] [--tag]

Design:
- Single source of truth lives in the repo root (app.py, client.py,
  tasks.py, __init__.py, __main__.py, static/, scripts/).
- Wheel builds are staged in a temporary directory containing a synthesized
  `python_script_launcher/` package. No sibling package dir is maintained.
- `python -m build` reads a temp pyproject.toml over that staged tree.
- Artifacts are written back to <repo>/dist.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

PROJECT = Path(__file__).parent.resolve()
DIST = PROJECT / "dist"

PACKAGE_NAME = "python_script_launcher"
DIST_NAME = "python-script-launcher"

# Files/directories copied from repo root into the staged wheel package
SOURCE_FILES = ["app.py", "client.py", "make_exe.py", "tasks.py", "__init__.py", "__main__.py"]
SOURCE_DIRS = ["static", "scripts"]
EXTRA_ROOT_FILES = ["README.md", "LICENSE", "VERSION"]


def _run(cmd, cwd=None, check=True):
    print(f"  $ {' '.join(cmd) if isinstance(cmd, list) else cmd}")
    r = subprocess.run(cmd, cwd=str(cwd or PROJECT), text=True)
    if r.returncode != 0 and check:
        print(f"  [ERROR] command failed (exit {r.returncode})")
        sys.exit(r.returncode)
    return r


def get_version() -> str:
    return (PROJECT / "VERSION").read_text(encoding="utf-8").strip()


def set_version(version: str):
    (PROJECT / "VERSION").write_text(version, encoding="utf-8")
    print(f"  version -> {version}")


def _stage_package(stage_root: Path, version: str) -> Path:
    """Materialize an isolated project tree with `python_script_launcher/` layout."""
    pkg_dir = stage_root / PACKAGE_NAME
    pkg_dir.mkdir(parents=True, exist_ok=True)

    for name in SOURCE_FILES:
        src = PROJECT / name
        if src.exists():
            shutil.copy2(src, pkg_dir / name)

    for name in SOURCE_DIRS:
        src = PROJECT / name
        if not src.exists():
            continue
        shutil.copytree(src, pkg_dir / name, dirs_exist_ok=True)

    # VERSION lives at project root so runtime code can read it too.
    (stage_root / "VERSION").write_text(version, encoding="utf-8")

    for name in EXTRA_ROOT_FILES:
        src = PROJECT / name
        if src.exists() and name != "VERSION":
            shutil.copy2(src, stage_root / name)

    _write_pyproject(stage_root, version)
    return pkg_dir


def _write_pyproject(stage_root: Path, version: str):
    """Emit a minimal pyproject.toml so setuptools picks up only the staged package."""
    content = f'''[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "{DIST_NAME}"
version = "{version}"
description = "Package Python scripts into standalone exe (Web + desktop client)."
license = "MIT"
readme = "README.md"
requires-python = ">=3.11"
keywords = ["pyinstaller", "packaging", "exe", "launcher", "scripts"]
classifiers = [
    "Development Status :: 4 - Beta",
    "Intended Audience :: Developers",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Topic :: Software Development :: Build Tools",
]
dependencies = [
    "fastapi>=0.100.0",
    "python-multipart>=0.0.32",
    "uvicorn[standard]>=0.20.0",
    "requests>=2.34.2",
    "pyinstaller>=6.0",
    "pywebview>=4.0",
]

[project.optional-dependencies]
desktop = ["pywebview>=4.0"]
build = ["pyinstaller>=6.0", "build>=1.0"]
all = ["pywebview>=4.0", "pyinstaller>=6.0", "build>=1.0"]

[project.scripts]
launcher = "{PACKAGE_NAME}.__main__:main"

[tool.setuptools.packages.find]
include = ["{PACKAGE_NAME}", "{PACKAGE_NAME}.*"]

[tool.setuptools.package-data]
"{PACKAGE_NAME}" = [
    "app.py", "client.py", "make_exe.py", "tasks.py",
    "static/**/*",
    "scripts/**/*.py",
]
'''
    (stage_root / "pyproject.toml").write_text(content, encoding="utf-8", newline="\n")


def build_wheel():
    print("\n[wheel] Building sdist + wheel from staged source...")
    version = get_version()
    DIST.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="psl-wheel-") as tmp:
        stage = Path(tmp)
        _stage_package(stage, version)
        _run(
            [sys.executable, "-m", "build",
             "--sdist", "--wheel", "--no-isolation",
             "--outdir", str(DIST)],
            cwd=stage,
        )
    for a in sorted(DIST.glob(f"{PACKAGE_NAME}-{version}*")):
        if a.suffix in (".whl", ".gz"):
            print(f"  [OK] {a.name} ({a.stat().st_size // 1024} KB)")


def build_exe():
    print("\n[exe] Building exe via make_exe.py...")
    _run([sys.executable, "make_exe.py", "--both"])
    for d in DIST.iterdir():
        if d.is_dir() and (d / f"{d.name}.exe").exists():
            print(f"  [OK] {d}/{d.name}.exe")


def _iter_release_items(version: str):
    yield PROJECT / "README.md"
    yield PROJECT / "VERSION"
    lic = PROJECT / "LICENSE"
    if lic.exists():
        yield lic
    for whl in DIST.glob(f"{PACKAGE_NAME}-{version}*.whl"):
        yield whl
    for tar in DIST.glob(f"{PACKAGE_NAME}-{version}*.tar.gz"):
        yield tar
    for d in DIST.iterdir():
        if d.is_dir() and (d / f"{d.name}.exe").exists():
            yield d


def make_zip(version: str) -> Path:
    print("\n[zip] Bundling release archive...")
    zip_path = DIST / f"PythonAppLauncher-{version}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in _iter_release_items(version):
            if not item.exists():
                continue
            if item.is_file():
                zf.write(item, arcname=f"PythonAppLauncher-{version}/{item.name}")
            else:
                base = item.name
                for p in item.rglob("*"):
                    if p.is_file():
                        rel = p.relative_to(item)
                        zf.write(p, arcname=f"PythonAppLauncher-{version}/{base}/{rel}")
    print(f"  [OK] {zip_path.name} ({zip_path.stat().st_size // 1024} KB)")
    return zip_path


def git_tag(version: str):
    print(f"\n[git] Tag v{version}...")
    for cmd in [
        ["git", "add", "-A"],
        ["git", "commit", "-m", f"release: v{version}"],
        ["git", "tag", f"v{version}"],
        ["git", "push"],
        ["git", "push", "--tags"],
    ]:
        _run(cmd, check=False)


def main():
    parser = argparse.ArgumentParser(description="Build wheel + exe from single source tree")
    parser.add_argument("--version", "-v", help="Set new VERSION before building")
    parser.add_argument("--wheel", action="store_true", help="Only build wheel/sdist")
    parser.add_argument("--exe", action="store_true", help="Only build exe")
    parser.add_argument("--zip", action="store_true", help="Bundle a release zip")
    parser.add_argument("--tag", action="store_true", help="Commit + git tag + push")
    args = parser.parse_args()

    if args.version:
        set_version(args.version)
    version = get_version()

    do_wheel = args.wheel or (not args.wheel and not args.exe)
    do_exe = args.exe or (not args.wheel and not args.exe)

    print("=" * 54)
    print(f"  Publish  v{version}  wheel={do_wheel} exe={do_exe} zip={args.zip}")
    print("=" * 54)

    if do_wheel:
        build_wheel()
    if do_exe:
        build_exe()
    if args.zip:
        make_zip(version)
    if args.tag:
        git_tag(version)

    print("\n" + "=" * 54)
    print(f"  Done. Artifacts in {DIST}")
    print("=" * 54)


if __name__ == "__main__":
    main()
