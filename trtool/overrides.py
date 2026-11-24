"""The user's manual fixes on top of the extracted catalogue. Stdlib only.

Build order:

  build/extracted.db          written by `trtool extract` (game files only)
  + data/overrides/<table>.tsv  the user's fixes (committed)
  = build/catalogue.db        what reports and helpers read

One TSV per catalogue table, one line per changed cell:

  <key columns...>  action  column  value  replaced  note  date

  action  set     one cell changed; `replaced` is the extracted value it replaced
          add     a row the game files don't have; one line per filled column
                  (`column` empty when the table has only key columns)
          delete  an extracted row removed; `replaced` is that row as JSON
  An empty cell means NULL.

An override is *stale* when the game changed underneath it: the extracted
value no longer equals `replaced`, the row is gone, or an added row now exists
in the game data. Stale overrides are never applied silently: they're skipped
and listed (by `extract`, `export-xlsx`'s "Stale overrides" sheet, and later
`validate`) for the user to keep or drop.

Overrides are made by `trtool import-xlsx` (see trtool/xlsx.py), which diffs a
workbook against the extracted data, or by editing the TSVs by hand.
"""
import json
import os
import re
import shutil
import sqlite3
from datetime import datetime, timezone

from .db import DATA, ROOT, read_tsv, write_tsv

BUILD_DIR = os.path.join(ROOT, "build")
OVERRIDES_DIR = os.path.join(DATA, "overrides")
EXTRACTED_NAME = "extracted.db"
CATALOGUE_NAME = "catalogue.db"

# Columns that identify a row, per catalogue table (in sheet/TSV order).
KEYS = {
    "items": ("id",),
    "group_members": ("group_id", "member_id", "rule", "mod_id"),
    "recipes": ("recipe_id",),
    "recipe_inputs": ("recipe_id", "slot"),
    "crafter_recipes": ("crafter_id", "recipe_id"),
    "crops": ("crop_id",),
    "crop_harvests": ("crop_id", "item_id"),
    "fish": ("item_id",),
    "shops": ("shop_id",),
    "shop_items": ("shop_id", "item_id"),
    "shop_recipes": ("shop_id", "recipe_id"),
}
TABLES = tuple(KEYS)
ACTIONS = ("delete", "set", "add")      # also the order they're applied in
OVERRIDE_FIELDS = ("action", "column", "value", "replaced", "note", "date")


def fields(table):
    return list(KEYS[table]) + list(OVERRIDE_FIELDS)


# --- values -------------------------------------------------------------------
def fmt(v):
    """Canonical text form, used for TSVs and for every comparison."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return str(int(v))
    if isinstance(v, float):
        return "%.15g" % v      # Excel keeps 15 significant digits; 2.0 -> "2"
    return str(v)


_INT = re.compile(r"-?\d+")


def check(v, decl_type):
    """fmt(v) checked against a column's declared type. Raises ValueError."""
    s = fmt(v)
    t = (decl_type or "").upper()
    if t in ("INTEGER", "REAL"):
        s = s.strip()
        if s == "":
            return s
        try:
            f = float(s)
        except ValueError:
            raise ValueError("%r is not a number" % s)
        if t == "INTEGER":
            if _INT.fullmatch(s):
                return s
            if not f.is_integer():
                raise ValueError("%r is not a whole number" % s)
            return str(int(f))
        return fmt(f)
    return s


def typed(s, decl_type):
    """TSV text -> the value stored in SQLite."""
    if s is None or s == "":
        return None
    t = (decl_type or "").upper()
    try:
        if t == "INTEGER":
            return int(s)
        if t == "REAL":
            return float(s)
    except ValueError:
        pass
    return s


# --- reading the catalogue ----------------------------------------------------
def columns(con, table):
    """[(name, declared type)] in schema order."""
    return [(r[1], r[2]) for r in con.execute("PRAGMA table_info(%s)" % table)]


def table_rows(con, table):
    """{key tuple (fmt strings): {column: value}} for every row."""
    keys = KEYS[table]
    cur = con.execute("SELECT * FROM %s" % table)
    names = [d[0] for d in cur.description]
    out = {}
    for r in cur:
        row = dict(zip(names, r))
        k = tuple(fmt(row[c]) for c in keys)
        if k in out:
            raise ValueError("%s: key %s is not unique in the extracted data" % (table, "|".join(k)))
        out[k] = row
    return out


def snapshot(table, row):
    """A row's non-key columns as JSON (the `replaced` value of a delete)."""
    return json.dumps({c: fmt(v) for c, v in row.items() if c not in KEYS[table]}, ensure_ascii=False)


def key_text(key):
    return "|".join(key)


# --- override files -----------------------------------------------------------
def load(overrides_dir=OVERRIDES_DIR):
    """{table: [override]}; each override is a dict with the TSV fields plus `key`."""
    out = {}
    if not os.path.isdir(overrides_dir):
        return out
    for fn in sorted(os.listdir(overrides_dir)):
        if not fn.endswith(".tsv"):
            continue
        table = fn[:-4]
        if table not in KEYS:
            raise ValueError("%s: no catalogue table called %r" % (os.path.join(overrides_dir, fn), table))
        recs = []
        for i, r in enumerate(read_tsv(os.path.join(overrides_dir, fn)), start=2):
            r = {k: (v or "") for k, v in r.items() if k is not None}
            if r.get("action") not in ACTIONS:
                raise ValueError("%s line %d: action must be one of %s" % (fn, i, ", ".join(ACTIONS)))
            r["key"] = tuple(r.get(c, "") for c in KEYS[table])
            recs.append(r)
        out[table] = recs
    return out


def _sort_key(rec):
    nums = tuple((0, int(k), "") if _INT.fullmatch(k) else (1, 0, k) for k in rec["key"])
    return nums, ACTIONS.index(rec["action"]), rec["column"]


def save(table, recs, overrides_dir=OVERRIDES_DIR):
    """Write one table's overrides (sorted); removes the file when there are none."""
    path = os.path.join(overrides_dir, table + ".tsv")
    if not recs:
        if os.path.exists(path):
            os.remove(path)
        return
    os.makedirs(overrides_dir, exist_ok=True)
    rows = []
    for r in sorted(recs, key=_sort_key):
        row = dict(zip(KEYS[table], r["key"]))
        row.update({f: r.get(f, "") for f in OVERRIDE_FIELDS})
        rows.append(row)
    write_tsv(path, fields(table), rows)


def make(table, key, action, column="", value="", replaced="", note="", date=""):
    return {"key": tuple(fmt(k) for k in key), "action": action, "column": column, "value": value,
            "replaced": replaced, "note": note, "date": date}


# --- stale check and apply ----------------------------------------------------
def classify(table, recs, rows, cols):
    """[(override, reason)]; reason is None when the override applies cleanly."""
    keys = KEYS[table]
    editable = {c for c, _ in cols if c not in keys}
    bad_add = {}
    out = []
    for r in recs:
        row, a, c = rows.get(r["key"]), r["action"], r["column"]
        reason = None
        if a == "set":
            if c not in editable:
                reason = "no editable column %r" % c
            elif row is None:
                reason = "row is no longer in the game data"
            elif fmt(row[c]) != r["replaced"]:
                reason = "game value changed from %r to %r" % (r["replaced"], fmt(row[c]))
        elif a == "add":
            if c and c not in editable:
                reason = "no editable column %r" % c
            elif row is not None:
                reason = "the game data now has this row"
        elif a == "delete":
            if row is None:
                reason = "row is no longer in the game data"
            elif json.loads(r["replaced"] or "{}") != json.loads(snapshot(table, row)):
                reason = "game row changed since it was deleted"
        if a == "add" and reason:
            bad_add.setdefault(r["key"], reason)
        out.append([r, reason])
    for pair in out:                    # an added row applies whole or not at all
        r = pair[0]
        if r["action"] == "add" and r["key"] in bad_add and not pair[1]:
            pair[1] = bad_add[r["key"]]
    return [tuple(p) for p in out]


def _where(keys):
    return " AND ".join("%s IS ?" % k for k in keys)


def apply(con, table, recs):
    """Apply overrides to an open catalogue. Returns (applied count, [(override, reason)])."""
    cols = columns(con, table)
    types = dict(cols)
    keys = KEYS[table]
    rows = table_rows(con, table)
    ok, stale = [], []
    for r, reason in classify(table, recs, rows, cols):
        (stale if reason else ok).append((r, reason))
    ok = [r for r, _ in ok]
    kv = lambda r: [typed(v, types[k]) for k, v in zip(keys, r["key"])]
    for r in ok:
        if r["action"] == "delete":
            con.execute("DELETE FROM %s WHERE %s" % (table, _where(keys)), kv(r))
    for r in ok:
        if r["action"] == "set":
            con.execute("UPDATE %s SET %s = ? WHERE %s" % (table, r["column"], _where(keys)),
                        [typed(r["value"], types[r["column"]])] + kv(r))
    added = {}
    for r in ok:
        if r["action"] == "add":
            added.setdefault(r["key"], (r, {}))[1].update({r["column"]: r["value"]} if r["column"] else {})
    for key, (r, vals) in added.items():
        names = list(keys) + list(vals)
        try:
            con.execute("INSERT INTO %s (%s) VALUES (%s)" % (table, ", ".join(names), ", ".join("?" * len(names))),
                        kv(r) + [typed(v, types[c]) for c, v in vals.items()])
        except sqlite3.IntegrityError as e:
            stale.extend((x, "can't add row: %s" % e) for x in ok if x["action"] == "add" and x["key"] == key)
            ok = [x for x in ok if not (x["action"] == "add" and x["key"] == key)]
    return len(ok), stale


def paths(build_dir=BUILD_DIR):
    return os.path.join(build_dir, EXTRACTED_NAME), os.path.join(build_dir, CATALOGUE_NAME)


def build(build_dir=BUILD_DIR, overrides_dir=OVERRIDES_DIR):
    """extracted.db + overrides -> catalogue.db. Returns {"applied": n, "stale": [(table, override, reason)]}."""
    extracted, out = paths(build_dir)
    if not os.path.exists(extracted):
        raise FileNotFoundError("No extracted data at %s. Run: trtool extract" % extracted)
    ovs = load(overrides_dir)
    tmp = out + ".tmp"
    shutil.copyfile(extracted, tmp)
    con = sqlite3.connect(tmp)
    applied, stale = 0, []
    try:
        for table in TABLES:
            if ovs.get(table):
                n, bad = apply(con, table, ovs[table])
                applied += n
                stale += [(table, r, why) for r, why in bad]
        con.executemany("INSERT OR REPLACE INTO meta VALUES (?, ?)", [
            ("overrides_applied", str(applied)), ("overrides_stale", str(len(stale))),
            ("built_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))])
        con.commit()
    finally:
        con.close()
    os.replace(tmp, out)
    return {"applied": applied, "stale": stale}


def stale(build_dir=BUILD_DIR, overrides_dir=OVERRIDES_DIR):
    """[(table, override, reason)] for overrides the extracted data no longer supports."""
    extracted, _ = paths(build_dir)
    con = sqlite3.connect(extracted)
    try:
        out = []
        for table, recs in load(overrides_dir).items():
            cols = columns(con, table)
            out += [(table, r, why) for r, why in classify(table, recs, table_rows(con, table), cols) if why]
        return out
    finally:
        con.close()


def needs_build(build_dir=BUILD_DIR, overrides_dir=OVERRIDES_DIR):
    extracted, out = paths(build_dir)
    if not os.path.exists(extracted):
        return False
    if not os.path.exists(out):
        return True
    built = os.path.getmtime(out)
    inputs = [extracted]
    if os.path.isdir(overrides_dir):
        inputs.append(overrides_dir)    # catches deleted files
        inputs += [os.path.join(overrides_dir, f) for f in os.listdir(overrides_dir)]
    return any(os.path.getmtime(p) > built for p in inputs)


# --- diffing a desired state (from a workbook) ----------------------------------
def diff(table, cols, rows, desired):
    """Overrides (no note/date) that turn the extracted `rows` into `desired`.

    desired: {key tuple: {column: fmt string}}, every row the user wants. A
    column missing from a desired row is left as extracted."""
    keys = KEYS[table]
    editable = [c for c, _ in cols if c not in keys]
    out = []
    for k, want in desired.items():
        row = rows.get(k)
        if row is None:
            lines = [make(table, k, "add", c, want[c]) for c in editable if want.get(c, "") != ""]
            out += lines or [make(table, k, "add")]
        else:
            out += [make(table, k, "set", c, want[c], fmt(row[c]))
                    for c in editable if c in want and want[c] != fmt(row[c])]
    out += [make(table, k, "delete", replaced=snapshot(table, row)) for k, row in rows.items() if k not in desired]
    return out


def _refresh(table, r, row, editable):
    """A stale override the user chose to keep, re-based on the current game data.
    Returns the replacement overrides, or None when it can't be re-based."""
    if row is None:
        return None
    if r["action"] == "set":
        return [dict(r, replaced=fmt(row[r["column"]]))]
    if r["action"] == "delete":
        return [dict(r, replaced=snapshot(table, row))]
    if r["action"] == "add" and r["column"] in editable and r["value"] != fmt(row[r["column"]]):
        return [dict(r, action="set", replaced=fmt(row[r["column"]]))]
    return []


def merge(table, previous, new, rows, cols, notes=None, decisions=None, today=None):
    """The table's override list after an import.

    new:       diff() of the workbook against the extracted rows
    previous:  the overrides on disk
    notes:     {key: note typed in the workbook}, or None to keep the notes on disk
    decisions: {(key, action, column): 'keep' | 'drop'} for stale overrides
    Keeps each override's date when it's unchanged. Stale previous
    overrides the workbook didn't touch survive (they weren't applied, so the
    workbook shows the game value) unless the user drops or keeps (re-bases) them.
    Returns (overrides, [messages])."""
    decisions = decisions or {}
    today = today or datetime.now().date().isoformat()
    keys = KEYS[table]
    editable = [c for c, _ in cols if c not in keys]
    prev = {(r["key"], r["action"], r["column"]): r for r in previous}
    out, msgs = [], []
    for r in new:
        p = prev.get((r["key"], r["action"], r["column"]))
        same = p and p["value"] == r["value"] and p["replaced"] == r["replaced"]
        r["note"] = notes.get(r["key"], "") if notes is not None else (p["note"] if p else "")
        r["date"] = p["date"] if same and p["date"] else today
        out.append(r)
    touched_cells = {(r["key"], r["column"]) for r in new}
    touched_rows = {r["key"] for r in new if r["action"] != "set"}
    for r, why in classify(table, previous, rows, cols):
        if not why:
            continue
        if (r["key"], r["column"]) in touched_cells or r["key"] in touched_rows:
            continue                    # the workbook made a fresh override for this cell or row
        d = decisions.get((r["key"], r["action"], r["column"]), "")
        label = "%s %s %s %s" % (table, key_text(r["key"]), r["action"], r["column"])
        if d == "drop":
            msgs.append("dropped stale override: %s" % label)
            continue
        if d == "keep":
            fresh = _refresh(table, r, rows.get(r["key"]), editable)
            if fresh is not None:
                for x in fresh:
                    x["date"] = today
                out += fresh
                msgs.append("kept stale override, re-based on the current game data: %s" % label)
                continue
            msgs.append("can't keep (row is gone from the game data), left stale: %s" % label)
        out.append(r)
    return out, msgs
