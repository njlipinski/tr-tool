"""Build build/extracted.db from the installed game. Read-only toward the game.
(trtool/overrides.py then applies the user's overrides to make build/catalogue.db.)

Sources (see docs/findings.md):
  ItemDatabase.items/food/fish -> items, fish;  IngredientGroup -> group_members
  RecipeDatabase.recipes -> recipes, recipe_inputs
  components with a `recipeList` field (Crafter, Grinder) + ItemSetup -> crafter_recipes
  CropsDatabase.Crops -> crops, crop_harvests;  ShopDatabase.shops -> shops, shop_items, shop_recipes
  I2 LanguageSourceAsset -> English names
"""
import datetime
import os
import sqlite3
import struct

from . import game_version, locate_data_dir
from .i2 import Localization, read_language_source
from .unity import Game

SCHEMA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "catalogue.sql")
SCHEMA_VERSION = "2"
FILES = ("sharedassets1.assets", "resources.assets")
DAYS_PER_YEAR = 4 * 28          # 4 seasons of 4 weeks of 7 days


def _copper(money):
    if not money:
        return None
    return money.get("gold", 0) * 10000 + money.get("silver", 0) * 100 + money.get("copper", 0)


def _minutes(t):
    days = t.get("years", 0) * DAYS_PER_YEAR + t.get("weeks", 0) * 7 + t.get("days", 0)
    return days * 24 * 60 + t.get("hours", 0) * 60 + t.get("mins", 0)


def _f32(v):
    """A Unity float (32-bit) as the shortest decimal that is the same float32:
    0.30000001192092896 -> 0.3. The stored value is unchanged, only its spelling."""
    if not isinstance(v, float):
        return v
    target = struct.pack("<f", v)
    for p in range(1, 10):
        s = float("%.*g" % (p, v))
        if struct.pack("<f", s) == target:
            return s
    return v


def _season(mask, best, bit):
    return 2 if best & bit else 1 if mask & bit else 0


class Extractor:
    def __init__(self, data_dir, log=print):
        self.data_dir = data_dir
        self.log = log
        log("Loading %s ..." % ", ".join(FILES))
        self.g = Game(data_dir, FILES)
        self.ids = {}           # (file, path_id) -> item id
        self.recipe_ids = {}    # (file, path_id) -> recipe id

    def single(self, cls):
        objs = self.g.by_class(cls)
        if len(objs) != 1:
            raise RuntimeError("Expected one %s, found %d" % (cls, len(objs)))
        return objs[0]

    def item_id(self, owner, pptr):
        k = self.g.key(owner["__file"], pptr)
        return self.ids.get(k) if k else None

    def rep_number(self, owner, pptr):
        r = self.g.deref(owner, pptr)
        return r.get("repNumber") if r else None

    # --- localization -------------------------------------------------------
    def load_names(self):
        lsa = [k for k, c in self.g.classes.items() if c == "LanguageSourceAsset"]
        if len(lsa) != 1:
            raise RuntimeError("Expected one I2 LanguageSourceAsset, found %d" % len(lsa))
        languages, terms = read_language_source(self.g.raw(lsa[0]))
        self.en = Localization(languages, terms, "en")
        self.log("Localization: %d terms, %d languages" % (len(terms), len(languages)))

    def english(self, obj, field="name"):
        if obj.get("translationByID"):
            return self.en.get("Items/item_%s_%s" % (field, obj["id"]))
        key = obj.get("nameId") if field == "name" else obj.get("description")
        return self.en.get(key) if key else None

    # --- tables -------------------------------------------------------------
    def items(self):
        db = self.single("ItemDatabase")
        spanish = {r["ID"]: r["name"] for r in db.get("itemsFile") or []}
        objs = {}
        for field in ("items", "food", "fish"):
            for p in db[field]:
                k = self.g.key(db["__file"], p)
                if k and k not in objs:
                    o = self.g.read(k)
                    if o is not None:
                        objs[k] = o
        for k, o in objs.items():
            self.ids[k] = o["id"]
        rows, fish = [], []
        for o in objs.values():
            name, lang = self.english(o), "en"
            if not name:
                name, lang = spanish.get(o["id"]), "es"
                if not name and " - " in (o.get("m_Name") or ""):
                    name = o["m_Name"].split(" - ", 1)[1]
                lang = lang if name else None
            rows.append({
                "id": o["id"], "name": name, "name_lang": lang,
                "kind": "group" if o["__class"] == "IngredientGroup" else "item",
                "class": o["__class"], "category": o.get("category"),
                "food_type": o.get("foodType"), "ingredient_type": o.get("ingredientType"),
                "price_copper": _copper(o.get("price")), "sell_price_copper": _copper(o.get("sellPrice")),
                "stack_size": o.get("amountStack") if o.get("canBeStacked") else 1,
                "can_be_sold": o.get("canBeSold"), "can_be_aged": o.get("canBeAged"),
                "must_age": o.get("hasToBeAgedMeal"), "contains_alcohol": o.get("containsAlcohol"),
                "excluded_from_trends": o.get("excludedFromTrends"),
                "excluded_from_shops": o.get("excludedFromShops"),
                "required_reputation": self.rep_number(o, o.get("requiredRep")),
                "description": self.english(o, "description"),
            })
            if o["__class"] == "Fish":
                ln = o.get("lenght") or {}
                fish.append({"item_id": o["id"], "fishing_method": o.get("fishingMethod"),
                             "bait_type": o.get("baitType"), "water_type": o.get("waterType"),
                             "mine_biome": o.get("mineBiome"), "difficulty": o.get("difficulty"),
                             "season_mask": o.get("season"), "min_length": ln.get("x"),
                             "max_length": ln.get("y")})
        self.item_objs = list(objs.values())
        return rows, fish

    def group_members(self):
        by_type = {}
        for o in self.item_objs:
            if o["__class"] != "IngredientGroup" and o.get("ingredientType"):
                by_type.setdefault(o["ingredientType"], []).append(o["id"])
        rows = []
        for g in self.item_objs:
            if g["__class"] != "IngredientGroup":
                continue
            for m in g.get("possibleItems") or []:
                mid = self.item_id(g, m["item"])
                if mid is not None:
                    rows.append({"group_id": g["id"], "member_id": mid, "mod_id": self.item_id(g, m.get("mod")),
                                 "rule": "explicit", "ingredient_type": None})
            for t in g.get("ingredientsTypes") or []:
                for mid in sorted(by_type.get(t, ())):
                    rows.append({"group_id": g["id"], "member_id": mid, "mod_id": None,
                                 "rule": "type", "ingredient_type": t})
        return rows

    def recipes(self):
        db = self.single("RecipeDatabase")
        objs = [self.g.deref(db, p) for p in db["recipes"]]
        objs = [o for o in objs if o]
        for o in objs:
            self.recipe_ids[(o["__file"], o["__path_id"])] = o["id"]
        rows, inputs = [], []
        for r in objs:
            new = self.g.key(r["__file"], r.get("newRecipe"))
            rows.append({
                "recipe_id": r["id"], "output_id": self.item_id(r, r["output"]["item"]),
                "output_qty": r["output"]["amount"], "minutes": _minutes(r["time"]), "fuel": r["fuel"],
                "page": r.get("page"), "recipe_group": r.get("recipeGroup"), "unlock": r.get("unlock"),
                "reputation": self.rep_number(r, r.get("reputationRequired")),
                "arcane_reputation": r.get("arcaneReputationRequired"),
                "sorcery_level": r.get("sorceryLevelRequired"), "recipe_fragments": r.get("recipeFragments"),
                "shop_silver_price": _f32(r.get("shopSilverPrice")), "exclude_from_trends": r.get("excludeFromTrends"),
                "save_ingredients": r.get("saveIngredientsAdded"),
                "replaced": 1 if r.get("replacedRecipe") else 0,
                "replaced_by": self.recipe_ids.get(new) if new else None,
            })
            for slot, x in enumerate(r["ingredientsNeeded"]):
                inputs.append({"recipe_id": r["id"], "slot": slot, "input_id": self.item_id(r, x["item"]),
                               "mod_id": self.item_id(r, x.get("mod")), "qty": x["amount"]})
        self.recipe_objs = objs
        return rows, inputs

    def _list_recipes(self, key, seen):
        if not key or key in seen:
            return set()
        seen.add(key)
        rl = self.g.read(key)
        if rl is None:
            return set()
        out = {self.recipe_ids[k] for k in (self.g.key(rl["__file"], p) for p in rl.get("recipes") or [])
               if k in self.recipe_ids}
        for p in rl.get("recipeLists") or []:
            out |= self._list_recipes(self.g.key(rl["__file"], p), seen)
        ignore = {self.recipe_ids[k] for k in (self.g.key(rl["__file"], p) for p in rl.get("recipesToIgnore") or [])
                  if k in self.recipe_ids}
        return out - ignore

    def crafter_recipes(self):
        setups = {}
        for s in self.g.by_class("ItemSetup"):
            setups[(s["__file"], s["m_GameObject"]["m_PathID"])] = s
        classes = self.g.classes_with_field("recipeList")
        self.log("Crafter classes: %s" % ", ".join(sorted(classes)))
        pairs = set()
        for c in self.g.by_class(*classes):
            s = setups.get((c["__file"], c["m_GameObject"]["m_PathID"]))
            crafter = self.item_id(s, s["item"]) if s else None
            if crafter is None:
                continue
            for rid in self._list_recipes(self.g.key(c["__file"], c.get("recipeList")), set()):
                pairs.add((crafter, rid))
        return [{"crafter_id": a, "recipe_id": b} for a, b in sorted(pairs)]

    def crops(self):
        db = self.single("CropsDatabase")
        crops, harvests = [], []
        for p in db["Crops"]:
            c = self.g.deref(db, p)
            if not c:
                continue
            mask, best = c.get("avaliableSeasons") or 0, c.get("bestSeasons") or 0
            crops.append({
                "crop_id": c["id"], "label": c.get("m_Name"), "seed_id": self.item_id(c, c.get("seed")),
                "days_to_grow": c.get("daysToGrow"),
                "regrow_days": c.get("daysUntilNewHarvest") if c.get("reusable") else None,
                "spring": _season(mask, best, 1), "summer": _season(mask, best, 2),
                "autumn": _season(mask, best, 4), "winter": _season(mask, best, 8),
                "best_season_amount": c.get("amountBestSeason"),
                "needs_magic_fertilizer": c.get("requiresMagicFertilizer"),
            })
            for h in c.get("harvestedItems") or []:
                iid = self.item_id(c, h["item"])
                if iid is not None:
                    harvests.append({"crop_id": c["id"], "item_id": iid, "qty": h.get("amount")})
        return crops, harvests

    def shops(self):
        db = self.single("ShopDatabase")
        shops, items, recipes = [], [], []
        for p in db["shops"]:
            s = self.g.deref(db, p)
            if not s:
                continue
            label = s.get("m_Name") or ""
            shops.append({"shop_id": s["id"], "label": label.split("-", 1)[1].strip() if "-" in label else label,
                          "shop_type": s.get("shopType"),
                          "update_days": ",".join(str(d) for d in s.get("updateDays") or []) or None})
            for x in s.get("shopItems") or []:
                iid = self.item_id(s, x["item"])
                if iid is not None:
                    items.append({"shop_id": s["id"], "item_id": iid, "always_appear": x.get("alwaysAppear"),
                                  "unlimited": x.get("unlimited"), "min_qty": x.get("min"),
                                  "max_qty": x.get("max"), "weight": _f32(x.get("weight"))})
            for rp in s.get("recipesList") or []:
                rid = self.recipe_ids.get(self.g.key(s["__file"], rp))
                if rid is not None:
                    recipes.append({"shop_id": s["id"], "recipe_id": rid})
        return shops, items, recipes


def _insert(con, table, rows):
    if not rows:
        return
    cols = list(rows[0])
    for r in rows:
        bad = [c for c in cols if isinstance(r[c], (list, dict))]
        if bad:
            raise TypeError("%s.%s is not a scalar: %r" % (table, bad[0], r[bad[0]]))
    con.executemany("INSERT INTO %s (%s) VALUES (%s)" % (table, ",".join(cols), ",".join("?" * len(cols))),
                    [tuple(r[c] for c in cols) for r in rows])


def extract(game_dir, out_path, log=print):
    """Write a fresh catalogue database. Returns {table: row count}."""
    data_dir = locate_data_dir(game_dir)
    x = Extractor(data_dir, log)
    x.load_names()
    tables = {}
    tables["items"], tables["fish"] = x.items()
    tables["group_members"] = x.group_members()
    tables["recipes"], tables["recipe_inputs"] = x.recipes()
    tables["crafter_recipes"] = x.crafter_recipes()
    tables["crops"], tables["crop_harvests"] = x.crops()
    tables["shops"], tables["shop_items"], tables["shop_recipes"] = x.shops()
    version = game_version(data_dir, x.g.gen)

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    tmp = out_path + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    con = sqlite3.connect(tmp)
    with open(SCHEMA, encoding="utf-8") as f:
        con.executescript(f.read())
    for t, rows in tables.items():
        _insert(con, t, rows)
    meta = {"game_version": version, "unity_version": next(iter(x.g.files.values())).unity_version,
            "extracted_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "schema_version": SCHEMA_VERSION, "game_dir": game_dir}
    con.executemany("INSERT INTO meta VALUES (?, ?)", meta.items())
    con.commit()
    con.close()
    os.replace(tmp, out_path)       # replace wholesale, only once everything succeeded
    return {t: len(rows) for t, rows in tables.items()} | {"game_version": version}
