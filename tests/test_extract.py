import os

import pytest

from trtool import extract
from trtool.cli import main

GAME_DIR = os.environ.get("TRTOOL_GAME_DIR")


def _fake_install(root, platform="Windows"):
    data = root / platform / "TravellersRest_Data" if platform else root / "TravellersRest_Data"
    (data / "Managed").mkdir(parents=True)
    return data


@pytest.mark.parametrize("platform", ["Windows", None])
def test_locate_data_dir_from_root(tmp_path, platform):
    data = _fake_install(tmp_path, platform)
    assert extract.locate_data_dir(str(tmp_path)) == str(data)


def test_locate_data_dir_accepts_data_folder(tmp_path):
    data = _fake_install(tmp_path)
    assert extract.locate_data_dir(str(data)) == str(data)


def test_locate_data_dir_errors(tmp_path):
    with pytest.raises(extract.GameDirError):
        extract.locate_data_dir(str(tmp_path / "missing"))
    with pytest.raises(extract.GameDirError):
        extract.locate_data_dir(str(tmp_path))  # empty: no *_Data


def test_asset_files_order(tmp_path):
    for n in ("level10", "level2", "sharedassets1.assets", "resources.assets",
              "globalgamemanagers", "globalgamemanagers.assets", "level2.resS", "app.info"):
        (tmp_path / n).write_bytes(b"")
    names = [os.path.basename(p) for p in extract.asset_files(str(tmp_path))]
    assert names == ["globalgamemanagers", "globalgamemanagers.assets", "level2", "level10",
                     "resources.assets", "sharedassets1.assets"]


@pytest.mark.skipif(not GAME_DIR, reason="set TRTOOL_GAME_DIR to the game install")
def test_explore_smoke(tmp_path):
    data = extract.locate_data_dir(GAME_DIR)
    out = tmp_path / "explore"
    extract.explore(data, str(out), files=[os.path.join(data, "sharedassets9.assets")], log=lambda *_: None)
    text = (out / "scripts.tsv").read_text(encoding="utf-8")
    assert text.startswith("file\tclass\tassembly\tcount")
    assert "sharedassets9.assets" in text


@pytest.fixture(scope="module")
def real_build(tmp_path_factory):
    """A build dir holding a fresh extracted.db."""
    from trtool import overrides
    from trtool.extract import catalogue as ex
    build = str(tmp_path_factory.mktemp("build"))
    ex.extract(GAME_DIR, overrides.paths(build)[0], log=lambda *_: None)
    return build


@pytest.fixture(scope="module")
def real_catalogue(real_build):
    from trtool import catalogue, overrides
    return catalogue.Catalogue(catalogue.connect(overrides.paths(real_build)[0]))


@pytest.mark.skipif(not GAME_DIR, reason="set TRTOOL_GAME_DIR to the game install")
def test_real_xlsx_round_trip_is_clean(real_build, tmp_path, capsys):
    """Exporting the real catalogue and importing it untouched saves no overrides."""
    pytest.importorskip("openpyxl")
    ovd, book = str(tmp_path / "overrides"), str(tmp_path / "c.xlsx")
    args = ["--build-dir", real_build, "--overrides-dir", ovd]
    main(["export-xlsx", "-o", book] + args)
    main(["import-xlsx", book] + args)
    assert "No changes" in capsys.readouterr().out
    assert not os.path.exists(ovd)


@pytest.mark.skipif(not GAME_DIR, reason="set TRTOOL_GAME_DIR to the game install")
def test_extract_matches_known_facts(real_catalogue):
    """The verified facts in CLAUDE.md."""
    c = real_catalogue
    con = c.con
    assert {i: c.name(i) for i in (1245, 148, 1248, 3437, 1246, 3073, 1376, 3016, 3018)} == {
        1245: "Beef", 148: "Lime", 1248: "Lamb Meat", 3437: "Sardine", 1246: "Pork",
        3073: "Wild Berries", 1376: "Shrimp", 3016: "Corn", 3018: "Wheat"}
    assert c.name(-34) == "Minced Ingredients" and c.expand(-34) == {1276, 1453}
    assert c.name(-23) == "Milk" and c.expand(-23) == {1252, 1253}
    assert {1221, 1245, 1246, 1247, 1248, 1249} <= c.expand(-1)
    assert {1280, 1282, 1284, 1286, 1288, 1289, 1290} == c.expand(-4)   # no unaged, no Cream Cheese

    r = con.execute("SELECT * FROM recipes WHERE recipe_id = 321").fetchone()
    assert (r["output_id"], r["minutes"], r["fuel"], r["output_qty"], r["reputation"]) == (1266, 50, 10, 20, 10)
    ins = [(x[0], x[1]) for x in con.execute(
        "SELECT input_id, qty FROM recipe_inputs WHERE recipe_id = 321 ORDER BY slot")]
    assert ins == [(-34, 2), (-5, 20), (-4, 2)]
    crafters = {x[0] for x in con.execute("SELECT crafter_id FROM crafter_recipes WHERE recipe_id = ?", (321,))}
    assert 672 in crafters                                              # Oven
    assert {x[0] for x in con.execute("SELECT crafter_id FROM crafter_recipes WHERE recipe_id = 334")} == {667}
    r = con.execute("SELECT * FROM recipes WHERE recipe_id = 307").fetchone()
    assert (r["output_id"], r["minutes"], r["fuel"], r["output_qty"]) == (1220, 120, 10, 5)
    assert [x[0] for x in con.execute("SELECT input_id FROM recipe_inputs WHERE recipe_id = 307 ORDER BY slot")] \
        == [1222, 1252]
    meta = dict(con.execute("SELECT key, value FROM meta").fetchall())
    assert meta["game_version"].count(".") == 3 and meta["schema_version"]


@pytest.mark.skipif(not GAME_DIR, reason="set TRTOOL_GAME_DIR to the game install")
def test_learned_save_pairs_are_explained(real_catalogue):
    """Every dish/ingredient pair learned from saves fits leaf_inputs (the save flattening model)."""
    from trtool import db
    rows = db.read_tsv(os.path.join(db.DATA, "dish_ingredients.tsv"))
    missing = [(r["dish_id"], r["ingredient_id"]) for r in rows
               if int(r["ingredient_id"]) not in real_catalogue.leaf_inputs(int(r["dish_id"]))]
    assert not missing


@pytest.mark.skipif(not GAME_DIR, reason="set TRTOOL_GAME_DIR to the game install")
def test_game_version():
    v = extract.game_version(extract.locate_data_dir(GAME_DIR))
    assert v and v.count(".") == 3 and v.startswith("0.")
