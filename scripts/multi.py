"""多任务示例: 用 @task 注册多个可运行函数, 无需 __main__ guard."""
from tasks import task


@task
def greet(name: str, greeting: str = "hello"):
    """Say hi to someone."""
    print(f"{greeting}, {name}!")


@task(name="square-sum", desc="Sum of squares up to n")
def square_sum(n: int = 4):
    total = sum(i * i for i in range(1, n + 1))
    print(f"squares(1..{n}) = {total}")


@task
def multiline(times: int = 3):
    """Emit multiple lines to test SSE streaming."""
    import time
    for i in range(times):
        print(f"line {i}", flush=True)
        time.sleep(0.05)
    print("done")
