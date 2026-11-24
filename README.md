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

In this order:

- **This week's trends** against your bar, taps and kegs:
  trending items you have in stock but aren't serving, unpopular items still on
  the menu, menu dishes hit by ingredient trends, dishes you've made before
  with a trending ingredient ("cook X with Y"), and, from every recipe you
  know (needs `trtool extract`): trending dishes you could make, and for each
  trending ingredient the highest-priced dishes you could make with it.
- **Daily stats & money**: last 7 days vs the 7 before, a 28-day chart, a
  14-day table (customers, kicked, price-rejected, sales split, rent, wages,
  shop spending), and **reputation** (level and progress per in-game day; the
  save only holds today's value, so the history builds up as you run reports).
- **Next week's trends**, same as this week.
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
| `config [show\|get\|set] [KEY] [VALUE]` | Local settings in `trtool.ini` (gitignored), e.g. `config set game_dir "E:\SteamLibrary\steamapps\common\Travellers Rest"`. `TRTOOL_GAME_DIR` overrides it. |
| `extract [--game-dir PATH]` | Read the game files (items, groups, recipes, crafters, crops, fish, shops; English names) into `build/extracted.db`, then build `build/catalogue.db` with your overrides applied. Re-run after each game update; it lists overrides the update made stale. Needs `pip install UnityPy TypeTreeGeneratorAPI`. |
| `export-xlsx [-o FILE]` | Write the catalogue to Excel (default `build/catalogue.xlsx`), one sheet per table, names next to IDs. Needs `pip install openpyxl`. |
| `import-xlsx FILE [--dry-run]` | Save the workbook's differences from the game data as overrides in `data/overrides/`, then rebuild the catalogue. Needs `pip install openpyxl`. |
| `explore [--game-dir PATH]` | Inventory the game's asset files (object types and script classes) into `build/explore/`. Needs `pip install UnityPy TypeTreeGeneratorAPI`. |

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
| `reputation.tsv` | Reputation level and progress, one row per in-game day a save was learned | `learn` |

**Fixing a catalogue value** (anything `extract` got wrong or missed):
`trtool export-xlsx`, edit the cells (or add/delete rows) and fill in `note`,
then `trtool import-xlsx build/catalogue.xlsx`. Only the differences from the
game data are saved, one line per cell, in `data/overrides/<table>.tsv`
(committed). Each line keeps the value it replaced. If a game update changes
that value, the override is listed as stale and not applied until you keep
or drop it in the workbook's "Stale overrides" sheet. Workbooks are
gitignored because they contain game data.

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
