"""Merge what a save reveals into the learned TSVs in data/.

- dish_ingredients.tsv: every (dish, ingredient) pair seen in a prepared
  item, i.e. the ingredient choices that dish can be cooked with.
- recipe_inputs.tsv: inputs of every remembered craft, keyed by recipe ID.
- reputation.tsv: reputation snapshot per in-game day (the save only holds the
  current value, so this history exists only for days a save was learned).

seen_count goes up once per distinct in-game date, so learning the same save
twice changes nothing.
"""
import os

from .db import DATA, read_tsv, write_tsv

DISH_FIELDS = ["dish_id", "ingredient_id", "seen_count", "first_seen", "last_seen"]
RECIPE_FIELDS = ["recipe_id", "output_id", "ingredient_id", "amount", "first_seen", "last_seen"]
REP_FIELDS = ["day_number", "date", "time", "reputation", "progress", "arcane_reputation", "arcane_progress"]
REP_FILE = "reputation.tsv"


def learn_reputation(save, data_dir=DATA):
    """Record the save's reputation under its in-game day; a later time that day replaces it."""
    d = save.date
    snap = {k: "" if v is None else str(v) for k, v in save.reputation().items()}
    row = dict(snap, day_number=str(d["day_number"]), date=save.date_label,
               time="%02d:%02d" % (d["hour"], d["minute"]))
    path = os.path.join(data_dir, REP_FILE)
    rows = {r["day_number"]: r for r in read_tsv(path)}
    old = rows.get(row["day_number"])
    if old and old.get("time", "") > row["time"]:
        return False
    rows[row["day_number"]] = row
    write_tsv(path, REP_FIELDS, sorted(rows.values(), key=lambda r: int(r["day_number"])))
    return old != row


def _merge(path, fields, keyf, observed, when):
    rows = {keyf(r): r for r in read_tsv(path)}
    added = 0
    for key, base in observed.items():
        r = rows.get(key)
        if r is None:
            r = dict(base, first_seen=when, last_seen=when)
            if "seen_count" in fields:
                r["seen_count"] = "1"
            rows[key] = r
            added += 1
        elif r.get("last_seen") != when:
            r["last_seen"] = when
            if "seen_count" in fields:
                r["seen_count"] = str(int(r.get("seen_count") or 0) + 1)
    ordered = sorted(rows.values(), key=lambda r: tuple(int(r[f]) for f in fields[:3]
                                                        if (r.get(f) or "").isdigit()))
    write_tsv(path, fields, ordered)
    return added


def learn(save, data_dir=DATA):
    when = save.date_label

    dishes = {}
    for dish, ings in save.cooked_instances():
        for i in ings:
            dishes[(str(dish), str(i))] = {"dish_id": str(dish), "ingredient_id": str(i)}

    recipes = {}
    for rid, out, ins in save.recent_recipes():
        for i, amt in ins:
            key = (str(rid), str(i), str(amt))
            recipes[key] = {"recipe_id": str(rid), "output_id": str(out),
                            "ingredient_id": str(i), "amount": str(amt)}

    new_d = _merge(os.path.join(data_dir, "dish_ingredients.tsv"), DISH_FIELDS,
                   lambda r: (r["dish_id"], r["ingredient_id"]), dishes, when)
    new_r = _merge(os.path.join(data_dir, "recipe_inputs.tsv"), RECIPE_FIELDS,
                   lambda r: (r["recipe_id"], r["ingredient_id"], r["amount"]), recipes, when)
    rep = learn_reputation(save, data_dir)
    return {"dish_pairs_seen": len(dishes), "dish_pairs_new": new_d,
            "recipe_inputs_seen": len(recipes), "recipe_inputs_new": new_r,
            "reputation_recorded": rep}
