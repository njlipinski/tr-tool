"""Queries over build/catalogue.db (written by `trtool extract`). Stdlib only.

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

from .db import ROOT

DEFAULT_PATH = os.path.join(ROOT, "build", "catalogue.db")


def connect(path=DEFAULT_PATH):
    if not os.path.exists(path):
        raise FileNotFoundError("No catalogue at %s. Run: trtool extract" % path)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


class Catalogue:
    def __init__(self, con):
        self.con = con
        self.items = {r["id"]: dict(r) for r in con.execute("SELECT * FROM items")}
        self.members = {}
        for r in con.execute("SELECT group_id, member_id FROM group_members"):
            self.members.setdefault(r[0], []).append(r[1])
        self.recipes = {r["recipe_id"]: dict(r) for r in con.execute("SELECT * FROM recipes WHERE replaced = 0")}
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
