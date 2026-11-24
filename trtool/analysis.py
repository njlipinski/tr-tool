"""Diagnostics computed from a save + the database. Pure data, no formatting."""
import collections
import os

# Trend effects as shown on the in-game Trends tab (0.7.6.19). Display only.
TREND_EFFECT = {
    ("food", "popular"): "+20%", ("drink", "popular"): "+20%",
    ("ingredient", "popular"): "+10%",
    ("food", "unpopular"): "-10%", ("drink", "unpopular"): "-10%",
    ("ingredient", "unpopular"): "-5%",
}


def dish_ingredient_index(con):
    """dish -> set(ingredients) and ingredient -> set(dishes), from learned data."""
    by_dish, by_ing = collections.defaultdict(set), collections.defaultdict(set)
    for r in con.execute("SELECT dish_id, ingredient_id FROM dish_ingredients"):
        by_dish[r[0]].add(r[1])
        by_ing[r[1]].add(r[0])
    return by_dish, by_ing


def menu_index(save):
    """item -> list of places on the menu; also the raw menu list."""
    menu = save.menu()
    where = collections.defaultdict(list)
    for m in menu:
        if m["item"]:
            where[m["item"]].append(m["where"])
    return menu, where


MAKE_WITH_TOP = 5


def _chain(cat, chain):
    return " ← ".join(cat.name(i) for i in chain)


def _recipe_info(cat, item):
    """Known recipes for an item: batch size and crafting stations."""
    out = []
    for rid in cat.made_by.get(item, ()):
        r = cat.recipes[rid]
        out.append({"recipe_id": rid, "qty": r["output_qty"],
                    "crafters": [cat.name(c) for c in cat.crafters.get(rid, ())]})
    return out


def makeable_suggestions(cat, t, where, stored, menu):
    """What the player could cook for a trend week, from recipes they know.

    make:      popular food/drink with a known recipe, not on the menu, none stored
    make_with: per popular ingredient, the highest-priced sellable dishes that
               take it, through known recipes only: as an ingredient choice (what
               a save stores in ingredientsID) or as a fixed input (fixed=True).
               Fixed inputs aren't stored on the dish; the user believes the
               trend counts for them too, but that's untested (docs/findings.md)."""
    unpop = set(t["food"]["unpopular"]) | set(t["drink"]["unpopular"])
    pop_dish = set(t["food"]["popular"]) | set(t["drink"]["popular"])
    make = []
    for kind in ("food", "drink"):
        for i in t[kind]["popular"]:
            if where.get(i) or stored.get(i, 0) > 0 or i not in cat.made_by:
                continue
            make.append({"id": i, "name": cat.name(i), "kind": kind, "price": cat.price(i),
                         "recipes": _recipe_info(cat, i)})
    make.sort(key=lambda r: -(r["price"] or 0))

    dishes = [d for d in cat.made_by if cat.serving(d) and d not in unpop]
    make_with = []
    for ing in t["ingredient"]["popular"]:
        def row(d, chain, fixed):
            return {"id": d, "name": cat.name(d), "kind": cat.serving(d), "price": cat.price(d),
                    "chain": _chain(cat, chain), "fixed": fixed, "dish_popular": d in pop_dish,
                    "on_menu": where.get(d, []), "stored": stored.get(d, 0),
                    "recipes": _recipe_info(cat, d)}
        options = {}
        for d in dishes:
            chain = cat.leaf_inputs(d).get(ing)
            if chain:
                options[d] = row(d, chain, False)
        # Dishes that take it only as a fixed input (directly or inside an intermediate).
        for rid, chain in cat.uses(ing).items():
            d = chain[-1]
            if d not in options and cat.serving(d) and d not in unpop:
                options[d] = row(d, list(reversed(chain)), True)
        serving_now = ["%s (%s%s)" % (cat.name(m["item"]), m["where"],
                                      ", fixed" if m["item"] in options and options[m["item"]]["fixed"] else "")
                       for m in menu if m["item"] and (ing in m["ingredients"] or
                                                       (m["item"] in options and options[m["item"]]["fixed"]))]
        ranked = sorted(options.values(), key=lambda r: (-(r["price"] or 0), r["name"]))
        make_with.append({"id": ing, "name": cat.name(ing), "stored": stored.get(ing, 0),
                          "serving_now": serving_now, "options": ranked[:MAKE_WITH_TOP],
                          "option_count": len(ranked)})
    return make, make_with


def trend_week(save, con, names, offset, cat=None):
    """Everything the report says about one trend week (0 = this, 1 = next).
    cat: a catalogue.Catalogue limited to the recipes the player knows, or None."""
    t = save.trends(offset)
    if t is None:
        return None
    stored = save.stored()
    menu, where = menu_index(save)
    by_dish, by_ing = dish_ingredient_index(con)

    def status(i):
        return {"id": i, "name": names(i), "on_menu": where.get(i, []),
                "stored": stored.get(i, 0)}

    lists = {kind: {mood: [status(i) for i in ids] for mood, ids in moods.items()}
             for kind, moods in t.items()}

    pop_ing = set(t["ingredient"]["popular"])
    unpop_ing = set(t["ingredient"]["unpopular"])
    pop_dish = set(t["food"]["popular"]) | set(t["drink"]["popular"])
    unpop_items = set(t["food"]["unpopular"]) | set(t["drink"]["unpopular"])

    actions = {"add": [], "remove": [], "ingredient_hits": [], "cook_with": []}

    # Popular food/drink you have stock of but are not serving.
    for kind in ("food", "drink"):
        for i in t[kind]["popular"]:
            if not where.get(i) and stored.get(i, 0) > 0:
                slot = "bar"
                if kind == "drink":
                    slot = "tap or keg" if names.on_tap(i) else "keg"
                actions["add"].append(dict(status(i), slot=slot))

    # Unpopular food/drink currently on the menu.
    for i in sorted(unpop_items):
        if where.get(i):
            actions["remove"].append(status(i))

    # Menu dishes whose ingredients are trending either way.
    for m in menu:
        if not m["item"]:
            continue
        good = [names(i) for i in m["ingredients"] if i in pop_ing]
        bad = [names(i) for i in m["ingredients"] if i in unpop_ing]
        if good or bad:
            actions["ingredient_hits"].append({
                "where": m["where"], "id": m["item"], "name": names(m["item"]),
                "popular_ingredients": good, "unpopular_ingredients": bad,
                "dish_popular": m["item"] in pop_dish,
                "dish_unpopular": m["item"] in unpop_items})

    # Dishes known (from learned data) to take a trending ingredient.
    for ing in sorted(pop_ing):
        for dish in sorted(by_ing.get(ing, ())):
            if names.category(dish) not in ("Food", "Drinks"):
                continue
            if dish in unpop_items:
                continue
            actions["cook_with"].append({
                "dish_id": dish, "dish": names(dish), "ingredient_id": ing,
                "ingredient": names(ing), "ingredient_stored": stored.get(ing, 0),
                "dish_popular": dish in pop_dish,
                "dish_on_menu": where.get(dish, []),
                "menu_uses_it": any(m["item"] == dish and ing in m["ingredients"]
                                    for m in menu)})
    actions["cook_with"].sort(key=lambda r: (not r["dish_popular"], r["dish"]))

    if cat is not None:
        actions["make"], actions["make_with"] = makeable_suggestions(cat, t, where, stored, menu)
    return {"offset": offset, "lists": lists, "actions": actions, "catalogue": cat is not None}


def reputation_history(save, data_dir):
    """Recorded reputation snapshots (data/reputation.tsv) plus this save, oldest
    first, with the progress gained since the previous snapshot."""
    from .db import read_tsv
    from .learn import REP_FILE
    rows = {int(r["day_number"]): r for r in read_tsv(os.path.join(data_dir, REP_FILE))}
    d = save.date
    cur = {k: "" if v is None else str(v) for k, v in save.reputation().items()}
    cur.update(day_number=str(d["day_number"]), date=save.date_label, time="%02d:%02d" % (d["hour"], d["minute"]))
    if d["day_number"] not in rows or rows[d["day_number"]].get("time", "") <= cur["time"]:
        rows[d["day_number"]] = cur
    out, prev = [], None
    num = lambda v: int(v) if (v or "").lstrip("-").isdigit() else None
    for n in sorted(rows):
        r = rows[n]
        row = {"day_number": n, "date": r.get("date"), "time": r.get("time"),
               "reputation": num(r.get("reputation")), "progress": num(r.get("progress")),
               "gained": None, "level_up": False}
        if prev and row["progress"] is not None and prev["progress"] is not None:
            if row["reputation"] == prev["reputation"]:
                row["gained"] = row["progress"] - prev["progress"]
            else:
                row["level_up"] = True
        out.append(row)
        prev = row
    return out


def daily(save):
    """Daily stats with derived columns, oldest first (only days with customers)."""
    out = []
    for n, s in enumerate(save.daily_stats(), 1):
        if not s.get("customersCount"):
            continue
        staff = sum(s.get(k, 0) for k in ("bartenderCost", "houseKeeperCost", "floorWorkerCost"))
        income = s.get("salesIncome", 0) + s.get("rentRoomIncome", 0)
        out.append(dict(s, day=n, staffCost=staff, income=income, net=income - staff))
    return out


def summarize(days, last=7):
    recent = days[-last:]
    if not recent:
        return {}
    keys = ("customersCount", "satisfiedCustomers", "kickedCustomers", "priceRejectedCustomers",
            "salesIncome", "foodIncome", "drinkIncome", "rentRoomIncome", "staffCost",
            "shopExpenses", "net")
    return {k: sum(d.get(k, 0) for d in recent) / len(recent) for k in keys} | {"days": len(recent)}


def unnamed_ingredients(save, con, names):
    """Ingredient IDs the save uses whose name is missing or not confirmed, with evidence."""
    ev = collections.defaultdict(lambda: collections.defaultdict(set))
    for rid, out, ins in save.recent_recipes():
        for i, _ in ins:
            ev[i]["crafted into"].add(names(out))
    for m in save.menu():
        for i in m["ingredients"]:
            ev[i]["in menu dish"].add("%s (%s)" % (names(m["item"]), m["where"]))
    for off, label in ((0, "this week"), (1, "next week")):
        t = save.trends(off)
        if t:
            for i in t["ingredient"]["popular"]:
                ev[i]["trend"].add("popular " + label)
            for i in t["ingredient"]["unpopular"]:
                ev[i]["trend"].add("unpopular " + label)
    stored = save.stored()
    rows = []
    for i in sorted(ev):
        info = names.get(i)
        conf = info.get("name_confidence")
        if conf in ("wiki", "confirmed"):
            continue
        rows.append({"id": i, "name": info.get("name") or "", "confidence": conf or "",
                     "basis": info.get("name_basis") or "", "stored": stored.get(i, 0),
                     "trend": "; ".join(sorted(ev[i]["trend"])),
                     "crafted_into": "; ".join(sorted(ev[i]["crafted into"])),
                     "in_menu_dishes": "; ".join(sorted(ev[i]["in menu dish"]))})
    return rows
