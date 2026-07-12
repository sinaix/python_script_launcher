"""示例：Hello World — 基础参数演示"""
import sys


def main(name: str, greeting: str = "你好"):
    """一个简单的问候脚本，演示必填参数和可选参数"""
    print(f"👋 {greeting}，{name}！")
    print(f"Python {sys.version.split()[0]}")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--name", required=True)
    p.add_argument("--greeting", default="你好")
    a = p.parse_args()
    main(a.name, a.greeting)