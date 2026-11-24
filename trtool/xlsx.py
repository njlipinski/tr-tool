"""Excel round trip for the catalogue: export-xlsx and import-xlsx.

export: one sheet per catalogue table (overrides applied), with a readable name
next to every ID column. Name columns are in [brackets] with grey text: they're
derived and ignored on import. Key columns have a blue header. Each sheet ends
with a `note` column for the user's reason for a change.

import: compares each sheet to the *extracted* data and saves only the
differences as overrides (trtool/overrides.py), then rebuilds the catalogue.
Changed cells become `set`, new rows `add`, removed rows `delete`.

openpyxl is imported only here, inside the functions.
"""
import os
import sqlite3
from datetime import datetime

from . import overrides as ov

INSTALL_HINT = "This command needs openpyxl: python -m pip install openpyxl"

# ID columns that get a [name] column next to them: column -> what it points at.
REFS = {
    "group_members": {"group_id": "item", "member_id": "item", "mod_id": "item"},
    "recipes": {"output_id": "item", "replaced_by": "recipe"},
    "recipe_inputs": {"recipe_id": "recipe", "input_id": "item", "mod_id": "item"},
    "crafter_recipes": {"crafter_id": "item", "recipe_id": "recipe"},
    "crops": {"seed_id": "item"},
    "crop_harvests": {"crop_id": "crop", "item_id": "item"},
    "fish": {"item_id": "item"},
    "shop_items": {"shop_id": "shop", "item_id": "item"},
    "shop_recipes": {"shop_id": "shop", "recipe_id": "recipe"},
}
NOTE = "note"
STALE_SHEET = "Stale overrides"
STALE_HEADER = ("table", "key", "action", "column", "override value", "replaced (when made)",
                "game value now", "why stale", "decision")
KEY_FILL, DERIVED_GREY, STALE_FILL = "BDD7EE", "808080", "FCE4D6"


def _openpyxl():
    try:
        import openpyxl
    except ImportError:
        raise SystemExit(INSTALL_HINT)
    return openpyxl


def derived(col):
    return "[%s name]" % col


def _namers(con):
    items = {r[0]: r[1] for r in con.execute("SELECT id, name FROM items")}
    recipes = {r[0]: items.get(r[1]) for r in con.execute("SELECT recipe_id, output_id FROM recipes")}
    shops = {r[0]: r[1] for r in con.execute("SELECT shop_id, label FROM shops")}
    crops = {r[0]: r[1] for r in con.execute("SELECT crop_id, label FROM crops")}
    return {"item": items, "recipe": recipes, "shop": shops, "crop": crops}


def _width(ws, n_cols, widths):
    from openpyxl.utils import get_column_letter
    for i in range(n_cols):
        ws.column_dimensions[get_column_letter(i + 1)].width = min(max(widths[i] + 2, 8), 50)


def export(out_path, build_dir=ov.BUILD_DIR, overrides_dir=ov.OVERRIDES_DIR):
    """Write the workbook. Returns {table: rows written}."""
    openpyxl = _openpyxl()
    from openpyxl.styles import Font, PatternFill
    from . import catalogue
    ex_path, cat_path = ov.paths(build_dir)
    if not os.path.exists(ex_path):
        raise SystemExit("No extracted data at %s. Run: trtool extract" % ex_path)
    con = catalogue.connect(cat_path, overrides_dir)
    names = _namers(con)
    meta = dict(con.execute("SELECT key, value FROM meta").fetchall())
    notes = {}
    for table, recs in ov.load(overrides_dir).items():
        for r in recs:
            if r["note"]:
                notes.setdefault((table, r["key"]), [])
                if r["note"] not in notes[(table, r["key"])]:
                    notes[(table, r["key"])].append(r["note"])
    stale = ov.stale(build_dir, overrides_dir)

    wb = openpyxl.Workbook()
    about = wb.active
    about.title = "About"
    bold, grey = Font(bold=True), Font(color=DERIVED_GREY)
    for row in (
        ("TR Tool catalogue",),
        ("game_version", meta.get("game_version")),
        ("extracted_at", meta.get("extracted_at")),
        ("overrides applied", meta.get("overrides_applied")),
        ("overrides stale", str(len(stale))),
        (),
        ("How to edit",),
        ("Change cells, add rows or delete rows in the table sheets, then run: trtool import-xlsx FILE",),
        ("Only differences from the extracted game data are saved (data/overrides/<table>.tsv).",),
        ("Blue headers are key columns: they identify the row. Changing one is a delete plus an add.",),
        ("[Bracketed] grey columns are derived names. They're ignored on import.",),
        ("note: why you changed the row. Saved with its overrides.",),
        ("Stale overrides: the game changed under these. Set decision to keep or drop; blank leaves them stale.",),
    ):
        about.append(row)
    about["A1"].font = Font(bold=True, size=14)
    about["A7"].font = bold
    about.column_dimensions["A"].width = 22

    counts = {}
    for table in ov.TABLES:
        ws = wb.create_sheet(table)
        cols = [c for c, _ in ov.columns(con, table)]
        refs = REFS.get(table, {})
        header, kinds = [], []
        for c in cols:
            header.append(c)
            kinds.append("key" if c in ov.KEYS[table] else "edit")
            if c in refs:
                header.append(derived(c))
                kinds.append("derived")
        header.append(NOTE)
        kinds.append("note")
        ws.append(header)
        for i, k in enumerate(kinds):
            cell = ws.cell(row=1, column=i + 1)
            cell.font = Font(bold=True, color=DERIVED_GREY if k == "derived" else None)
            if k == "key":
                cell.fill = PatternFill("solid", fgColor=KEY_FILL)
        widths = [len(h) for h in header]
        order = ", ".join(ov.KEYS[table])
        n = 0
        for r in con.execute("SELECT * FROM %s ORDER BY %s" % (table, order)):
            row = dict(zip(cols, r))
            key = tuple(ov.fmt(row[c]) for c in ov.KEYS[table])
            out = []
            for c in cols:
                out.append(row[c])
                if c in refs:
                    out.append(names[refs[c]].get(row[c]) if row[c] is not None else None)
            out.append("; ".join(notes.get((table, key), [])) or None)
            ws.append(out)
            n += 1
            for i, v in enumerate(out):
                if isinstance(v, str):
                    if v.startswith("="):           # text, not a formula
                        ws.cell(row=n + 1, column=i + 1).data_type = "s"
                    widths[i] = max(widths[i], min(len(v), 50))
                elif v is not None:
                    widths[i] = max(widths[i], len(str(v)))
                if kinds[i] == "derived":
                    ws.cell(row=n + 1, column=i + 1).font = grey
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        _width(ws, len(header), widths)
        counts[table] = n

    ws = wb.create_sheet(STALE_SHEET)
    ws.append(STALE_HEADER)
    for c in ws[1]:
        c.font = bold
    ex = sqlite3.connect(ex_path)
    rows_cache = {}
    for table, r, why in stale:
        rows = rows_cache.setdefault(table, ov.table_rows(ex, table))
        row = rows.get(r["key"])
        now = "" if row is None else (ov.fmt(row.get(r["column"])) if r["column"] else ov.snapshot(table, row))
        ws.append([table, ov.key_text(r["key"]), r["action"], r["column"], r["value"], r["replaced"], now, why, None])
        for c in ws[ws.max_row]:
            c.fill = PatternFill("solid", fgColor=STALE_FILL)
    ex.close()
    ws.freeze_panes = "A2"
    _width(ws, len(STALE_HEADER), [len(h) for h in STALE_HEADER])
    con.close()
    wb.save(out_path)
    return counts


class ImportError_(Exception):
    """The workbook has problems; nothing was written."""


def _read_sheet(ws, table, cols):
    """{key: {column: fmt}}, {key: note}, [errors]."""
    types = dict(cols)
    keys = ov.KEYS[table]
    rows = ws.iter_rows(values_only=True)
    header = next(rows, None)
    errors = []
    if not header:
        return {}, {}, ["%s: sheet is empty (no header row)" % table]
    idx = {}
    for i, h in enumerate(header):
        h = (h or "").strip() if isinstance(h, str) else h
        if h in (None, "") or (isinstance(h, str) and h.startswith("[")):
            continue
        if h != NOTE and h not in types:
            errors.append("%s: unknown column %r" % (table, h))
        elif h in idx:
            errors.append("%s: column %r appears twice" % (table, h))
        else:
            idx[h] = i
    missing = [k for k in keys if k not in idx]
    if missing:
        errors.append("%s: key column(s) missing: %s" % (table, ", ".join(missing)))
    if errors:
        return {}, {}, errors
    desired, notes = {}, {}
    for n, vals in enumerate(rows, start=2):
        get = lambda c: vals[idx[c]] if idx[c] < len(vals) else None
        if all(v is None or (isinstance(v, str) and not v.strip()) for v in vals):
            continue
        row, bad = {}, False
        for c in idx:
            if c == NOTE:
                continue
            try:
                row[c] = ov.check(get(c), types[c])
            except ValueError as e:
                errors.append("%s row %d, %s: %s" % (table, n, c, e))
                bad = True
        if bad:
            continue
        key = tuple(row.pop(k) for k in keys)
        if any(k == "" for k, c in zip(key, keys) if c != "mod_id"):
            errors.append("%s row %d: key column empty" % (table, n))
            continue
        if key in desired:
            errors.append("%s row %d: duplicate key %s" % (table, n, ov.key_text(key)))
            continue
        desired[key] = row
        if NOTE in idx and get(NOTE) not in (None, ""):
            notes[key] = ov.fmt(get(NOTE)).strip()
    return desired, (notes if NOTE in idx else None), errors


def _read_decisions(wb, errors):
    if STALE_SHEET not in wb.sheetnames:
        return {}
    out = {}
    rows = wb[STALE_SHEET].iter_rows(values_only=True)
    next(rows, None)
    for n, v in enumerate(rows, start=2):
        if not v or v[0] is None:
            continue
        v = list(v) + [None] * (len(STALE_HEADER) - len(v))
        d = (ov.fmt(v[8]).strip().lower())
        if d not in ("", "keep", "drop"):
            errors.append("%s row %d: decision must be keep, drop or blank" % (STALE_SHEET, n))
            continue
        if d:
            table = ov.fmt(v[0])
            key = tuple(ov.fmt(v[1]).split("|")) if table in ov.KEYS else ()
            out.setdefault(table, {})[(key, ov.fmt(v[2]), ov.fmt(v[3]))] = d
    return out


def import_(xlsx_path, build_dir=ov.BUILD_DIR, overrides_dir=ov.OVERRIDES_DIR, dry_run=False, today=None, log=print):
    """Diff the workbook against the extracted data and save the overrides.
    Returns {table: (previous count, new count)} of tables whose overrides changed.
    Raises ImportError_ (listing every problem) without writing anything."""
    openpyxl = _openpyxl()
    today = today or datetime.now().date().isoformat()
    ex_path, _ = ov.paths(build_dir)
    if not os.path.exists(ex_path):
        raise SystemExit("No extracted data at %s. Run: trtool extract" % ex_path)
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    con = sqlite3.connect(ex_path)
    previous = ov.load(overrides_dir)
    errors, results, msgs = [], {}, []
    decisions = _read_decisions(wb, errors)
    try:
        for table in ov.TABLES:
            if table not in wb.sheetnames:
                msgs.append("%s: no sheet, its overrides are left as they are" % table)
                continue
            cols = ov.columns(con, table)
            desired, notes, errs = _read_sheet(wb[table], table, cols)
            errors += errs
            if errs:
                continue
            rows = ov.table_rows(con, table)
            new = ov.diff(table, cols, rows, desired)
            prev = previous.get(table, [])
            merged, m = ov.merge(table, prev, new, rows, cols, notes, decisions.get(table), today)
            msgs += m
            def sig(rs):
                return sorted(tuple(r.get(f, "") for f in ("action", "column", "value", "replaced", "note", "date"))
                              + r["key"] for r in rs)
            if sig(prev) != sig(merged):
                results[table] = (prev, merged)
    finally:
        con.close()
        wb.close()
    if errors:
        raise ImportError_("\n".join(errors))
    for m in msgs:
        log(m)
    for table, (prev, merged) in results.items():
        old = {_ident(r) for r in prev}
        new = {_ident(r) for r in merged}
        log("%-16s %d overrides (%+d new, %d removed)" % (table, len(merged), len(new - old), len(old - new)))
        if not dry_run:
            ov.save(table, merged, overrides_dir)
    if not results:
        log("No changes to the overrides.")
    return {t: (len(p), len(m)) for t, (p, m) in results.items()}


def _ident(r):
    return (r["key"], r["action"], r["column"], r["value"], r["replaced"])
