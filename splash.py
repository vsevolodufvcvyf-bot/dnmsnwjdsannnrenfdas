# -*- coding: utf-8 -*-
"""Красивый экран для Start.bat — вызывается до и после pip."""
import os
import sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())

from Utils.console_ui import print_splash

if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "boot"
    extra = sys.argv[2] if len(sys.argv) > 2 else ""
    print_splash(stage, extra)
