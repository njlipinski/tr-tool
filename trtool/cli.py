"""Command line: python -m trtool <command> ..."""
import argparse
import csv
import glob
import json
import os
import sys

from . import analysis, db, learn as learn_mod, report
from .save import Save


def default_save_dir():
    """The game's save folder on this machine, if we can guess it."""
    candidates = []
    if os.name == "nt":
        candidates.append(os.path.expandvars(r"%USERPROFILE%\AppData\LocalLow\Louqou\TravellersRest\GameSaves"))
    home = os.path.expanduser("~")
    candidates += [  # Linux / Proton and macOS guesses; adjust if yours differs
        os.path.join(home, ".config", "unity3d", "Louqou", "TravellersRest", "GameSaves"),
        os.path.join(home, "Library", "Application Support", "Louqou", "TravellersRest", "GameSaves"),
    ]
    for c in candidates:
        if os.path.isdir(c):
            return c
    return None


def resolve_save(arg):
    """A .save file, a folder (newest .save in it), or nothing (the game's folder)."""
    path = arg or default_save_dir()
    if not path:
        sys.exit("No save given and the game's save folder wasn't found. Pass a .save file or folder.")
    if os.path.isdir(path):
        saves = glob.glob(os.path.join(path, "**", "*.save"), recursive=True)
        if not saves:
            sys.exit("No .save files in %s" % path)
        path = max(saves, key=os.path.getmtime)
    if not os.path.isfile(path):
        sys.exit("Not found: %s" % path)
    return path


def cmd_build_db(a):
    con = db.build(a.db)
    n = con.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    print("Built %s (%d items)" % (a.db, n))


def cmd_learn(a):
    for p in a.saves:
        s = Save(resolve_save(p))
        print("%s  %s" % (s.path, json.dumps(learn_mod.learn(s))))


def cmd_report(a):
    s = Save(resolve_save(a.save))
    if not a.no_learn:
        learn_mod.learn(s)
    con = db.connect(a.db)
    page = report.render(s, con, db.Names(con))
    out = a.output or os.path.splitext(os.path.basename(s.path))[0] + "_report.html"
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    print("Wrote %s" % out)


def cmd_ingredients(a):
    s = Save(resolve_save(a.save))
    con = db.connect(a.db)
    rows = analysis.unnamed_ingredients(s, con, db.Names(con))
    out = open(a.output, "w", encoding="utf-8", newline="") if a.output else sys.stdout
    if not rows:
        print("Every ingredient in this save has a confirmed name.", file=sys.stderr)
        return
    w = csv.DictWriter(out, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
    w.writeheader()
    w.writerows(rows)


def cmd_dump(a):
    s = Save(resolve_save(a.save))
    data = s.raw if not a.field else s.raw.get(a.field)
    json.dump(data, sys.stdout, indent=1, ensure_ascii=False)
    print()


def cmd_where(a):
    print(default_save_dir() or "Save folder not found on this machine.")


def main(argv=None):
    p = argparse.ArgumentParser(prog="trtool", description="TR Tool: Travellers Rest save helper")
    p.add_argument("--db", default=db.DEFAULT_DB, help="database path (default: build/trtool.db)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("build-db", help="rebuild the database from data/*.tsv")
    sp.set_defaults(func=cmd_build_db)

    sp = sub.add_parser("learn", help="add what saves reveal (dish ingredients, recipe inputs) to data/")
    sp.add_argument("saves", nargs="*", default=[None])
    sp.set_defaults(func=cmd_learn)

    sp = sub.add_parser("report", help="write the HTML diagnostics report")
    sp.add_argument("save", nargs="?", help=".save file or folder (default: newest in the game's folder)")
    sp.add_argument("-o", "--output")
    sp.add_argument("--no-learn", action="store_true", help="don't update data/ from this save")
    sp.set_defaults(func=cmd_report)

    sp = sub.add_parser("ingredients", help="list ingredient IDs without a confirmed name, with evidence")
    sp.add_argument("save", nargs="?")
    sp.add_argument("-o", "--output")
    sp.set_defaults(func=cmd_ingredients)

    sp = sub.add_parser("dump", help="print the decoded save (or one field) as JSON")
    sp.add_argument("save", nargs="?")
    sp.add_argument("--field")
    sp.set_defaults(func=cmd_dump)

    sp = sub.add_parser("where", help="show the game's save folder on this machine")
    sp.set_defaults(func=cmd_where)

    a = p.parse_args(argv)
    a.func(a)
