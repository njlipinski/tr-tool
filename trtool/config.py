"""Local settings in trtool.ini at the repo root (gitignored).

Environment variables TRTOOL_<KEY> (e.g. TRTOOL_GAME_DIR) override the file.
"""
import configparser
import os

from .db import ROOT

DEFAULT_PATH = os.path.join(ROOT, "trtool.ini")
SECTION = "trtool"
KEYS = ("game_dir",)


def _path(path):
    return path or os.environ.get("TRTOOL_CONFIG") or DEFAULT_PATH


def load(path=None):
    """All settings in the file as a dict (env overrides not applied)."""
    cp = configparser.ConfigParser()
    cp.read(_path(path), encoding="utf-8")
    return dict(cp[SECTION]) if cp.has_section(SECTION) else {}


def get(key, path=None):
    env = os.environ.get("TRTOOL_" + key.upper())
    if env:
        return env
    return load(path).get(key)


def set(key, value, path=None):  # noqa: A001 (mirrors the command name)
    if key not in KEYS:
        raise KeyError("Unknown setting %r (known: %s)" % (key, ", ".join(KEYS)))
    p = _path(path)
    cp = configparser.ConfigParser()
    cp.read(p, encoding="utf-8")
    if not cp.has_section(SECTION):
        cp.add_section(SECTION)
    cp[SECTION][key] = value
    with open(p, "w", encoding="utf-8") as f:
        cp.write(f)
