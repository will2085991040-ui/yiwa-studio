# -*- coding: utf-8 -*-
"""Desktop launcher (Step 21): inject config -> alembic schema -> uvicorn -> desktop window -> graceful stop.

This module deliberately does NOT import the 'app' package at module top-level
(app/__init__.py eagerly builds the DB engine) so that apply_env() can set DATABASE_URL etc.
before 'app' is ever first imported.
"""
import os
import sys
import threading
import webbrowser

import uvicorn

from desktop.config import DesktopConfig
from desktop.server import build_desktop_app


def _resource_root() -> str:
    # Frozen: PyInstaller onefile temp dir; dev: backend/ directory.
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resolve_web_root(config_web_root: str) -> str:
    # Explicit config > bundled frontend_out > dev ../frontend/out.
    if config_web_root:
        return config_web_root
    root = _resource_root()
    for candidate in (os.path.join(root, "frontend_out"), os.path.join(root, "..", "frontend", "out")):
        if os.path.isdir(candidate):
            return candidate
    return ""


class DesktopLauncher:
    def __init__(self, config: DesktopConfig):
        self.config = config
        self.url = "http://{0}:{1}".format(config.host, config.port)
        self._server = None
        self._thread = None

    def apply_env(self) -> None:
        c = self.config
        os.environ["APP_ENV"] = "production"
        os.environ["AUTH_REQUIRED"] = "true"  # desktop app forces auth on all project APIs
        os.environ["DATABASE_URL"] = c.database_url
        os.environ["YIWA_DATA_DIR"] = c.data_dir
        os.environ["LLM_PROVIDER"] = c.llm_provider
        os.environ["LLM_BASE_URL"] = c.llm_base_url
        os.environ["LLM_MODEL"] = c.llm_model
        if c.llm_script_model:
            os.environ["LLM_SCRIPT_MODEL"] = c.llm_script_model
        os.environ["LLM_API_KEY"] = c.llm_api_key
        os.environ["LLM_DISABLE_THINKING"] = "true" if c.llm_disable_thinking else "false"
        os.environ["LLM_TIMEOUT_SECONDS"] = str(c.llm_timeout_seconds)
        os.environ["IMAGE_PROVIDER"] = c.image_provider
        os.environ["IMAGE_BASE_URL"] = c.image_base_url
        os.environ["IMAGE_MODEL"] = c.image_model
        os.environ["IMAGE_SIZE"] = c.image_size
        os.environ["IMAGE_API_KEY"] = c.image_api_key
        os.environ["VIDEO_PROVIDER"] = c.video_provider
        os.environ["VIDEO_BASE_URL"] = c.video_base_url
        os.environ["VIDEO_MODEL"] = c.video_model
        os.environ["VIDEO_API_KEY"] = c.video_api_key
        os.environ["YIWA_TOKEN"] = c.yiwa_token
        os.environ["YIWA_GATEWAY_URL"] = c.yiwa_gateway_url

    def ensure_schema(self) -> None:
        # Alembic upgrade head on first run.
        from alembic import command
        from alembic.config import Config
        root = _resource_root()
        ini_path = os.path.join(root, "alembic.ini")
        if not os.path.isfile(ini_path):
            ini_path = os.path.join(root, "..", "alembic.ini")
        cfg = Config(ini_path)
        cfg.set_main_option("script_location", os.path.join(root, "alembic"))
        if not os.path.isdir(os.path.join(root, "alembic")):
            cfg.set_main_option("script_location", os.path.join(root, "..", "alembic"))
        command.upgrade(cfg, "head")

    def _log(self, msg: str) -> None:
        try:
            from datetime import datetime as _dt
            logf = os.path.join(self.config.data_dir, "yiwa-launcher.log")
            with open(logf, "a", encoding="utf-8") as fh:
                fh.write(_dt.now().isoformat() + "  " + msg + "\n")
        except Exception:
            pass

    # ---- single-instance guard (atomic lockfile) ----
    # A windowed PyInstaller EXE spawns a bootloader parent + one child, so
    # "count YIWA.exe" can be >1 while only ONE logical instance exists. The
    # real hazard is launching the EXE again while one is running: the second
    # uvicorn tries to bind host:port, gets OSError 10048, its backend dies, and
    # its empty window never resolves /api/auth/status -> the login screen spins
    # forever on "正在校验登录". We prevent that with an atomic lockfile in a
    # SHARED dir (data_dir, not the per-instance _MEIPASS temp dir). Only the
    # lock owner may start a server; any later launch exits immediately.
    def _port_up(self, timeout: float = 0.35) -> bool:
        # True if our host:port currently accepts connections, i.e. a healthy
        # backend is already serving there. This is the authoritative sign that
        # another running instance owns the server.
        import socket as _socket
        try:
            with _socket.create_connection((self.config.host, self.config.port), timeout=timeout):
                return True
        except OSError:
            return False

    def _acquire_single_instance(self) -> bool:
        # Returns True if THIS instance is the one allowed to start the server.
        # Returns False if another instance is already serving host:port (in
        # which case we must NOT start a second uvicorn - that double bind is
        # exactly what produced OSError 10048 and a red/blank WebView).
        #
        # Key rule: the PORT is the single source of truth. If it already
        # listens, another live instance owns it - never fight it. PID checks
        # are unreliable here because a windowed PyInstaller EXE runs as a
        # bootloader parent + child, and os.kill() works oddly on the child.
        import errno as _errno
        lock_path = os.path.join(self.config.data_dir, "yiwa.lock")
        if self._port_up():
            self._log("port %d already served by another instance - becoming client, not owner" % self.config.port)
            return False
        for _attempt in range(2):
            try:
                fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
            except OSError as exc:
                if exc.errno not in (_errno.EEXIST, 17):  # 17 = Windows EEXIST
                    raise
                # Lock file exists, but the port is NOT listening -> the previous
                # owner crashed (or is stuck before binding), so the lock is
                # stale. Removing it lets us take over. If the port were live we
                # would already have returned False above.
                self._log("removing stale single-instance lock")
                try:
                    os.unlink(lock_path)
                except OSError:
                    pass
                continue
            try:
                os.write(fd, str(os.getpid()).encode("ascii"))
            finally:
                os.close(fd)
            self._lock_owned = True
            return True
        self._log("could not acquire single-instance lock")
        return False

    def _release_single_instance(self) -> None:
        if not getattr(self, "_lock_owned", False):
            return
        try:
            os.unlink(os.path.join(self.config.data_dir, "yiwa.lock"))
        except OSError:
            pass
        self._lock_owned = False

    def _wait_serving(self, timeout: float = 4.0) -> bool:
        # After the uvicorn thread is started, wait until it actually accepts
        # connections on host:port. If it never does (port grabbed by a racing
        # / stale instance, TIME_WAIT, or bind failure) return False so the
        # caller can degrade to attach to the already-running instance.
        import time as _t
        deadline = _t.time() + timeout
        while _t.time() < deadline:
            if self._port_up(0.15):
                return True
            _t.sleep(0.15)
        return False

    @property
    def serving_ready(self) -> bool:
        return getattr(self, "_serving_ready", False)

    def start(self) -> bool:
        # Return True when this instance OWNS the desktop server; False when a
        # duplicate launch was rejected (caller should exit quietly).
        # windowed (no-console) EXE: sys.stdout/stderr may be None, which crashes
        # uvicorn's DefaultFormatter (calls MSTree). Give them proper streams so
        # .isatty() works and any print() does not die.
        if sys.stdout is None:
            sys.stdout = open(os.devnull, "w", encoding="utf-8")
        if sys.stderr is None:
            sys.stderr = open(os.devnull, "w", encoding="utf-8")
        self.config.ensure_dirs()
        self._log("start: acquire single-instance lock")
        self._lock_owned = False
        if not self._acquire_single_instance():
            return False
        self._log("start: apply_env")
        self.apply_env()
        self._log("start: ensure_schema begin")
        self.ensure_schema()
        self._log("start: ensure_schema done")
        web_root = _resolve_web_root(self.config.web_root)
        self._log("start: build_desktop_app begin (web_root=%r)" % web_root)
        app = build_desktop_app(web_root)
        self._log("start: build_desktop_app done")
        try:
            server_config = uvicorn.Config(app, host=self.config.host, port=self.config.port, log_level="info", log_config=None)
            self._server = uvicorn.Server(server_config)
            self._thread = threading.Thread(target=self._run_server, name="yiwa-desktop", daemon=True)
            self._thread.start()
            self._log("start: server thread started")
            self._serving_ready = self._wait_serving()
            if not self._serving_ready:
                self._log("server did not become ready on %s - attaching to existing instance" % self.url)
        except BaseException as exc:
            import traceback as _tb
            self._log("START-ERROR:\n" + "\n".join(_tb.format_exception(type(exc), exc, exc.__traceback__)))
            raise
        return True

    def _run_server(self) -> None:
        # Run uvicorn in a thread; write errors + lifecycle to data_dir/yiwa-launcher.log
        # so a windowed (no-console) EXE is debuggable.
        import traceback as _tb
        from datetime import datetime as _dt

        def _app_log(msg: str) -> None:
            try:
                logf = os.path.join(self.config.data_dir, "yiwa-launcher.log")
                with open(logf, "a", encoding="utf-8") as fh:
                    fh.write(_dt.now().isoformat() + "  " + msg + "\n")
            except Exception:
                pass

        try:
            _app_log("server thread started, url=%s" % self.url)
            # Run uvicorn on a DEDICATED asyncio event loop in this thread.
            # Under a frozen (PyInstaller, windowed) EXE on Windows,
            # uvicorn.Server.run() may fail to start the implicit loop and the
            # port silently never binds; an explicit per-thread loop fixes it.
            import asyncio as _asyncio
            _loop = _asyncio.new_event_loop()
            _asyncio.set_event_loop(_loop)
            _loop.run_until_complete(self._server.serve())
            _app_log("PIA server thread exited normally")
        except BaseException as exc:
            try:
                logf = os.path.join(self.config.data_dir, "yiwa-launcher.log")
                with open(logf, "a", encoding="utf-8") as fh:
                    fh.write("SERVER-THREAD-ERROR:\n")
                    fh.write("\n".join(_tb.format_exception(type(exc), exc, exc.__traceback__)))
                    fh.write("\n")
            except Exception:
                pass

    def open_desktop_window(self) -> bool:
        # Open the app in an embedded native window (pywebview + WebView2).
        # Falls back to the system browser if pywebview/WebView2 is unavailable.
        try:
            import webview
        except Exception as exc:
            print("[YIWA] pywebview unavailable: {0}; opening in browser.".format(exc), flush=True)
            webbrowser.open(self.url)
            return False
        try:
            window = webview.create_window(
                "YIWA Studio",
                self.url,
                width=1440,
                height=900,
                min_size=(1100, 720),
                background_color="#0c0b1d",
                text_select=True,
            )
            webview.start()
            return window is not None
        except Exception as exc:
            print("[YIWA] desktop window failed: {0}, falling back to browser".format(exc), flush=True)
            webbrowser.open(self.url)
            return False

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._release_single_instance()
