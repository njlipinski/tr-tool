"""Overrides on a small hand-built extracted.db, and the Excel round trip (no game needed)."""
import json
import os
import sqlite3

import pytest

from trtool import catalogue, overrides as ov
from trtool.cli import main

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA = os.path.join(ROOT, "trtool", "catalogue.sql")


@pytest.fixture
def dirs(tmp_path):
    """(build_dir, overrides_dir) with a tiny extracted.db."""
    build, ovd = tmp_path / "build", tmp_path / "overrides"
    build.mkdir()
    con = sqlite3.connect(str(build / ov.EXTRACTED_NAME))
    with open(SCHEMA, encoding="utf-8") as f:
        con.executescript(f.read())
    con.execute("INSERT INTO meta VALUES ('game_version', '0.7.6.19')")
    con.executemany("INSERT INTO items (id, name, name_lang, kind, class, price_copper) VALUES (?,?,?,?,?,?)", [
        (-34, "Minced Ingredients", "en", "group", "IngredientGroup", None),
        (1245, "Beef", "en", "item", "Food", 40),
        (1276, "Minced Meat", "en", "item", "Food", None),
        (1453, "Minced Fish", "en", "item", "Food", None),
        (2000, "=Odd name", "es", "item", "Item", None),
    ])
    con.executemany("INSERT INTO group_members (group_id, member_id, rule) VALUES (?,?,?)",
                    [(-34, 1276, "explicit"), (-34, 1453, "explicit")])
    con.execute("INSERT INTO shops VALUES (5, 'Butcher', 0, '1,4')")
    con.executemany("INSERT INTO shop_items (shop_id, item_id, weight) VALUES (?,?,?)",
                    [(5, 1245, 0.3), (5, 1276, 1.0)])
    con.commit()
    con.close()
    return str(build), str(ovd)


def write(ovd, table, recs):
    ov.save(table, [ov.make(table, *r) for r in recs], ovd)


def cat(build):
    return sqlite3.connect(os.path.join(build, ov.CATALOGUE_NAME))


def test_fmt_and_check():
    assert ov.fmt(None) == "" and ov.fmt(2.0) == "2" and ov.fmt(True) == "1"
    assert ov.fmt(0.30000001192092896) == ov.fmt(0.300000011920929)   # Excel's 15 digits
    assert ov.check("12", "INTEGER") == "12" and ov.check(12.0, "INTEGER") == "12"
    assert ov.check("", "INTEGER") == "" and ov.check("0.5", "REAL") == "0.5"
    for bad, t in (("abc", "INTEGER"), (1.5, "INTEGER"), ("x", "REAL")):
        with pytest.raises(ValueError):
            ov.check(bad, t)


def test_build_applies_set_add_delete(dirs):
    build, ovd = dirs
    write(ovd, "items", [((1245,), "set", "name", "Beef Steak", "Beef", "renamed in game"),
                         ((3000,), "add", "name", "New Thing"), ((3000,), "add", "kind", "item"),
                         ((3000,), "add", "class", "Item")])
    write(ovd, "group_members", [(("-34", "1453", "explicit", ""), "delete", "", "",
                                  json.dumps({"ingredient_type": ""}))])
    res = ov.build(build, ovd)
    assert res == {"applied": 5, "stale": []}
    c = cat(build)
    assert c.execute("SELECT name FROM items WHERE id = 1245").fetchone()[0] == "Beef Steak"
    assert c.execute("SELECT name, kind FROM items WHERE id = 3000").fetchone() == ("New Thing", "item")
    assert [r[0] for r in c.execute("SELECT member_id FROM group_members")] == [1276]
    assert dict(c.execute("SELECT * FROM meta"))["overrides_applied"] == "5"
    # extracted.db itself is untouched
    ex = sqlite3.connect(os.path.join(build, ov.EXTRACTED_NAME))
    assert ex.execute("SELECT name FROM items WHERE id = 1245").fetchone()[0] == "Beef"


def test_stale_overrides_are_not_applied(dirs):
    build, ovd = dirs
    write(ovd, "items", [((1245,), "set", "name", "Beef Steak", "Old Beef"),     # game value differs
                         ((1245,), "set", "price_copper", "50", "40"),          # fine
                         ((7777,), "set", "name", "Ghost", "Gone"),             # row gone
                         ((1276,), "add", "name", "Dup")])                      # row exists now
    write(ovd, "shop_items", [(("5", "1245"), "delete", "", "", json.dumps(
        {"always_appear": "", "unlimited": "", "min_qty": "", "max_qty": "", "weight": "0.9"}))])
    res = ov.build(build, ovd)
    assert res["applied"] == 1
    reasons = {(t, r["key"], r["column"]): why for t, r, why in res["stale"]}
    assert reasons == {
        ("items", ("1245",), "name"): "game value changed from 'Old Beef' to 'Beef'",
        ("items", ("7777",), "name"): "row is no longer in the game data",
        ("items", ("1276",), "name"): "the game data now has this row",
        ("shop_items", ("5", "1245"), ""): "game row changed since it was deleted",
    }
    c = cat(build)
    assert c.execute("SELECT name, price_copper FROM items WHERE id = 1245").fetchone() == ("Beef", 50)
    assert len(ov.stale(build, ovd)) == 4


def test_connect_rebuilds_when_overrides_change(dirs):
    build, ovd = dirs
    path = os.path.join(build, ov.CATALOGUE_NAME)
    con = catalogue.connect(path, ovd)
    assert catalogue.Catalogue(con).name(1245) == "Beef"
    con.close()                     # Windows can't replace an open file
    write(ovd, "items", [((1245,), "set", "name", "Beef Steak", "Beef")])
    os.utime(os.path.join(ovd, "items.tsv"), (2e9, 2e9))      # newer than the catalogue
    assert catalogue.Catalogue(catalogue.connect(path, ovd)).name(1245) == "Beef Steak"


def test_diff_and_merge():
    table = "items"
    cols = [("id", "INTEGER"), ("name", "TEXT"), ("price_copper", "INTEGER")]
    rows = {("1",): {"id": 1, "name": "A", "price_copper": 5}, ("2",): {"id": 2, "name": "B", "price_copper": None}}
    desired = {("1",): {"name": "A2", "price_copper": "5"}, ("3",): {"name": "C", "price_copper": ""}}
    new = ov.diff(table, cols, rows, desired)
    assert [(r["key"], r["action"], r["column"], r["value"], r["replaced"]) for r in new] == [
        (("1",), "set", "name", "A2", "A"),
        (("3",), "add", "name", "C", ""),
        (("2",), "delete", "", "", json.dumps({"name": "B", "price_copper": ""})),
    ]
    prev = [ov.make(table, ("1",), "set", "name", "A2", "A", "old note", "2026-01-01")]
    merged, _ = ov.merge(table, prev, new, rows, cols, notes=None, today="2026-11-23")
    assert merged[0]["note"] == "old note" and merged[0]["date"] == "2026-01-01"   # unchanged override
    assert merged[1]["date"] == "2026-11-23"


def test_merge_keeps_or_drops_stale():
    table = "items"
    cols = [("id", "INTEGER"), ("name", "TEXT")]
    rows = {("1",): {"id": 1, "name": "New game name"}}
    stale = ov.make(table, ("1",), "set", "name", "Mine", "Old game name", "n", "2026-01-01")
    left, _ = ov.merge(table, [stale], [], rows, cols, today="2026-11-23")
    assert left == [stale]                                       # no decision: left stale
    dropped, msgs = ov.merge(table, [stale], [], rows, cols, decisions={(("1",), "set", "name"): "drop"})
    assert dropped == [] and "dropped" in msgs[0]
    kept, _ = ov.merge(table, [stale], [], rows, cols, decisions={(("1",), "set", "name"): "keep"},
                       today="2026-11-23")
    assert kept[0]["replaced"] == "New game name" and kept[0]["value"] == "Mine"


def test_load_rejects_bad_files(tmp_path):
    (tmp_path / "nope.tsv").write_text("x\n", encoding="utf-8")
    with pytest.raises(ValueError):
        ov.load(str(tmp_path))
    os.remove(str(tmp_path / "nope.tsv"))
    (tmp_path / "items.tsv").write_text("id\taction\tcolumn\n1\tupdate\tname\n", encoding="utf-8")
    with pytest.raises(ValueError):
        ov.load(str(tmp_path))


# --- Excel ----------------------------------------------------------------------
def test_xlsx_round_trip(dirs, tmp_path, capsys):
    openpyxl = pytest.importorskip("openpyxl")
    build, ovd = dirs
    book = str(tmp_path / "c.xlsx")
    args = ["--build-dir", build, "--overrides-dir", ovd]
    main(["export-xlsx", "-o", book] + args)

    main(["import-xlsx", book] + args)                   # untouched workbook: no overrides
    assert "No changes" in capsys.readouterr().out
    assert not os.path.exists(ovd)

    wb = openpyxl.load_workbook(book)
    ws = wb["items"]
    hdr = [c.value for c in ws[1]]
    assert hdr[-1] == "note"
    for row in ws.iter_rows(min_row=2):
        if row[0].value == 1245:
            row[hdr.index("name")].value = "Beef Steak"
            row[hdr.index("note")].value = "in-game tooltip"
    ws = wb["shop_items"]
    hdr = [c.value for c in ws[1]]
    assert "[item_id name]" in hdr
    assert [c.value for c in ws[2]][hdr.index("[item_id name]")] == "Beef"
    ws.delete_rows(3)                                     # (5, 1276)
    ws.append([5, None, 1453, "ignored", 1, None, None, None, 0.5, None])
    wb.save(book)

    main(["import-xlsx", book, "--dry-run"] + args)
    assert not os.path.exists(ovd)
    main(["import-xlsx", book] + args)
    loaded = ov.load(ovd)
    assert [(r["action"], r["column"], r["value"], r["replaced"], r["note"]) for r in loaded["items"]] == [
        ("set", "name", "Beef Steak", "Beef", "in-game tooltip")]
    assert sorted((r["key"], r["action"], r["column"]) for r in loaded["shop_items"]) == [
        (("5", "1276"), "delete", ""), (("5", "1453"), "add", "always_appear"), (("5", "1453"), "add", "weight")]
    c = cat(build)
    assert c.execute("SELECT name FROM items WHERE id = 1245").fetchone()[0] == "Beef Steak"
    assert c.execute("SELECT item_id, weight FROM shop_items ORDER BY item_id").fetchall() == [(1245, 0.3), (1453, 0.5)]
    assert c.execute("SELECT name FROM items WHERE id = 2000").fetchone()[0] == "=Odd name"   # not a formula

    main(["export-xlsx", "-o", book] + args)              # re-export: same state, no new diffs
    main(["import-xlsx", book] + args)
    assert "No changes" in capsys.readouterr().out.splitlines()[-1]


def test_xlsx_stale_sheet_decisions(dirs, tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    build, ovd = dirs
    write(ovd, "items", [((1245,), "set", "name", "Mine", "Old Beef"),
                         ((1276,), "set", "name", "Mince", "Older")])
    book = str(tmp_path / "c.xlsx")
    args = ["--build-dir", build, "--overrides-dir", ovd]
    main(["export-xlsx", "-o", book] + args)
    wb = openpyxl.load_workbook(book)
    ws = wb["Stale overrides"]
    rows = list(ws.iter_rows(min_row=2))
    assert [(r[1].value, r[6].value) for r in rows] == [("1245", "Beef"), ("1276", "Minced Meat")]
    rows[0][8].value = "keep"
    rows[1][8].value = "drop"
    wb.save(book)
    main(["import-xlsx", book] + args)
    recs = ov.load(ovd)["items"]
    assert [(r["key"], r["value"], r["replaced"]) for r in recs] == [(("1245",), "Mine", "Beef")]
    assert cat(build).execute("SELECT name FROM items WHERE id = 1245").fetchone()[0] == "Mine"


def test_xlsx_import_reports_errors(dirs, tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    build, ovd = dirs
    book = str(tmp_path / "c.xlsx")
    args = ["--build-dir", build, "--overrides-dir", ovd]
    main(["export-xlsx", "-o", book] + args)
    wb = openpyxl.load_workbook(book)
    ws = wb["items"]
    hdr = [c.value for c in ws[1]]
    ws.cell(row=2, column=hdr.index("price_copper") + 1).value = "lots"
    ws.cell(row=4, column=1).value = ws.cell(row=3, column=1).value
    wb.save(book)
    with pytest.raises(SystemExit) as e:
        main(["import-xlsx", book] + args)
    assert "not a number" in str(e.value) and "duplicate key" in str(e.value)
    assert not os.path.exists(ovd)
