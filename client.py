"""
Python App Launcher — 桌面客户端版
作为模块引入时: from python_script_launcher import start_desktop
直接运行时:     python client.py
"""
import sys, os, threading, argparse
from pathlib import Path


def start_desktop(
    root: str = None,
    port: int = 8765,
    title: str = "Python App Launcher",
    width: int = 1200,
    height: int = 800,
    debug: bool = False,
):
    import webview
    from app import create_app, scan_scripts, find_python, is_port_used

    project_root = Path(root).resolve() if root else _find_root()

    if is_port_used(port):
        print(f"[!] Port {port} already in use")
        return

    app = create_app(root=project_root)

    found = scan_scripts(project_root)
    print(f"\n{'='*50}")
    print(f"  {title} - Desktop")
    print(f"{'='*50}")
    print(f"  Project: {project_root}")
    print(f"  Scripts: {len(found)}")
    print(f"  Port:    {port}")
    print(f"{'='*50}\n")

    def run_server():
        import uvicorn
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="error")

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    import time; time.sleep(1)

    class Api:
        def select_folder(self):
            w = webview.windows[0]
            r = w.create_file_dialog(webview.FOLDER_DIALOG)
            return r[0] if r else None

        def open_folder(self, path=None):
            import subprocess
            target = str(Path(path) if path else project_root)
            if sys.platform == "win32":
                subprocess.Popen(["explorer", target])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", target])
            else:
                subprocess.Popen(["xdg-open", target])

    window = webview.create_window(
        title=title,
        url=f"http://localhost:{port}",
        width=width,
        height=height,
        min_size=(800, 600),
        text_select=True,
        background_color="#ffffff",
        js_api=Api(),
    )

    webview.start(debug=debug)
    os._exit(0)


def _find_root():
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    p = Path(__file__).parent.resolve()
    return p.parent if p.name == "scripts" else p


if __name__ == "__main__":
    if getattr(sys, "frozen", False):
        import ctypes
        mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "PythonAppLauncher_Desktop")
        if ctypes.windll.kernel32.GetLastError() == 183:
            print("Another instance is already running.")
            sys.exit(0)

    parser = argparse.ArgumentParser(description="Python App Launcher Desktop")
    parser.add_argument("--root", "-r", type=str, default=None)
    parser.add_argument("--port", "-p", type=int, default=8765)
    parser.add_argument("--debug", action="store_true")
    args, _ = parser.parse_known_args()

    start_desktop(root=args.root, port=args.port, debug=args.debug)
