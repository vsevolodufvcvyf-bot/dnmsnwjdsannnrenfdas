# -*- coding: utf-8 -*-
"""Атомарная запись файлов: читатель видит либо старый файл целиком, либо новый."""
from __future__ import annotations

import configparser
import io
import os
import tempfile


def atomic_write_text(path: str, text: str, encoding: str = "utf-8") -> None:
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp_", suffix=os.path.basename(path), dir=folder)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_config(path: str, cfg: configparser.ConfigParser) -> None:
    buf = io.StringIO()
    cfg.write(buf)
    atomic_write_text(path, buf.getvalue())
