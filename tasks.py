"""Task registration helpers for user scripts.

Usage from a user script:

    from python_script_launcher import task, run_cli   # inside a wheel install
    # or, from the top-level module when scripts sit next to the launcher:
    from tasks import task, run_cli

    @task
    def greet(name, greeting="hello"):
        print(f"{greeting}, {name}!")

    @task(name="square-sum", desc="Sum of squares up to n")
    def square_sum(n=5):
        total = sum(i * i for i in range(1, n + 1))
        print(f"squares(1..{n}) = {total}")

    if __name__ == "__main__":
        run_cli()

The Launcher (`app.scan_scripts`) discovers every @task-decorated function
inside a user script, so a single .py can expose multiple runnable tasks.
The legacy convention (one `def main(...)` plus `if __name__ == "__main__"`)
still works.
"""
from __future__ import annotations

import argparse
import inspect
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


# --- Type helpers --------------------------------------------------------

_TYPE_MAP = {
    str: str,
    int: int,
    float: float,
    bool: None,  # bool uses store_true / store_false
}


@dataclass
class TaskParam:
    name: str
    type_str: str
    required: bool
    default: Any = None
    help_text: str = ""

    def to_dict(self):
        return {
            "name": self.name,
            "type": self.type_str,
            "required": self.required,
            "default": self.default,
            "help": self.help_text,
        }


@dataclass
class TaskSpec:
    name: str
    func: Callable[..., Any]
    desc: str = ""
    params: list = field(default_factory=list)

    def __call__(self, **kwargs):
        return self.func(**kwargs)


def _annotation_to_type(annotation):
    if annotation is inspect.Parameter.empty:
        return str
    if isinstance(annotation, type):
        return annotation
    return str


def _describe_params(func):
    sig = inspect.signature(func)
    params = []
    for param_name, param in sig.parameters.items():
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        tp = _annotation_to_type(param.annotation)
        has_default = param.default is not inspect.Parameter.empty
        params.append(TaskParam(
            name=param_name,
            type_str=getattr(tp, "__name__", str(tp)),
            required=not has_default,
            default=(param.default if has_default else None),
        ))
    return params


# --- Registration -------------------------------------------------------

_TASKS_ATTR = "__tasks__"


def task(fn=None, *, name=None, desc=None):
    def wrap(func):
        module = sys.modules.get(func.__module__)
        registry = getattr(module, _TASKS_ATTR, None) if module is not None else None
        if registry is None:
            registry = {}
            if module is not None:
                setattr(module, _TASKS_ATTR, registry)
        task_name = name or func.__name__
        spec = TaskSpec(
            name=task_name,
            func=func,
            desc=(desc if desc is not None else (inspect.getdoc(func) or "")),
            params=_describe_params(func),
        )
        registry[task_name] = spec
        func.__task_spec__ = spec
        return func

    if fn is not None and callable(fn):
        return wrap(fn)
    return wrap


def collect_tasks(module):
    tasks_ = getattr(module, _TASKS_ATTR, None)
    if isinstance(tasks_, dict):
        return dict(tasks_)
    return {}


# --- CLI helper ---------------------------------------------------------

def _add_cli_argument(parser, param):
    if param.type_str == "bool" or isinstance(param.default, bool):
        parser.add_argument(
            f"--{param.name.replace('_', '-')}",
            dest=param.name,
            action="store_true" if not bool(param.default) else "store_false",
            default=bool(param.default),
            help=f"(default: {param.default})",
        )
        return

    lookup = {"int": int, "float": float, "str": str}
    cli_type = lookup.get(param.type_str, str)
    kwargs = {"type": cli_type, "dest": param.name}
    if param.required:
        parser.add_argument(f"--{param.name.replace('_', '-')}",
                            required=True, help="required", **kwargs)
    else:
        parser.add_argument(f"--{param.name.replace('_', '-')}",
                            default=param.default,
                            help=f"(default: {param.default!r})", **kwargs)


def run_cli(module=None, argv=None):
    if module is None:
        frame = sys._getframe(1)
        module = sys.modules.get(frame.f_globals.get("__name__"))
    tasks_ = collect_tasks(module) if module is not None else {}
    if not tasks_:
        print("[tasks] no @task registered in this module", file=sys.stderr)
        return 2

    if len(tasks_) == 1:
        spec = next(iter(tasks_.values()))
        parser = argparse.ArgumentParser(prog=spec.name, description=spec.desc)
        for p in spec.params:
            _add_cli_argument(parser, p)
        ns = parser.parse_args(argv)
        spec(**vars(ns))
        return 0

    parser = argparse.ArgumentParser(prog=(module.__name__ if module else "tasks"))
    sub = parser.add_subparsers(dest="_task", required=True)
    for spec in tasks_.values():
        head = spec.desc.splitlines()[0] if spec.desc else None
        sp = sub.add_parser(spec.name, help=head, description=spec.desc)
        for p in spec.params:
            _add_cli_argument(sp, p)
    ns = parser.parse_args(argv)
    task_name = ns._task
    kwargs = {k: v for k, v in vars(ns).items() if k != "_task"}
    tasks_[task_name](**kwargs)
    return 0
