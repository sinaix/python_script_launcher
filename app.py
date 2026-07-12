"""
Python App Launcher — Web 后端
作为模块引入时: from python_script_launcher import create_app
直接运行时:     python app.py
"""
import ast
import asyncio
import json
import os
import re
import sys
import uuid
import io
import subprocess
import shutil
import threading
import queue
from pathlib import Path
from typing import Optional, Callable

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, FileResponse
import uvicorn

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _default_root():
    """确定用户脚本根目录。
    - frozen: 使用 sys._MEIPASS，其中通过 --add-data scripts;scripts
      带入了 scripts/ 子目录 (onefile 时为解包临时目录, onedir 时为 _internal 目录)。
    - 开发: 使用 launcher 所在目录，若自身位于 scripts/ 内则回到上一级。
    """
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)).resolve()
    p = Path(__file__).parent.resolve()
    return p.parent if p.name == "scripts" else p


def _default_static(root: Path):
    if getattr(sys, "frozen", False):
        meipass = Path(sys._MEIPASS)
        static = meipass / "static"
        if static.exists():
            return static
    return root / "static"


DEFAULT_ROOT = _default_root()

# 用户脚本根目录下真正扫描的子目录名 (按优先级)。若都不存在，则退回 root 本身。
SCRIPTS_SUBDIRS = ("scripts",)

# 只在浅层递归时忽略的目录
SKIP_DIRS = {
    "_uploads", "__pycache__", "dist", "build",
    ".venv", "venv", "env", ".env",
    "node_modules", ".git", ".idea", ".vscode",
    "_internal",  # PyInstaller onedir 结构，绝不进入
    "site-packages",
}
SKIP_FILES = {"app.py", "client.py", "make_exe.py", "publish.py", "tasks.py",
              "__init__.py", "__main__.py"}

# 快速前置过滤: 有 def main(...) 或 @task 装饰器时才做完整解析
_MAIN_RE = re.compile(rb"^\s*def\s+main\s*\(", re.MULTILINE)
_TASK_RE = re.compile(rb"^\s*@\s*(?:\w+\.)?task\b", re.MULTILINE)

# scan_scripts 缓存: {root_str: (signature, result)}
_SCAN_CACHE: dict = {}


class ParamInfo:
    def __init__(self, name, type_str="str", required=True, default=None, help_text=""):
        self.name = name
        self.type_str = type_str
        self.required = required
        self.default = default
        self.help_text = help_text

    def to_dict(self):
        return {"name": self.name, "type": self.type_str, "required": self.required,
                "default": self.default, "help": self.help_text}


class ScriptInfo:
    def __init__(self, name, path, docstring="", params=None,
                 has_file_param=False, task=None):
        self.name = name
        self.path = path
        self.docstring = docstring or "无说明"
        self.params = params or []
        self.has_file_param = has_file_param
        # task=None -> 兼容旧脚本 (runpy 运行, 需要 __main__ guard)
        # task="<task_name>" -> 新式脚本, 通过 @task 装饰器注册
        self.task = task

    def to_dict(self):
        return {
            "name": self.name,
            "path": self.path,
            "docstring": self.docstring,
            "params": [p.to_dict() for p in self.params],
            "has_file_param": self.has_file_param,
            "task": self.task,
        }


def _get_annotation_str(node) -> str:
    if node is None:
        return "str"
    try:
        return ast.unparse(node).strip()
    except Exception:
        return "str"


def _resolve_scan_dir(root: Path) -> Path:
    """在 root 下寻找真正的脚本目录：优先 root/scripts, 其次 root 本身。"""
    root = Path(root).resolve()
    for sub in SCRIPTS_SUBDIRS:
        candidate = root / sub
        if candidate.is_dir():
            return candidate
    return root


def _iter_script_files(scan_dir: Path):
    """浅层遍历脚本目录，跳过隐藏/构建/依赖目录与保留文件名。"""
    if not scan_dir.exists():
        return
    for py_file in scan_dir.rglob("*.py"):
        parts = py_file.relative_to(scan_dir).parts
        if any(part in SKIP_DIRS or part.startswith(".") for part in parts[:-1]):
            continue
        name = py_file.name
        if name in SKIP_FILES or name.startswith("_"):
            continue
        yield py_file


def _dir_signature(scan_dir: Path) -> tuple:
    """收集扫描目录中所有候选 .py 的 (path, mtime, size) 作为缓存 key。"""
    items = []
    for f in _iter_script_files(scan_dir):
        try:
            st = f.stat()
            items.append((str(f), st.st_mtime_ns, st.st_size))
        except OSError:
            continue
    items.sort()
    return tuple(items)


def scan_scripts(root: Path) -> dict:
    scan_dir = _resolve_scan_dir(Path(root))
    if not scan_dir.exists():
        return {}

    signature = _dir_signature(scan_dir)
    cache_key = str(scan_dir)
    cached = _SCAN_CACHE.get(cache_key)
    if cached and cached[0] == signature:
        return cached[1]

    scripts: dict = {}
    for py_file in _iter_script_files(scan_dir):
        try:
            raw = py_file.read_bytes()
        except OSError:
            continue
        has_task = bool(_TASK_RE.search(raw))
        has_main = bool(_MAIN_RE.search(raw))
        if not (has_task or has_main):
            continue
        try:
            source = raw.decode("utf-8", errors="replace")
            tree = ast.parse(source)
        except Exception:
            continue
        rel = py_file.relative_to(scan_dir)
        module_doc = ast.get_docstring(tree) or ""

        task_entries = _extract_task_entries(tree)
        if task_entries:
            for task_name, func_def in task_entries.items():
                params, has_file_param = _extract_params(func_def)
                key = f"{py_file.stem}.{task_name}" if len(task_entries) > 1 else py_file.stem
                doc = ast.get_docstring(func_def) or module_doc
                scripts[key] = ScriptInfo(
                    name=key,
                    path=str(rel),
                    docstring=doc[:300],
                    params=params,
                    has_file_param=has_file_param,
                    task=task_name,
                )
            continue

        # Fallback: legacy convention using `def main(...)` + __main__ guard.
        main_def = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "main":
                main_def = node
                break
        if main_def is None:
            continue
        params, has_file_param = _extract_params(main_def)
        doc = ast.get_docstring(main_def) or module_doc
        scripts[py_file.stem] = ScriptInfo(
            name=py_file.stem,
            path=str(rel),
            docstring=doc[:300],
            params=params,
            has_file_param=has_file_param,
        )
    _SCAN_CACHE[cache_key] = (signature, scripts)
    return scripts


def _extract_params(func_def) -> tuple:
    """Convert an ast.FunctionDef arg list into (params, has_file_param)."""
    args = func_def.args
    all_args = args.args
    defaults = args.defaults
    num_default = len(defaults)
    num_args = len(all_args)
    params = []
    has_file_param = False
    for i, arg in enumerate(all_args):
        if arg.arg in ("self", "cls"):
            continue
        type_str = _get_annotation_str(arg.annotation)
        d_idx = i - (num_args - num_default)
        if d_idx >= 0:
            try:
                default_val = ast.literal_eval(defaults[d_idx])
            except Exception:
                default_val = str(ast.unparse(defaults[d_idx])).strip()
            p = ParamInfo(arg.arg, type_str, False, default_val)
        else:
            p = ParamInfo(arg.arg, type_str, True)
        if any(kw in arg.arg.lower() for kw in ("file", "path", "upload")):
            has_file_param = True
        params.append(p)
    return params, has_file_param


def _extract_task_entries(tree) -> dict:
    """Return {task_name: FunctionDef} for every @task-decorated top-level function.

    Recognizes ``@task`` and ``@task(name=..., desc=...)`` (also ``@tasks.task``
    or ``@some_alias.task``). ``name=`` keyword overrides the function name.
    """
    entries: dict = {}
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for deco in node.decorator_list:
            explicit_name = None
            call = None
            if isinstance(deco, ast.Call):
                call = deco.func
                for kw in deco.keywords:
                    if kw.arg == "name":
                        try:
                            explicit_name = ast.literal_eval(kw.value)
                        except Exception:
                            explicit_name = None
                        break
            else:
                call = deco
            if isinstance(call, ast.Attribute):
                attr = call.attr
            elif isinstance(call, ast.Name):
                attr = call.id
            else:
                continue
            if attr != "task":
                continue
            task_name = explicit_name or node.name
            entries[str(task_name)] = node
            break
    return entries


def scan_dir_for(root: Path) -> Path:
    """外部调用：返回给定 root 对应的实际脚本目录（可能是 root/scripts）。"""
    return _resolve_scan_dir(Path(root))


class _LineWriter:
    """把 write() 拆成行, 立即投递到 queue, 支持无换行结尾的 flush."""
    def __init__(self, queue: "queue.Queue", tag: str):
        self._queue = queue
        self._tag = tag
        self._buf = ""

    def write(self, data):
        if not isinstance(data, str):
            data = str(data)
        self._buf += data
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._queue.put((self._tag, line))
        return len(data)

    def flush(self):
        if self._buf:
            self._queue.put((self._tag, self._buf))
            self._buf = ""

    def isatty(self):
        return False


async def _run_script_stream(script_path: Path, args_list: list):
    """在后台线程里以 runpy 方式执行脚本, 异步 yield ("OUT"/"ERR"/"EXIT", value).

    - 避免 exe 内启动子 python 进程（frozen 下每次会重新解包/加载依赖, 耗时数秒）。
    - 通过队列增量转发标准输出/错误, 让前端看到实时进度。
    """
    import queue as _queue_mod
    import runpy
    import contextlib

    out_queue: _queue_mod.Queue = _queue_mod.Queue()
    sentinel = object()

    def worker():
        old_stdout, old_stderr = sys.stdout, sys.stderr
        old_argv = sys.argv
        script_dir = str(script_path.parent.resolve())
        added_path = script_dir not in sys.path
        if added_path:
            sys.path.insert(0, script_dir)
        exit_code = 0
        try:
            sys.stdout = _LineWriter(out_queue, "OUT")
            sys.stderr = _LineWriter(out_queue, "ERR")
            sys.argv = [str(script_path)] + list(args_list)
            try:
                runpy.run_path(str(script_path), run_name="__main__")
            except SystemExit as e:
                exit_code = e.code if isinstance(e.code, int) else 1
            except Exception as e:
                import traceback
                sys.stderr.write(traceback.format_exc())
                exit_code = 1
            finally:
                # flush 剩余无换行 buffer
                try:
                    sys.stdout.flush(); sys.stderr.flush()
                except Exception:
                    pass
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr
            sys.argv = old_argv
            if added_path:
                try:
                    sys.path.remove(script_dir)
                except ValueError:
                    pass
            out_queue.put(("EXIT", exit_code))
            out_queue.put(sentinel)

    loop = asyncio.get_running_loop()
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    while True:
        item = await loop.run_in_executor(None, out_queue.get)
        if item is sentinel:
            break
        yield item


def _coerce_task_kwargs(spec_obj, raw: dict) -> dict:
    """Best-effort convert HTTP-form string values to the types declared in
    the TaskSpec params. Missing values keep the task's own defaults.
    """
    coerced: dict = {}
    lookup = {p.name: p for p in getattr(spec_obj, "params", [])}
    for key, value in raw.items():
        info = lookup.get(key)
        if info is None or value is None or value == "":
            coerced[key] = value
            continue
        type_str = info.type_str
        try:
            if type_str == "int":
                coerced[key] = int(value) if not isinstance(value, int) else value
            elif type_str == "float":
                coerced[key] = float(value) if not isinstance(value, float) else value
            elif type_str == "bool":
                if isinstance(value, bool):
                    coerced[key] = value
                else:
                    coerced[key] = str(value).lower() in ("1", "true", "yes", "on")
            else:
                coerced[key] = value
        except (TypeError, ValueError):
            coerced[key] = value
    return coerced


async def _run_task_stream(script_path: Path, task_name: str, kwargs: dict):
    """Import a script module and call its @task-registered function in-thread.

    Yields ("OUT" | "ERR" | "EXIT", value) tuples, same shape as
    _run_script_stream, so the SSE handler can be reused.
    """
    import queue as _queue_mod
    import importlib
    import importlib.util
    import traceback

    out_queue: _queue_mod.Queue = _queue_mod.Queue()
    sentinel = object()

    def worker():
        old_stdout, old_stderr = sys.stdout, sys.stderr
        script_dir = str(script_path.parent.resolve())
        added_path = script_dir not in sys.path
        if added_path:
            sys.path.insert(0, script_dir)
        exit_code = 0
        try:
            sys.stdout = _LineWriter(out_queue, "OUT")
            sys.stderr = _LineWriter(out_queue, "ERR")
            module_name = f"_launcher_task_{script_path.stem}"
            try:
                spec = importlib.util.spec_from_file_location(module_name, str(script_path))
                if spec is None or spec.loader is None:
                    raise ImportError(f"cannot load {script_path}")
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                registry = getattr(module, "__tasks__", None) or {}
                spec_obj = registry.get(task_name)
                if spec_obj is None:
                    raise KeyError(f"task not registered: {task_name}")
                spec_obj(**_coerce_task_kwargs(spec_obj, kwargs))
            except SystemExit as e:
                exit_code = e.code if isinstance(e.code, int) else 1
            except Exception:
                sys.stderr.write(traceback.format_exc())
                exit_code = 1
            finally:
                try:
                    sys.stdout.flush(); sys.stderr.flush()
                except Exception:
                    pass
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr
            if added_path:
                try:
                    sys.path.remove(script_dir)
                except ValueError:
                    pass
            out_queue.put(("EXIT", exit_code))
            out_queue.put(sentinel)

    loop = asyncio.get_running_loop()
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    while True:
        item = await loop.run_in_executor(None, out_queue.get)
        if item is sentinel:
            break
        yield item


def find_python(project_root: Path = None) -> str:
    """在 frozen 模式下仅返回自身路径（不依赖外部 Python）"""
    if not getattr(sys, "frozen", False):
        return sys.executable
    # frozen 模式下，我们不再需要外部 Python 来执行子脚本
    # 因为 run_script 会走进程内执行路径
    return sys.executable


def is_port_used(port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def create_app(
    root: str | Path = None,
    static_dir: str | Path = None,
    uploads_dir: str | Path = None,
    on_run: Optional[Callable] = None,
) -> FastAPI:
    project_root = Path(root).resolve() if root else DEFAULT_ROOT
    static = Path(static_dir).resolve() if static_dir else _default_static(project_root)
    uploads = Path(uploads_dir).resolve() if uploads_dir else project_root / "_uploads"
    uploads.mkdir(parents=True, exist_ok=True)

    python_bin = find_python(project_root)
    app = FastAPI(title="Python App Launcher")

    @app.get("/api/scripts")
    async def list_scripts(api_root: str = None):
        scan_root = Path(api_root).resolve() if api_root else project_root
        scripts = scan_scripts(scan_root)
        return {"root": str(scan_root), "scripts": [s.to_dict() for s in scripts.values()]}

    @app.post("/api/upload")
    async def upload_file(file: UploadFile = File(...)):
        file_id = f"{uuid.uuid4().hex[:12]}_{file.filename}"
        dest = uploads / file_id
        with open(dest, "wb") as f:
            content = await file.read()
            f.write(content)
        return {"file_id": file_id, "filename": file.filename, "size": len(content)}

    @app.post("/api/run")
    async def run_script(
        script: str = Form(...),
        args_json: str = Form("[]"),
        file_ids: str = Form(""),
        root: str = Form(""),
    ):
        scan_root = Path(root).resolve() if root else project_root
        scripts_dir_ = scan_dir_for(scan_root)
        scripts = scan_scripts(scan_root)
        if script not in scripts:
            return JSONResponse({"error": f"Unknown script: {script}"}, 404)
        meta = scripts[script]
        cmd = [python_bin, "-u", str(scripts_dir_ / meta.path)]

        parsed_args: dict = {}
        try:
            args_val = json.loads(args_json)
            if isinstance(args_val, dict):
                parsed_args = args_val
                for k, v in args_val.items():
                    if v is not None and v != "":
                        cmd.extend([f"--{k}", str(v)])
        except Exception:
            pass

        if file_ids:
            file_param = "filepath"
            for p in meta.params:
                if any(kw in p.name.lower() for kw in ("file", "path", "upload")):
                    file_param = p.name
                    break
            file_paths = []
            for fid in file_ids.split(","):
                fid = fid.strip()
                if fid:
                    fpath = uploads / fid
                    if fpath.exists():
                        file_paths.append(str(fpath))
            if file_paths:
                cmd.extend([f"--{file_param}"] + file_paths)
                parsed_args[file_param] = file_paths[0] if len(file_paths) == 1 else file_paths

        if on_run:
            on_run(script, cmd)

        async def stream_output():
            if getattr(sys, "frozen", False) or meta.task:
                # In-process execution:
                #   - frozen exe (avoids spawning a nested Python) or
                #   - task-based scripts (@task decorated, no __main__ guard).
                try:
                    script_path = scripts_dir_ / meta.path
                    exit_code = 0
                    if meta.task:
                        stream = _run_task_stream(script_path, meta.task, parsed_args)
                    else:
                        script_path_str = str(script_path)
                        extra_args = cmd[2:] if len(cmd) > 2 else []
                        if extra_args and extra_args[0] == script_path_str:
                            extra_args = extra_args[1:]
                        stream = _run_script_stream(script_path, extra_args)
                    async for tag, value in stream:
                        if tag == "EXIT":
                            exit_code = value
                            continue
                        if not value:
                            continue
                        yield f"data: [{tag}] {value}\n\n"
                    yield f"data: __EXIT__:{exit_code}\n\n"
                except asyncio.CancelledError:
                    yield "data: Cancelled\n\ndata: __EXIT__:1\n\n"
                except Exception as e:
                    yield f"data: Error: {e}\n\ndata: __EXIT__:1\n\n"
            else:
                try:
                    kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
                    env = os.environ.copy()
                    env["PYTHONIOENCODING"] = "utf-8"
                    kwargs["env"] = env
                    if sys.platform == "win32":
                        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
                    elif sys.platform != "win32":
                        kwargs["preexec_fn"] = os.setpgrp
                    proc = await asyncio.create_subprocess_exec(*cmd, cwd=str(scripts_dir_), **kwargs)
                    encoding = "utf-8"
                    async for chunk in _merge_streams(proc.stdout, proc.stderr, encoding):
                        yield f"data: {chunk}\n\n"
                    await proc.wait()
                    yield f"data: __EXIT__:{proc.returncode}\n\n"
                except asyncio.CancelledError:
                    yield "data: Cancelled\n\ndata: __EXIT__:1\n\n"
                except Exception as e:
                    yield f"data: Error: {e}\n\ndata: __EXIT__:1\n\n"
        return StreamingResponse(stream_output(), media_type="text/event-stream")

    @app.get("/", response_class=HTMLResponse)
    async def index():
        candidates = []
        if getattr(sys, "frozen", False):
            candidates.append(Path(sys._MEIPASS) / "static" / "index.html")
        candidates.extend([
            static / "index.html",
            project_root / "static" / "index.html",
        ])
        for f in candidates:
            if f.exists():
                return FileResponse(str(f), media_type="text/html")
        return HTMLResponse("<h1>index.html not found</h1>", status_code=404)

    app.state.project_root = project_root
    app.state.static_dir = static
    app.state.uploads_dir = uploads
    return app


async def _merge_streams(stdout, stderr, encoding="utf-8"):
    queue = asyncio.Queue()
    async def tag_stream(stream, tag):
        while True:
            line = await stream.readline()
            if not line:
                break
            text = line.decode(encoding, errors="replace").rstrip()
            if text:
                await queue.put(f"[{tag}] {text}")
        await queue.put(None)
    tasks = [asyncio.create_task(tag_stream(stdout, "OUT")),
             asyncio.create_task(tag_stream(stderr, "ERR"))]
    active = 2
    while active > 0:
        item = await queue.get()
        if item is None:
            active -= 1
        else:
            yield item
    for t in tasks:
        t.cancel()


app = create_app()

if __name__ == "__main__":
    found = scan_scripts(DEFAULT_ROOT)
    print(f"\n  Python App Launcher")
    print(f"  Project:   {DEFAULT_ROOT}")
    print(f"  Scripts:   {len(found)} 个")
    for name, info in found.items():
        print(f"    - {name}: {info.path}")

    port = 8765
    if is_port_used(port):
        print(f"  [!] Port {port} already in use, skipping\n")
    else:
        print(f"  http://localhost:{port}\n")
        uvicorn.run(app, host="0.0.0.0", port=port)
