# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置：YIWA 桌面 EXE（Windows 单文件，内嵌 WebView2 桌面窗口）。
# 用法：见同目录 build_exe.ps1，或在 backend/ 下执行：
#   pyinstaller --clean --noconfirm desktopyiwa.spec
import os

from PyInstaller.utils.hooks import collect_submodules, collect_data_files, collect_dynamic_libs

spec_dir = SPECPATH                        # backenddesktop
backend_dir = os.path.dirname(spec_dir)    # backend
repo_root = os.path.dirname(backend_dir)   # ai-interactive-growth-agent

hiddenimports = collect_submodules("app")
hiddenimports += collect_submodules("desktop")
hiddenimports += collect_submodules("uvicorn")
hiddenimports += collect_submodules("alembic")
# pywebview + pythonnet（WebView2 桌面窗口）
hiddenimports += collect_submodules("webview")
hiddenimports += collect_submodules("pythonnet")
hiddenimports += collect_submodules("clr_loader")
# ffmpeg（imageio-ffmpeg 自带的静态二进制）用于离线合成完整成片
hiddenimports += collect_submodules("imageio_ffmpeg")

# 打进 EXE 的外部资源：前端静态产物 / Alembic 迁移脚本 / alembic.ini
datas = [
    (os.path.join(repo_root, "frontend", "out"), "frontend_out"),
    (os.path.join(backend_dir, "alembic"), "alembic"),
    (os.path.join(backend_dir, "alembic.ini"), "."),
] + collect_data_files("imageio_ffmpeg")

# pywebview / WebView2 桌面窗口所需的额外资源与原生库
datas_extra = collect_data_files("webview")
datas_extra += collect_data_files("pythonnet")
datas_extra += collect_data_files("clr_loader")
binaries_extra = collect_dynamic_libs("pythonnet")
binaries_extra += collect_dynamic_libs("clr_loader")

a = Analysis(
    [os.path.join(spec_dir, "entry.py")],
    pathex=[backend_dir],
    binaries=binaries_extra,
    datas=datas + datas_extra,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "pytest_cov", "ruff", "psycopg2"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="YIWA",
    icon=os.path.join(repo_root, "backend", "desktop", "icon.ico"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # 无控制台：以内嵌 WebView2 桌面窗口运行
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
