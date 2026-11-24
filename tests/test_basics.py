import os
import shutil

import pytest

from trtool import db, learn, report
from trtool.cli import main

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_SAVE = os.environ.get("TRTOOL_TEST_SAVE")


def test_money():
    assert report.money(391773) == "39g 17s 73c"
    assert report.money(953) == "9s 53c"
    assert report.money(5) == "5c"
    assert report.money(-150) == "-1s 50c"


def test_build_db_merges_curated_over_wiki(tmp_path):
    data = tmp_path / "data"
    (data / "raw").mkdir(parents=True)
    (data / "raw" / "wiki_items.tsv").write_text("12\tLager\tDrinks\n1245\t\t\n", encoding="utf-8")
    (data / "items_curated.tsv").write_text(
        "id\tname\tcategory\tserving\tconfidence\tbasis\n"
        "12\t\t\ttap\t\t\n"
        "1245\tBeef\tIngredient\t\tconfirmed\tin game\n", encoding="utf-8")
    con = db.build(str(tmp_path / "t.db"), str(data))
    con.row_factory = __import__("sqlite3").Row
    names = db.Names(con)
    assert names(12) == "Lager" and names.on_tap(12)
    assert names(1245) == "Beef"
    assert names(99) == "#99"


class FakeSave:
    date_label = "Y1 Autumn W3 Sun"
    date = {"day_number": 77, "hour": 6, "minute": 1}
    rep = {"reputation": 20, "progress": 28000, "arcane_reputation": 0, "arcane_progress": 0}

    def reputation(self):
        return self.rep

    def cooked_instances(self):
        yield 1365, [1245, 1275, 148]

    def recent_recipes(self):
        return [(403, 1365, [(1276, 2), (148, 2)])]


def test_learn_is_idempotent_per_date(tmp_path):
    for f in ("dish_ingredients.tsv", "recipe_inputs.tsv"):
        shutil.copy(os.path.join(ROOT, "data", f), tmp_path / f)
        (tmp_path / f).write_text((tmp_path / f).read_text(encoding="utf-8").splitlines()[0] + "\n",
                                  encoding="utf-8")
    first = learn.learn(FakeSave(), str(tmp_path))
    second = learn.learn(FakeSave(), str(tmp_path))
    assert first["dish_pairs_new"] == 3 and second["dish_pairs_new"] == 0
    rows = db.read_tsv(str(tmp_path / "dish_ingredients.tsv"))
    assert {r["seen_count"] for r in rows} == {"1"}


def test_reputation_history(tmp_path):
    from trtool import analysis
    s = FakeSave()
    assert learn.learn_reputation(s, str(tmp_path)) is True
    assert learn.learn_reputation(s, str(tmp_path)) is False          # same day, same value
    later = FakeSave()
    later.date_label, later.date = "Y1 Autumn W4 Mon", {"day_number": 78, "hour": 6, "minute": 0}
    later.rep = dict(s.rep, progress=28092)
    learn.learn_reputation(later, str(tmp_path))
    rows = db.read_tsv(str(tmp_path / "reputation.tsv"))
    assert [(r["day_number"], r["progress"]) for r in rows] == [("77", "28000"), ("78", "28092")]
    # the current save is included even when it wasn't learned (report --no-learn)
    now = FakeSave()
    now.date_label, now.date = "Y1 Autumn W4 Tue", {"day_number": 79, "hour": 6, "minute": 0}
    now.rep = dict(s.rep, reputation=21, progress=100)
    hist = analysis.reputation_history(now, str(tmp_path))
    assert [(h["day_number"], h["gained"], h["level_up"]) for h in hist] == [
        (77, None, False), (78, 92, False), (79, None, True)]


@pytest.mark.skipif(not REAL_SAVE, reason="set TRTOOL_TEST_SAVE to a .save file")
def test_real_save_end_to_end(tmp_path):
    from trtool.save import Save
    s = Save(REAL_SAVE)
    d = s.date
    assert 1 <= d["week"] <= 4 and d["weekday"] in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    assert s.trends(0) and s.trends(1)
    assert any(m["where"].startswith("keg") for m in s.menu())
    out = tmp_path / "r.html"
    main(["--db", str(tmp_path / "t.db"), "report", REAL_SAVE, "-o", str(out), "--no-learn"])
    page = out.read_text(encoding="utf-8")
    assert page.index("This week") < page.index("Daily stats") < page.index("Next week")
    assert "Reputation" in page
    assert d["day_number"] >= 1 and s.reputation()["reputation"] is not None
