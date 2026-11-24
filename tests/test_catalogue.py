"""Catalogue helpers on a small hand-built database (no game needed).

IDs and recipes mirror the real game (see CLAUDE.md facts) so the fixture reads naturally.
"""
import os
import sqlite3

import pytest

from trtool import catalogue

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA = os.path.join(ROOT, "trtool", "catalogue.sql")

ITEMS = {  # id: (name, must_age)
    -1: ("Meat", 0), -4: ("Cheese", 0), -5: ("Bread", 0), -34: ("Minced Ingredients", 0),
    1245: ("Beef", 0), 1248: ("Lamb Meat", 0), 1276: ("Minced Meat", 0), 1453: ("Minced Fish", 0),
    1267: ("Bread", 0), 1283: ("Unaged Emmental Cheese", 1), 1284: ("Emmental Cheese", 0),
    1266: ("Cheeseburger", 0), 9999: ("Old Burger", 0),
}
MEMBERS = [  # group, member, rule, ingredient_type
    (-1, 1245, "type", 6), (-1, 1248, "type", 6),
    (-34, 1276, "explicit", None), (-34, 1453, "explicit", None),
    (-4, 1283, "type", 9), (-4, 1284, "type", 9),
    (-5, 1267, "explicit", None),
]
RECIPES = [  # id, output, replaced, inputs
    (321, 1266, 0, [-34, -5, -4]),
    (334, 1276, 0, [-1]),
    (900, 9999, 1, [1245]),     # replaced: must be ignored
]


@pytest.fixture
def cat(tmp_path):
    con = sqlite3.connect(str(tmp_path / "c.db"))
    with open(SCHEMA, encoding="utf-8") as f:
        con.executescript(f.read())
    for i, (name, must_age) in ITEMS.items():
        con.execute("INSERT INTO items (id, name, name_lang, kind, class, must_age) VALUES (?,?,?,?,?,?)",
                    (i, name, "en", "group" if i < 0 else "item", "IngredientGroup" if i < 0 else "Food", must_age))
    con.executemany("INSERT INTO group_members (group_id, member_id, rule, ingredient_type) VALUES (?,?,?,?)", MEMBERS)
    for rid, out, replaced, ins in RECIPES:
        con.execute("INSERT INTO recipes (recipe_id, output_id, output_qty, save_ingredients, replaced) "
                    "VALUES (?,?,1,1,?)", (rid, out, replaced))
        for slot, i in enumerate(ins):
            con.execute("INSERT INTO recipe_inputs (recipe_id, slot, input_id, qty) VALUES (?,?,?,1)", (rid, slot, i))
    con.commit()
    con.row_factory = sqlite3.Row
    return catalogue.Catalogue(con)


def test_expand_skips_items_that_must_age(cat):
    assert cat.expand(-4) == {1284}
    assert cat.expand(-1) == {1245, 1248}


def test_leaf_inputs_follow_groups_and_intermediates(cat):
    leaves = cat.leaf_inputs(1266)
    assert {1248, 1245, 1284, 1267} <= set(leaves)
    assert 1283 not in leaves                            # unaged cheese can't be used
    assert leaves[1248] == [1266, -34, 1276, -1, 1248]   # Cheeseburger <- Minced <- Minced Meat <- Meat <- Lamb


def test_replaced_recipes_are_ignored(cat):
    assert cat.leaf_inputs(9999) == {}
    assert 900 not in cat.uses(1245)


def test_uses_through_groups_and_intermediates(cat):
    u = cat.uses(1245)
    assert u[334] == [1245, 1276]                        # Beef -> Minced Meat
    assert u[321] == [1245, 1276, 1266]                  # ... -> Cheeseburger


def _sellable(con, item, price, food_type=1):
    con.execute("UPDATE items SET can_be_sold = 1, food_type = ?, sell_price_copper = ? WHERE id = ?",
                (food_type, price, item))


def test_known_recipes_limit_chains(cat):
    con = cat.con
    con.execute("UPDATE recipes SET unlock = 1")
    con.execute("UPDATE recipes SET unlock = 0 WHERE recipe_id = 334")      # basic: needs no unlocking
    assert catalogue.known_recipe_ids(con, [321]) == {321, 334}
    only_burger = catalogue.Catalogue(con, {321})
    leaves = only_burger.leaf_inputs(1266)
    assert 1276 in leaves and 1245 not in leaves         # Minced Meat can't be made from Beef without 334
    assert 334 not in only_burger.recipes


def test_serving_and_price(cat):
    _sellable(cat.con, 1266, 283)
    c = catalogue.Catalogue(cat.con)
    assert c.serving(1266) == "food" and c.price(1266) == 283
    assert c.serving(1276) is None                       # not sellable


def test_makeable_suggestions(cat):
    from trtool import analysis
    con = cat.con
    _sellable(con, 1266, 283)
    con.execute("INSERT INTO items (id, name, kind, class, can_be_sold, food_type, sell_price_copper) "
                "VALUES (1300, 'Steak', 'item', 'Food', 1, 1, 500)")
    con.execute("INSERT INTO recipes (recipe_id, output_id, output_qty, save_ingredients, replaced) "
                "VALUES (950, 1300, 4, 1, 0)")
    con.execute("INSERT INTO recipe_inputs VALUES (950, 0, 1245, NULL, 1)")   # Beef as a fixed input
    con.execute("INSERT INTO items (id, name, kind, class) VALUES (672, 'Oven', 'item', 'Item')")
    con.execute("INSERT INTO crafter_recipes VALUES (672, 321)")
    c = catalogue.Catalogue(con)
    t = {"food": {"popular": [1266], "unpopular": []}, "drink": {"popular": [], "unpopular": []},
         "ingredient": {"popular": [1245], "unpopular": []}}
    make, make_with = analysis.makeable_suggestions(c, t, where={}, stored={}, menu=[])
    assert [(r["name"], r["price"], r["recipes"][0]["crafters"]) for r in make] == [("Cheeseburger", 283, ["Oven"])]
    beef = make_with[0]
    assert beef["name"] == "Beef" and beef["serving_now"] == []
    # one list, highest price first; fixed inputs are flagged
    assert [(o["name"], o["chain"], o["fixed"]) for o in beef["options"]] == [
        ("Steak", "Steak ← Beef", True),
        ("Cheeseburger", "Cheeseburger ← Minced Ingredients ← Minced Meat ← Meat ← Beef", False)]
    # a menu dish with it as a fixed input counts as serving it
    _, mw = analysis.makeable_suggestions(c, t, where={1300: ["bar 2"]}, stored={},
                                          menu=[{"item": 1300, "where": "bar 2", "ingredients": []}])
    assert mw[0]["serving_now"] == ["Steak (bar 2, fixed)"]
    # on the menu already, or stocked: not in "make"
    make, _ = analysis.makeable_suggestions(c, t, where={1266: ["bar 1"]}, stored={}, menu=[])
    assert make == []
