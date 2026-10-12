# -*- coding: utf-8 -*-
"""Красивый экран для Start.bat — вызывается до и после pip."""
import os
import sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())

if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "boot"
    if stage == "deps":
        from Utils.bootstrap import missing_modules
        raise SystemExit(1 if missing_modules() else 0)
    from Utils.console_ui import print_splash
    extra = sys.argv[2] if len(sys.argv) > 2 else ""
    fails = sys.argv[3] if len(sys.argv) > 3 else ""
    print_splash(stage, extra, fails)
