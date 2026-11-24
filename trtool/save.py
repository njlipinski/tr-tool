"""Read a Travellers Rest save into a convenient shape.

Every field accessed here was located by inspecting real saves (game
0.7.6.19). If an update renames or moves a field, fix it here: the rest of
the tool only talks to this module. Accessors use .get() so a missing field
degrades to "no data" instead of a crash.
"""
import collections

from . import nrbf

SEASONS = ["Spring", "Summer", "Autumn", "Winter"]
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

TREND_KEYS = {
    "food": ("foodTrends", "unpopularFoodTrends"),
    "drink": ("drinkTrends", "unpopularDrinkTrends"),
    "ingredient": ("ingredientTrends", "unpopularIngredientTrends"),
}

# Top-level fields that hold item slots (inventories, chests, bins).
_SLOT_LISTS = ("itemsInInventory", "itemsInActionBar", "itemsInBuildingInventory", "orderBox")


def _version(v):
    return ".".join(str(x) for x in v) if isinstance(v, list) else None


class Save:
    def __init__(self, path):
        self.path = path
        self.raw = nrbf.load(path)

    # --- headline numbers -----------------------------------------------
    @property
    def summary(self):
        r = self.raw
        return {
            "character": (r.get("characterSave") or {}).get("name"),
            "tavern": (r.get("characterSave") or {}).get("tavernName"),
            "game_version": _version(r.get("versionNumber")),
            "first_version": _version(r.get("initialVersionNumber")),
            "money_copper": r.get("money"),
            "reputation": r.get("tavernRep"),
            "reputation_progress": r.get("tavernProgress"),
            "arcane_reputation": r.get("arcaneRep"),
            "play_seconds": r.get("realGameTimeSeconds"),
        }

    # --- date -------------------------------------------------------------
    @property
    def date(self):
        t = self.raw["currentTime"]
        weekday = t["day"]["value__"]                     # 0 = Monday
        season = t["season"]["value__"]
        return {
            "year": t["year"],
            "season": SEASONS[season],
            # 1-based day count since Year 1 Spring Mon (4 seasons x 4 weeks x 7 days)
            "day_number": ((t["year"] - 1) * 4 + season) * 28 + t["week"] * 7 + weekday + 1,
            "week": t["week"] + 1,                         # save is 0-based
            "weekday": DAYS[weekday],
            "day_of_month": t["week"] * 7 + weekday + 1,
            "hour": t["hour"],
            "minute": t["min"],
            "days_to_next_trend": self.raw.get("daysToNextTrend"),
        }

    @property
    def date_label(self):
        d = self.date
        return "Y%d %s W%d %s" % (d["year"], d["season"], d["week"], d["weekday"])

    # --- trends -----------------------------------------------------------
    def trends(self, offset=0):
        """offset 0 = this week, 1 = next week (as in the in-game Trends tab).

        allTrendsSave[0] is the current week and [1] the next. Verified
        against in-game screens on 0.7.6.19; [2] and [3] look like the two
        previous weeks.
        """
        sets = self.raw.get("allTrendsSave") or []
        if offset >= len(sets):
            return None
        s = sets[offset]
        return {kind: {"popular": list(s.get(p) or []), "unpopular": list(s.get(u) or [])}
                for kind, (p, u) in TREND_KEYS.items()}

    # --- menu -------------------------------------------------------------
    @staticmethod
    def _entry(where, slot):
        x = (slot or {}).get("itemInstanceSave")
        return {"where": where,
                "item": x["itemID"] if x else None,
                "ingredients": list(x.get("ingredientsID") or []) if x else [],
                "stack": (slot or {}).get("stack", 0) if x else 0}

    def menu(self):
        """Everything customers can order: bar slots, taps, kegs (empty ones too)."""
        out = []
        for i, slot in enumerate((self.raw.get("barSave") or {}).get("slots") or [], 1):
            out.append(self._entry("bar %d" % i, slot))
        for tap in self.raw.get("beerTaps") or []:
            out.append(self._entry("tap %d" % (tap["id"] + 1), tap.get("slotSave")))
        for k, keg in enumerate(self.raw.get("barPlaceablesInside") or [], 1):
            slots = keg.get("slots") or [None]
            out.append(self._entry("keg %d" % k, slots[0]))
        return out

    # --- storage ----------------------------------------------------------
    def _all_slots(self):
        for p in self.raw.get("placedItemsSave") or []:
            for s in p.get("slots") or []:
                yield s
        for k in _SLOT_LISTS:
            for s in self.raw.get(k) or []:
                yield s

    def stored(self):
        """Total count of each item ID across chests, inventory and bins (not the menu)."""
        c = collections.Counter()
        for s in self._all_slots():
            if s and s.get("itemInstanceSave"):
                c[s["itemInstanceSave"]["itemID"]] += s.get("stack", 0)
        return c

    def cooked_instances(self):
        """(dish itemID, [ingredient itemIDs]) for every prepared item in the save.

        Covers the menu, storage and crafting outputs. Used to learn which
        ingredient choices each dish has been made with.
        """
        for m in self.menu():
            if m["item"] and m["ingredients"]:
                yield m["item"], m["ingredients"]
        for s in self._all_slots():
            x = (s or {}).get("itemInstanceSave")
            if x and x.get("ingredientsID"):
                yield x["itemID"], list(x["ingredientsID"])
        for _rid, out_item, ins, out_ings in self._recent():
            if out_ings:
                yield out_item, out_ings

    # --- crafting history ------------------------------------------------
    def _recent(self):
        for crafter in self.raw.get("recentRecipesSave") or []:
            for r in crafter.get("recentRecipes") or []:
                ins = [x["itemID"] for x in r.get("ingredientsAdded") or []]
                amt = r.get("ingredientsAddedAmount") or []
                out = r.get("output") or {}
                yield (r["recipeID"], out.get("itemID"), list(zip(ins, amt)),
                       list(out.get("ingredientsID") or []))

    def recent_recipes(self):
        """(recipeID, output itemID, [(input itemID, amount)]) per remembered craft."""
        return [(rid, out, ins) for rid, out, ins, _ in self._recent()]

    def unlocked_recipes(self):
        """Recipe IDs the player has unlocked (altar, shops, ...). Basic recipes
        that need no unlocking (catalogue recipes.unlock = 0) are not listed."""
        return set(self.raw.get("unlockedRecipes") or [])

    # --- reputation ----------------------------------------------------------
    def reputation(self):
        """Reputation at the moment of saving. The save keeps only the current
        value (no per-day history); `learn` records one snapshot per in-game day."""
        r = self.raw
        return {"reputation": r.get("tavernRep"), "progress": r.get("tavernProgress"),
                "arcane_reputation": r.get("arcaneRep"), "arcane_progress": r.get("arcaneProgress")}

    # --- daily stats -----------------------------------------------------
    def daily_stats(self):
        """One dict per in-game day, oldest first, as stored in tavernStats."""
        items = (self.raw.get("tavernStats") or {}).get("_items") or []
        return [{k: v for k, v in s.items() if k != "__class"} for s in items if s]

    # --- staff -------------------------------------------------------------
    def staff(self):
        out = []
        for role, key in (("Bartender", "barworkerSave"), ("Waiter", "waiterSave"),
                          ("Bouncer", "bouncerSave"), ("Housekeeper", "houseKeeperSave")):
            e = self.raw.get(key)
            if e and e.get("name"):
                out.append({"role": role, "name": e["name"], "level": e.get("level"),
                            "working": e.get("working"),
                            "unspent_points": e.get("professionPoints", 0)})
        return out
