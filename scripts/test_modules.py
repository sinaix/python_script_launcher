"""最简单的模块测试"""
import sys


def main():
    print("=== Module Test ===")
    print(f"Python: {sys.version}")
    print(f"Executable: {sys.executable}")
    print()

    modules = ["json", "os", "pathlib", "requests", "rich", "pandas", "numpy"]
    for mod in modules:
        try:
            m = __import__(mod)
            v = getattr(m, "__version__", "ok")
            print(f"  [OK]   {mod} {v}")
        except ImportError:
            print(f"  [MISS] {mod}")
        except Exception as e:
            print(f"  [ERR]  {mod}: {e}")


if __name__ == "__main__":
    main()