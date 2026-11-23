# TR Tool

A helper for **Travellers Rest** that reads a save file and writes a tavern
diagnostics report. Built against game version 0.7.6.19 (Early Access).

The save is never modified. Everything is read-only.

Roadmap and working rules (for Claude Code and humans): see `CLAUDE.md`. Next up is a full item/recipe catalogue extracted from the installed game files, with Excel overrides.

## Quick start

Needs Python 3.9+ and no other packages.

```
python -m trtool where            # show the game's save folder on this PC
python -m trtool report           # newest save in that folder -> <save>_report.html
python -m trtool report path\to\SaveFile.save -o report.html
```

On Windows the saves are in
`%USERPROFILE%\AppData\LocalLow\Louqou\TravellersRest\GameSaves`.

## What the report shows

- **Next week and this week's trends** against your bar, taps and kegs:
  trending items you have in stock but aren't serving, unpopular items still on
  the menu, menu dishes hit by ingredient trends, and dishes you've made before
  with a trending ingredient ("cook X with Y").
- **Daily stats & money**: last 7 days vs the 7 before, a 28-day chart, and a
  14-day table (customers, kicked, price-rejected, sales split, rent, wages,
  shop spending).
- **Staff** and **ingredients that still need a confirmed name**.

## Commands

| Command | What it does |
|---|---|
| `report [SAVE]` | Write the HTML report. Also runs `learn` unless `--no-learn`. |
| `learn [SAVE ...]` | Record which ingredients each dish has been made with, and recipe inputs, into `data/`. Safe to repeat. |
| `ingredients [SAVE]` | List ingredient IDs without a confirmed name, with clues (stock, trends, dishes). |
| `build-db` | Rebuild `build/trtool.db` from `data/*.tsv` (happens automatically when the TSVs change). |
| `dump [SAVE] [--field NAME]` | Print the decoded save as JSON, for exploring new fields. |
| `where` | Print the save folder the tool found. |

`SAVE` can be a `.save` file or a folder (the newest `.save` in it is used).
With no `SAVE`, the game's own folder is used.

## Data

The data files in `data/` are the source of truth. The SQLite database is
rebuilt from them, so edit the files, not the database.

| File | Contents | Edited by |
|---|---|---|
| `raw/wiki_items.tsv` | id, name, category from the wiki | `tools/wiki_dump.js` |
| `items_curated.tsv` | Names the wiki lacks, plus overrides; `serving=tap` marks drinks that fit a tap | You |
| `item_sources.tsv` | Where to get an item (shop, crop, forage, fish...) | You |
| `dish_ingredients.tsv` | Dish ↔ ingredient pairs seen in your saves | `learn` |
| `recipe_inputs.tsv` | Recipe inputs seen in crafting history | `learn` |

**Confirming an ingredient name:** hover the item in game (prepared dishes
list their ingredients in green), then edit its row in `items_curated.tsv`
and set `confidence` to `confirmed`. For the confidence levels and how to add
a new table, see `CLAUDE.md`.

**Refreshing wiki names after a game update:** run `tools/wiki_dump.js` in
the browser console on travellersrest.wiki.gg (instructions are at the top
of the file).

## Tests

```
python -m pytest            # unit tests
TRTOOL_TEST_SAVE=path/to/SaveFile.save python -m pytest   # also checks a real save
```
