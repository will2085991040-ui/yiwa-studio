"""CLI：python -m desktop [--data-dir DIR] [--port N] [--web-root DIR] [--no-browser]。"""
import argparse
import os
import sys
import time

from desktop.config import load_config, save_config
from desktop.launcher import DesktopLauncher


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="yiwa-desktop", description="YIWA 桌面服务")
    parser.add_argument("--data-dir", default=None, help="数据目录（默认 %APPDATA%/YIWA/data）")
    parser.add_argument("--port", type=int, default=None, help="监听端口（默认 8765）")
    parser.add_argument("--web-root", default=None, help="前端静态产物目录（缺省用内置启动页）")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args(argv)

    # `--data-dir` 指定时从该目录读取 config.json，避免泄漏 %APPDATA% 下的真实密钥
    # （冒烟测试 / 多实例隔离必需）。
    cfg = load_config(os.path.join(args.data_dir, "config.json") if args.data_dir else None)
    if args.data_dir:
        cfg.data_dir = args.data_dir
    if args.port:
        cfg.port = args.port
    if args.web_root:
        cfg.web_root = args.web_root
    if args.no_browser:
        cfg.open_browser = False
    save_config(cfg)  # 首次启动落地 config.json，供用户填入 API-Key

    launcher = DesktopLauncher(cfg)
    owns = launcher.start()
    server_ready = getattr(launcher, "serving_ready", True)
    if not owns:
        # Another YIWA instance is already running (single-instance lock). Do
        # NOT start a second uvicorn and do NOT show an error dialog: the
        # existing instance already owns host:port, so just exit quietly. No
        # second window and no error - the user keeps the first instance.
        print("另一个 YIWA 实例已在运行，本次启动直接退出。", flush=True)
        import time as _time
        try:
            _time.sleep(0.8)
        except Exception:
            pass
        return 0
    if not server_ready:
        # We own the lock but the server could not bind - a rare race / stale
        # port. Degrade gracefully: attach to the already-running instance so
        # the user still gets the app instead of an error dialog.
        print("检测到端口已被实例占用，转连已有实例。", flush=True)
        if cfg.open_browser:
            launcher.open_desktop_window()
        import time as _time
        try:
            _time.sleep(0.8)
        except Exception:
            pass
        launcher.stop()
        return 0
    print(f"YIWA 桌面服务已启动：{launcher.url}", flush=True)
    try:
        if cfg.open_browser:
            launcher.open_desktop_window()
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        launcher.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())