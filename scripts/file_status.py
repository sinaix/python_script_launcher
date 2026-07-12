"""示例：文件统计 — 演示文件路径参数"""
import sys
from pathlib import Path


def main(filepath: str):
    """统计指定文件的行数、单词数和字节数"""
    path = Path(filepath)
    if not path.exists():
        print(f"❌ 文件不存在: {filepath}")
        return
    content = path.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines()
    words = content.split()
    print(f"📄 {path.name}")
    print(f"   大小: {path.stat().st_size:,} 字节")
    print(f"   行数: {len(lines):,}")
    print(f"   单词: {len(words):,}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python file_stats.py --filepath <文件路径>")
        sys.exit(1)
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--filepath", nargs="+", required=True)
    args = parser.parse_args()

    # args.filepath 现在是列表：['uploads/abc.json', 'uploads/def.json']
    for fpath in args.filepath:
        main(fpath)
    