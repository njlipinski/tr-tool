"""Queries over build/catalogue.db (the extracted game data with the user's
overrides applied; see trtool/overrides.py). Stdlib only.

Rules applied by every helper here:
- replaced recipes (recipes.replaced = 1) are ignored;
- items that must age before use (items.must_age = 1, e.g. Unaged Brie) are
  not group members for expansion purposes.

How saves flatten ingredients (inferred from the game data plus the user's saves,
checked by tests/test_catalogue.py and `trtool validate` later):
a prepared item's `ingredientsID` lists the item chosen for each *group* slot,
following intermediates down. Fixed (non-group) inputs aren't stored, but
their own choices are carried up.
  Cheeseburger -> [Lamb Meat (Minced Ingredients -> Minced Meat -> Meat), Corn, Emmental]
  Tacos        -> [Beef, Lard (Culinary Fats, inside Tortilla), Lime (Lemon - Lime)]
A chosen item that was itself made with choices is usually replaced by those
choices (Minced Meat -> Lamb Meat), but not always (Brandy stores the Wine it
was made from). Which one happens isn't known, so leaf_inputs returns both: a
superset of what saves can contain.
"""
import os
import sqlite3

from . import overrides

DEFAULT_PATH = overrides.paths()[1]


def connect(path=DEFAULT_PATH, overrides_dir=overrides.OVERRIDES_DIR):
    """Open a catalogue. When extracted.db sits beside it, the catalogue is first
    rebuilt if it's missing or older than the extracted data or the overrides."""
    build_dir = os.path.dirname(os.path.abspath(path))
    if os.path.basename(path) == overrides.CATALOGUE_NAME and overrides.needs_build(build_dir, overrides_dir):
        overrides.build(build_dir, overrides_dir)
    if not os.path.exists(path):
        raise FileNotFoundError("No catalogue at %s. Run: trtool extract" % path)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


FOOD_TYPES = {1: "food", 2: "drink"}   # items.food_type, read off the menu items in a real save


def known_recipe_ids(con, unlocked):
    """The save's unlocked recipes plus the basic ones that need no unlocking
    (recipes.unlock = 0: flours, malts, worts, musts...)."""
    return set(unlocked) | {r[0] for r in con.execute("SELECT recipe_id FROM recipes WHERE unlock = 0")}


class Catalogue:
    def __init__(self, con, recipe_ids=None):
        """recipe_ids: only consider these recipes (e.g. known_recipe_ids()), so every
        chain the helpers return goes through recipes the player can make."""
        self.con = con
        self.items = {r["id"]: dict(r) for r in con.execute("SELECT * FROM items")}
        self.members = {}
        for r in con.execute("SELECT group_id, member_id FROM group_members"):
            self.members.setdefault(r[0], []).append(r[1])
        self.recipes = {r["recipe_id"]: dict(r) for r in con.execute("SELECT * FROM recipes WHERE replaced = 0")
                        if recipe_ids is None or r["recipe_id"] in recipe_ids}
        self.crafters = {}
        for r in con.execute("SELECT crafter_id, recipe_id FROM crafter_recipes ORDER BY crafter_id"):
            self.crafters.setdefault(r[1], []).append(r[0])
        self.inputs = {}
        for r in con.execute("SELECT recipe_id, input_id FROM recipe_inputs ORDER BY recipe_id, slot"):
            if r[0] in self.recipes:
                self.inputs.setdefault(r[0], []).append(r[1])
        self.made_by = {}
        for rid, r in self.recipes.items():
            self.made_by.setdefault(r["output_id"], []).append(rid)
        self._choices = {}

    def name(self, i):
        r = self.items.get(i)
        return (r and r["name"]) or "#%s" % i

    def is_group(self, i):
        return i is not None and i < 0

    def serving(self, i):
        """'food' or 'drink' when the item can go on the menu, else None."""
        r = self.items.get(i) or {}
        return FOOD_TYPES.get(r.get("food_type")) if r.get("can_be_sold") else None

    def price(self, i):
        """Base sell price in copper (Food.sellPrice in the game files)."""
        return (self.items.get(i) or {}).get("sell_price_copper")

    # --- groups -------------------------------------------------------------
    def expand(self, group_id, _seen=None):
        """Leaf (non-group) items a group accepts, recursively; must-age items left out."""
        seen = _seen if _seen is not None else set()
        if group_id in seen:
            return set()
        seen.add(group_id)
        out = set()
        for m in self.members.get(group_id, ()):
            if self.is_group(m):
                out |= self.expand(m, seen)
            elif not (self.items.get(m) or {}).get("must_age"):
                out.add(m)
        return out

    def groups_of(self, item_id):
        """Every group that accepts item_id, directly or through nested groups."""
        return {g for g in self.members if item_id in self.expand(g)}

    # --- save flattening ------------------------------------------------------
    def leaf_inputs(self, item_id):
        """{leaf item id: example chain [item_id, ..., leaf]} that can appear in a
        prepared item's saved `ingredientsID`. Empty when the item has no choices."""
        return self._choices_of_item(item_id, ())

    def _choices_of_item(self, item_id, stack):
        if item_id in self._choices:
            return self._choices[item_id]
        if item_id in stack:
            return {}
        out = {}
        for rid in self.made_by.get(item_id, ()):
            if not self.recipes[rid]["save_ingredients"]:
                continue
            for inp in self.inputs.get(rid, ()):
                if self.is_group(inp):
                    for m in sorted(self.expand(inp)):
                        out.setdefault(m, [item_id, inp, m])
                        for leaf, chain in self._choices_of_item(m, stack + (item_id,)).items():
                            out.setdefault(leaf, [item_id, inp] + chain)
                else:
                    for leaf, chain in self._choices_of_item(inp, stack + (item_id,)).items():
                        out.setdefault(leaf, [item_id] + chain)
        if not stack:
            self._choices[item_id] = out
        return out

    # --- uses -------------------------------------------------------------------
    def uses(self, item_id):
        """{recipe id: example chain [item_id, ..., recipe output]} for every current
        recipe the item can feed, directly, through groups, or through intermediates."""
        out = {}
        frontier = [(item_id, [item_id])]
        seen_items = set()
        while frontier:
            it, chain = frontier.pop(0)
            if it in seen_items:
                continue
            seen_items.add(it)
            accepts = {it} | (self.groups_of(it) if not self.is_group(it) else set())
            for rid, ins in self.inputs.items():
                if rid in out or not accepts.intersection(ins):
                    continue
                outp = self.recipes[rid]["output_id"]
                out[rid] = chain + [outp]
                frontier.append((outp, chain + [outp]))
        return out
