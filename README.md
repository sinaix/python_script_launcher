# Python App Launcher

一键把任意 Python 脚本目录变成独立 Web/桌面 exe：自动扫描脚本、生成参数表单、实时流式输出，支持一份脚本注册多个可运行任务。

## 特性

- **自动扫描**：递归识别 `scripts/` 下的入口，支持 `@task` 装饰器与传统 `def main()`。
- **多任务脚本**：一个 `.py` 文件可注册多个 `@task`，无需手写 `if __name__ == "__main__"`。
- **参数表单**：根据函数签名自动生成 UI（`str/int/float/bool` + 默认值 + 文件上传）。
- **实时输出**：进程内 `runpy` / `importlib` 执行 + SSE 行流，冷启动毫秒级。
- **一键打包**：`launcher build` 调用 PyInstaller，产出无需 Python 环境的 `.exe`。
- **双形态发布**：`publish.py` 同步产出 wheel + sdist + `onedir/onefile` exe + release zip。

## 安装

```bash
# 通过 uv（推荐）
uv sync

# 或安装已发布的 wheel（含打包依赖）
pip install "python-script-launcher[build]"
```

## 用户脚本写法

推荐使用 `@task` 装饰器，一个文件可暴露多个可调用任务：

```python
# my_tools/demo.py
from python_script_launcher import task  # 或 from tasks import task

@task
def hi(name: str = "world"):
    """打个招呼。"""
    print(f"hi, {name}!")

@task(name="add", desc="加两个整数")
def add_(a: int, b: int = 1):
    print(a + b)
```

依然兼容旧式 `def main(...) + __main__` 脚本：

```python
def main(name: str = "world"):
    print(f"hello, {name}!")

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--name", default="world")
    main(**vars(p.parse_args()))
```

**约定**

| 特性 | 说明 |
|------|------|
| 入口 | `@task` 装饰函数，或顶层 `def main(...)` |
| 参数类型 | 通过类型注解推导（`str/int/float/bool`），无注解按 `str` 处理 |
| 必填/可选 | 有默认值 → 可选；无默认值 → 必填 |
| 文件参数 | 参数名含 `file` / `path` / `upload` 时启用上传控件 |
| 说明文字 | 函数 docstring 显示在 UI 上 |

## CLI

安装后可直接使用 `launcher` 入口（或 `python -m python_script_launcher`）：

```bash
# 扫描并列出脚本
launcher scan --scripts D:\my_tools

# 开发模式启动 Web UI（http://localhost:8765）
launcher run --scripts D:\my_tools --port 8765

# 打包成 exe（onedir 默认，冷启动快）
launcher build --scripts D:\my_tools --name MyTools --mode both

# 单文件 exe（体积大、启动稍慢）
launcher build --scripts D:\my_tools --onefile --clean
```

`build` 参数：

| 参数 | 说明 | 默认 |
|------|------|------|
| `--scripts, -s` | 脚本目录 | 必填 |
| `--output, -o` | 产物目录 | `./dist` |
| `--name, -n` | 应用名 | 脚本目录名 |
| `--mode, -m` | `web` / `client` / `both` | `both` |
| `--onefile` | 单文件 exe | `false` |
| `--clean` | 丢弃 `build/` 缓存重打 | `false` |

## 作为库调用

```python
from python_script_launcher import create_app, scan_scripts, start_desktop
from pathlib import Path

# 扫描
scripts = scan_scripts(Path(r"D:\\my_tools"))

# 启动 Web
app = create_app(root=r"D:\\my_tools")  # ASGI app, 用 uvicorn.run 起

# 启动桌面
start_desktop(root=r"D:\\my_tools", title="我的工具", port=8765)
```

## 发布 / 版本管理

`publish.py` 是唯一的发布入口，从根目录源码 stage 出一份 `python_script_launcher/` 布局并调用 `python -m build`：

```bash
# 只出 wheel + sdist
python publish.py --wheel

# 只出 exe（onedir，PythonAppLauncher / PythonAppDesktop）
python publish.py --exe

# 完整发布：wheel + exe + zip
python publish.py --wheel --exe --zip

# 升版本号（写入 VERSION 后再构建）
python publish.py --version 1.2.0 --wheel --exe
```

## 打包原理速览

- `make_exe.py` 用 `importlib.metadata.distributions()` 拿到当前解释器里所有第三方包，通过 `--collect-all` 全量塞进 exe，避开脆弱的 import 扫描。
- `__main__.py::_stage_project()` 会把 `app.py / client.py / tasks.py / static/` + 用户脚本复制到临时目录，并合成 `python_script_launcher/` 包 shim（转发 `tasks`），让打包后的 exe 里用户脚本 `from python_script_launcher import task` 依然可用。
- 打包后 `app.py` 在 frozen 模式下直接进程内跑用户脚本（`runpy.run_path` 或 `@task` importlib），不再拉起子 Python，冷启动 20-60 ms。

## 目录结构

```
pyRunner/
├─ app.py            # FastAPI 后端 + 脚本扫描 / SSE 执行
├─ client.py         # pywebview 桌面壳
├─ tasks.py          # @task 装饰器 + run_cli()
├─ make_exe.py       # PyInstaller 封装（build_exe 可复用）
├─ __init__.py       # wheel 包入口 + 版本号
├─ __main__.py       # launcher CLI (scan/run/build)
├─ publish.py        # wheel + exe + zip 发布器
├─ static/           # Web UI（单页）
├─ scripts/          # 示例脚本
├─ pyproject.toml    # 本地 dev 依赖（wheel 由 publish.py 生成）
└─ VERSION           # 版本号（publish.py 读写）
```

## License

MIT
