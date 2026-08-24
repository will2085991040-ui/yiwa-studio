"""PyInstaller 入口：调用 desktop 包的 CLI main()。"""
import sys

from desktop.__main__ import main

if __name__ == "__main__":
    sys.exit(main())