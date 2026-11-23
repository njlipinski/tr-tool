"""Render the diagnostics as one self-contained HTML page."""
import datetime
import html

from . import analysis


def money(copper):
    """Copper -> 'Xg Ys Zc' (100 copper = 1 silver, 100 silver = 1 gold)."""
    if copper is None:
        return "?"
    c = int(round(copper))
    sign = "-" if c < 0 else ""
    c = abs(c)
    g, rest = divmod(c, 10000)
    s, c = divmod(rest, 100)
    parts = []
    if g: parts.append("%dg" % g)
    if s or g: parts.append("%ds" % s)
    parts.append("%dc" % c)
    return sign + " ".join(parts)


e = lambda x: html.escape(str(x))


def table(headers, rows, cls=""):
    out = ['<table class="%s"><thead><tr>' % cls]
    out += ["<th>%s</th>" % e(h) for h in headers]
    out.append("</tr></thead><tbody>")
    if not rows:
        out.append('<tr><td colspan="%d" class="muted">none</td></tr>' % len(headers))
    for r in rows:
        out.append("<tr>" + "".join("<td>%s</td>" % c for c in r) + "</tr>")
    out.append("</tbody></table>")
    return "".join(out)


def line_chart(series, labels, width=760, height=220):
    """series: [(name, color, [values])] -> inline SVG."""
    vals = [v for _, _, vs in series for v in vs]
    if not vals:
        return ""
    lo, hi = min(0, min(vals)), max(vals) or 1
    pad_l, pad_b, pad_t = 64, 24, 10
    w, h = width - pad_l - 10, height - pad_b - pad_t
    n = max(len(labels) - 1, 1)
    X = lambda i: pad_l + w * i / n
    Y = lambda v: pad_t + h * (1 - (v - lo) / ((hi - lo) or 1))
    out = ['<svg viewBox="0 0 %d %d" class="chart">' % (width, height)]
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        out.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" class="grid"/>' % (pad_l, width - 10, Y(v), Y(v)))
        out.append('<text x="%d" y="%.1f" class="axis" text-anchor="end">%s</text>' % (pad_l - 6, Y(v) + 4, e(money(v))))
    step = max(1, len(labels) // 10)
    for i in range(0, len(labels), step):
        out.append('<text x="%.1f" y="%d" class="axis" text-anchor="middle">%s</text>' % (X(i), height - 6, e(labels[i])))
    for name, color, vs in series:
        pts = " ".join("%.1f,%.1f" % (X(i), Y(v)) for i, v in enumerate(vs))
        out.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="2"><title>%s</title></polyline>' % (pts, color, e(name)))
    out.append("</svg>")
    legend = " ".join('<span class="key"><i style="background:%s"></i>%s</span>' % (c, e(n)) for n, c, _ in series)
    return '<div class="legend">%s</div>%s' % (legend, "".join(out))


def _places(p):
    return e(", ".join(p)) if p else '<span class="muted">—</span>'


def trend_section(week, title):
    if week is None:
        return "<section><h2>%s</h2><p class='muted'>No trend data.</p></section>" % e(title)
    a, L = week["actions"], week["lists"]
    out = ["<section><h2>%s</h2>" % e(title)]

    out.append("<h3>Serve these (trending, in stock, not on the menu)</h3>")
    out.append(table(["Item", "Stored", "Goes on"],
                     [[e(r["name"]), r["stored"], e(r["slot"])] for r in a["add"]]))

    out.append("<h3>Take these off (unpopular, on the menu)</h3>")
    out.append(table(["Item", "Where"], [[e(r["name"]), _places(r["on_menu"])] for r in a["remove"]]))

    out.append("<h3>Menu dishes affected by ingredient trends</h3>")
    out.append(table(["Where", "Dish", "Trending ingredient", "Unpopular ingredient", "Dish itself"],
                     [[e(r["where"]), e(r["name"]), e(", ".join(r["popular_ingredients"])),
                       e(", ".join(r["unpopular_ingredients"])),
                       "popular" if r["dish_popular"] else ("unpopular" if r["dish_unpopular"] else "")]
                      for r in a["ingredient_hits"]]))

    out.append("<h3>Cook with a trending ingredient</h3>"
               "<p class='muted'>Dishes you have made with this ingredient before (learned from your saves). "
               "Popular dishes first: they get both bonuses.</p>")
    out.append(table(["Dish", "With", "Ingredient stored", "Dish trending", "Already on menu that way"],
                     [[e(r["dish"]), e(r["ingredient"]), r["ingredient_stored"],
                       "yes" if r["dish_popular"] else "", "yes" if r["menu_uses_it"] else ""]
                      for r in a["cook_with"]]))

    out.append("<h3>Full trend lists</h3>")
    rows = []
    for kind in ("food", "drink", "ingredient"):
        for mood in ("popular", "unpopular"):
            for r in L[kind][mood]:
                rows.append([e(kind), "%s %s" % (e(mood), e(analysis.TREND_EFFECT[(kind, mood)])),
                             e(r["name"]), _places(r["on_menu"]), r["stored"]])
    out.append(table(["Type", "Trend", "Item", "On menu", "Stored"], rows, "compact"))
    out.append("</section>")
    return "".join(out)


def stats_section(days):
    out = ["<section><h2>Daily stats &amp; money</h2>"]
    if not days:
        return out[0] + "<p class='muted'>No daily stats yet.</p></section>"
    last, prev = analysis.summarize(days, 7), analysis.summarize(days[:-7], 7)

    def row(label, key, fmt=lambda v: "%.0f" % v):
        a = last.get(key, 0)
        b = prev.get(key) if prev else None
        delta = "" if b is None else ("%+.0f%%" % (100 * (a - b) / b) if b else "")
        return [e(label), fmt(a), fmt(b) if b is not None else "", delta]

    out.append(table(["Per day", "Last %d days" % last["days"], "7 days before", "Change"], [
        row("Customers", "customersCount"),
        row("Satisfied", "satisfiedCustomers"),
        row("Kicked out", "kickedCustomers"),
        row("Rejected for price", "priceRejectedCustomers"),
        row("Sales", "salesIncome", money),
        row("  food", "foodIncome", money),
        row("  drink", "drinkIncome", money),
        row("Room rent", "rentRoomIncome", money),
        row("Staff wages", "staffCost", money),
        row("Shop spending", "shopExpenses", money),
        row("Sales + rent − wages", "net", money),
    ]))
    out.append("<p class='muted'>Food/drink split and shop spending are only recorded from about "
               "the Rum and Runes update (0.7.6) on; earlier days show 0.</p>")

    recent = days[-28:]
    labels = ["d%d" % d["day"] for d in recent]
    out.append("<h3>Last %d days</h3>" % len(recent))
    out.append(line_chart([("Sales", "#2f6fbd", [d["salesIncome"] for d in recent]),
                           ("Staff wages", "#c0504d", [d["staffCost"] for d in recent]),
                           ("Sales + rent − wages", "#4a9b5f", [d["net"] for d in recent])], labels))
    out.append(table(["Day", "Customers", "Kicked", "Price-rejected", "Sales", "Food", "Drink",
                      "Rent", "Wages", "Shop"],
                     [[d["day"], d["customersCount"], d["kickedCustomers"], d.get("priceRejectedCustomers", 0),
                       money(d["salesIncome"]), money(d.get("foodIncome", 0)), money(d.get("drinkIncome", 0)),
                       money(d.get("rentRoomIncome", 0)), money(d["staffCost"]), money(d.get("shopExpenses", 0))]
                      for d in reversed(days[-14:])], "compact"))
    out.append("</section>")
    return "".join(out)


CSS = """
body{font:14px/1.45 system-ui,sans-serif;margin:0;background:#faf7f2;color:#2b2520}
main{max-width:980px;margin:0 auto;padding:24px}
h1{margin:0 0 4px;font-size:24px} h2{margin:32px 0 8px;border-bottom:2px solid #d8cbb8;padding-bottom:4px}
h3{margin:18px 0 6px;font-size:15px}
.meta{display:flex;flex-wrap:wrap;gap:8px 24px;margin:8px 0 0}
.meta b{display:block;font-size:18px}
table{border-collapse:collapse;width:100%;margin:4px 0 8px;background:#fff}
th,td{border-bottom:1px solid #eee4d6;padding:5px 8px;text-align:left;vertical-align:top}
th{background:#f1e9dd;font-weight:600} table.compact td{padding:3px 8px}
td:nth-child(n+2){font-variant-numeric:tabular-nums}
.muted{color:#8a7d6e}.chart{width:100%;height:auto;background:#fff}
.chart .grid{stroke:#eee4d6}.chart .axis{font-size:10px;fill:#8a7d6e}
.legend{margin:4px 0}.key{margin-right:14px}.key i{display:inline-block;width:10px;height:10px;margin-right:4px;border-radius:2px}
footer{margin:32px 0 0;color:#8a7d6e;font-size:12px}
"""


def render(save, con, names):
    s, d = save.summary, save.date
    this_w = analysis.trend_week(save, con, names, 0)
    next_w = analysis.trend_week(save, con, names, 1)
    days = analysis.daily(save)
    unnamed = analysis.unnamed_ingredients(save, con, names)
    next_week_no = d["week"] % 4 + 1  # assumes 4-week seasons
    when = "Year %d, %s, Week %d, %s %d" % (d["year"], d["season"], d["week"], d["weekday"], d["day_of_month"])

    meta = [("Date", when), ("Reputation", "%s (progress %s)" % (s["reputation"], s["reputation_progress"])),
            ("Money", money(s["money_copper"])), ("Game version", s["game_version"])]
    parts = ["<!DOCTYPE html><html><head><meta charset='utf-8'>",
             "<title>%s — tavern report</title><style>%s</style></head><body><main>" % (e(s["tavern"] or "Tavern"), CSS),
             "<h1>%s</h1>" % e(s["tavern"] or "Tavern"),
             "<div class='meta'>%s</div>" % "".join("<div><span class='muted'>%s</span><b>%s</b></div>" % (e(k), e(v)) for k, v in meta)]

    if d["weekday"] == "Sun":
        parts.append("<p><b>It's Sunday:</b> next week's trends start tomorrow, so plan the menu with them.</p>")
    parts.append(trend_section(next_w, "Next week (Week %d)" % next_week_no))
    parts.append(trend_section(this_w, "This week (Week %d)" % d["week"]))
    parts.append(stats_section(days))

    staff = save.staff()
    if staff:
        parts.append("<section><h2>Staff</h2>")
        parts.append(table(["Role", "Name", "Level", "Working", "Unspent points"],
                           [[e(x["role"]), e(x["name"]), x["level"], "yes" if x["working"] else "no",
                             x["unspent_points"]] for x in staff]))
        parts.append("</section>")

    if unnamed:
        parts.append("<section><h2>Unconfirmed ingredient names</h2><p class='muted'>%d ingredient IDs in this save "
                     "have no confirmed name. Names ending in ? are guesses. Run <code>trtool ingredients SAVE</code> "
                     "for the evidence, confirm in game, and add them to <code>data/items_curated.tsv</code>.</p>"
                     % len(unnamed))
        parts.append(table(["ID", "Name so far", "Confidence", "Stored", "Trend", "In menu dishes"],
                           [[r["id"], e(r["name"]), e(r["confidence"]), r["stored"], e(r["trend"]),
                             e(r["in_menu_dishes"])] for r in unnamed], "compact"))
        parts.append("</section>")

    parts.append("<footer>Generated %s from %s. Trend effects as shown in game 0.7.6.19.</footer>"
                 % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), e(save.path)))
    parts.append("</main></body></html>")
    return "".join(parts)
