"""Interactive stdin demo — Launcher will show an input box; type answers there.

三个任务，覆盖不同的输入姿势：
- ``ask_name``: 单次 ``input()`` 走一次交互。
- ``quiz``: 多轮 ``input(prompt)``，展示提示前先 flush。
- ``echo_lines``: 循环读取直到 EOF (前端按 ``Ctrl+D`` 或 EOF 按钮结束)。
"""
from tasks import task


@task
def ask_name(greeting: str = "hello"):
    """Prompt for a single line and greet the user."""
    name = input("你叫什么名字? ").strip()
    print(f"{greeting}, {name or 'stranger'}!")


@task(desc="Two-question quiz — 展示多次 input() 交互")
def quiz():
    """Ask a couple of questions in sequence."""
    fav = input("最喜欢的编程语言? ").strip() or "python"
    year = input("入行几年了? ").strip() or "?"
    print(f"记录: 语言={fav}, 年限={year}")


@task(desc="逐行回显 stdin, 直到收到 EOF")
def echo_lines():
    """Echo every line typed until the user sends EOF."""
    import sys

    print("请输入多行文本，输完后按 EOF 结束:", flush=True)
    count = 0
    for line in sys.stdin:
        count += 1
        # 去除末尾换行, 保留内部空白
        print(f"[{count}] {line.rstrip()}")
    print(f"共读取 {count} 行, 已收到 EOF, 退出。")
