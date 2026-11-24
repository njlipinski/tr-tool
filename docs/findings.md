# Phase 1 findings: Travellers Rest game files

Game **0.7.6.19**, Unity 2022.3.62f2, Steam install. Everything below was
read from the installed game, read-only. Reproduce the inventory with
`trtool explore`; the deeper reads were ad-hoc scripts (not committed).

**Headline:** everything Phase 2 needs is readable: items, groups, recipes,
crafters, crops, fish, shops, English names. The mismatches with CLAUDE.md
are resolved (see "Mismatches"). Phase 2 status is at the end.

## Install and build

- Root: `E:\SteamLibrary\steamapps\common\Travellers Rest`. The Unity player
  is one level down: `...\Windows\TravellersRest_Data\`. `trtool` accepts the
  root and finds `*_Data` itself.
- **Mono, confirmed:** `Managed\Assembly-CSharp.dll` (18 MB) and
  `Assembly-CSharp-firstpass.dll`; no `GameAssembly.dll`.
- Assets: `globalgamemanagers(.assets)`, `resources.assets` (243 MB),
  `sharedassets0–32.assets`, `level0–32`. No AssetBundles or Addressables.
  `StreamingAssets` only has a Unity Services config.
- **Version:** `VersionNumberManager` in `level1`: `version = "v0.7.6.19.0"`,
  `versionNumber = [0,7,6,19,0]` (same shape as the save's `versionNumber`).
  `PlayerSettings.bundleVersion` is just `"0.1"`, so it's useless.

## Type trees: generated from the DLLs

All 69 asset files have **stripped type trees**. The user approved adding
**`TypeTreeGeneratorAPI`** (pip, prebuilt wheel). UnityPy loads `Managed\*.dll`
through it and then decodes the game classes. Results:

- Every item (1,691) and recipe (654) decodes with no errors.
- One exception: the I2 localization asset. Its generated layout is missing
  8 bytes (two ints, `0` and `1`) just before the term list, so UnityPy fails.
  Parsing it by hand with that 8-byte skip works and consumes the whole object.
  Phase 2 needs a small custom reader for this one asset.
- UnityPy quirk: script names must be resolved **before** attaching the
  generator, or cross-file script pointers fail.

Kept, and now on CLAUDE.md Rule 4's list of agreed dependencies.

## Where the data lives

All game classes are in `Assembly-CSharp`, global namespace.

### Items: `ItemDatabase` (sharedassets1)
- `items` (1,691 pointers), `fish` (68), `food` (724), `nextID`.
- Objects are in `resources.assets` and `sharedassets1.assets`, across 29
  classes that all share the `Item` base: Item 841, Food 542, Seed 93, Fish 68,
  IngredientGroup 48, SproutSeed 19, SpellBook 12, PhaseItem 10, tools,
  animals…
- Base fields: `id`, `translationByID`, `nameId`, `description`,
  `excludedFromTrends`, `excludedFromShops`, `canBeStacked`, `amountStack`,
  `requiredRep` (pointer), `arcaneReputationRequired`, `sorceryLevelRequired`,
  `comfort`, sprites/prefabs…
- Food adds: `price` and `sellPrice` as `{gold, silver, copper}`, `category`,
  `foodType`, `ingredientType` (int enum), `canBeAged`, `containsAlcohol`,
  `recipe` (pointer), `tags`, `modifiers`, `seed`…
- **Names:** if `translationByID = 1` (1,404 items), the English name is I2
  term `Items/item_name_<id>` (description: `Items/item_description_<id>`).
  Otherwise `nameId` is the term key. 1,601 of 1,691 items resolve to
  English. The 90 that don't look like unused or old objects ("[OLD]" tables,
  hairstyles, extra chests).

### Ingredient groups: `IngredientGroup` (48, ids −1…−58)
- Two membership rules, **both needed** (a group can use both):
  1. `possibleItems`: explicit list of `{item, mod}` pairs. Members can be
     other groups (−35 = {−34, −16}; Meat −1 contains Arcane Meat −50).
     **`mod` matters:** "Malt from Barley or Wheat" (−36) lists item 1544
     Malt twice with different mods. So a member is an (item, mod) pair, not
     just an item.
  2. `ingredientsTypes`: list of `ingredientType` values. Every item with that
     type is a member. Meat −1 = type 6 → Wild Turkey 1221, Beef 1245,
     Pork 1246, Chicken Meat 1247, Lamb Meat 1248, Vegetable meat 1249.
- **Cheese −4** = `ingredientsTypes [9]` → 12 items: the 7 cheeses on the
  wiki's Cheese page (Brie 1280, Cheddar 1282, Emmental 1284, Blue 1286,
  Manchego 1288, Feta 1289, Mozzarella 1290) **plus 5 "Unaged" cheeses**
  (1279, 1281, 1283, 1285, 1287). Cream Cheese 1452 has type 0, so it's
  excluded, matching the wiki. **Settled by the user:** unaged cheeses must
  be aged before they can be used as ingredients. The game marks them
  `hasToBeAgedMeal = 1` (they also have `canBeUsedAsModifier = 0` and no
  aged sprite). Mozzarella and Feta are aged as soon as they're made and have
  no unaged form. **Phase 2 rule:** leave items with `hasToBeAgedMeal = 1` out
  of group expansion and `leaf_inputs`. The only other items with the flag
  are Pickled Eggs 1368, Pickles in Vinegar 1378, Marinated Pickles 1379 and
  Kimchi 1382, presumably for the same reason.
- An earlier draft said Cheese and Fruit had no members. That was wrong: it
  only counted `possibleItems`.
- 47 of 48 groups have members. The exception is **"Dishes" −6**, which has
  neither rule and is used only by recipe 345 → Leftovers 1244. Its
  membership ("any dish"?) must be decided in code. **Open.**
- Bread −5 = {1267 Bread, 80 Wheat Bread, 197 Rye Bread, 198 Barley Bread};
  Grain −3 = type 8 = {3016 Corn, 3018 Wheat, 3020 Rice, 3022 Barley, 3024 Rye}.

### Recipes: `RecipeDatabase` (sharedassets1) → `Recipe` (654, resources.assets)
- `id`, `ingredientsNeeded[] {item, amount, mod}`, `output {item, amount}`,
  `fuel`, `time {years, weeks, days, hours, mins}`, `page`, `recipeGroup`,
  `unlock` (int), `reputationRequired` (pointer), `arcaneReputationRequired`,
  `sorceryLevelRequired`, `recipeFragments`, `shopSilverPrice`,
  `excludeFromTrends`, `saveIngredientsAdded`…
- **`replacedRecipe = 1` on 49 recipes**, with `newRecipe` pointing to the
  replacement. **Decision (the user):** keep every recipe; flag replaced
  ones and leave them out of suggestions and other report logic. Recorded
  in CLAUDE.md Phase 2.
- `unlock` values, read against the designer table (below):
  0 = none/default, 1 = Recipe Temple ("Templo Recetas", i.e. the Altar),
  2 = Halloween quest, 3 = Christmas, 4 = "X" (known from start?),
  7 = buying the Cheesery, 8 = shop (Amos/Gero/Kharma/Petra/Woody),
  9 = skill, 10 = main progress, 11 = "Agujeros" (holes/mines), 5/6/12 = blank
  in the table. **These meanings are inferred from the Spanish table, not
  confirmed. The enum names are in the DLL; I'll read them in Phase 2.**
- `reputationRequired` points to an object I haven't decoded yet. The table
  gives the number (Cheeseburger: 10).

### Crafters
- No crafter field on `Recipe`. Chain: crafter item's prefab GameObject has
  `ItemSetup.item` (→ item ID) and `Crafter.recipeList` → `RecipeList`
  (33 objects, nested via `recipeLists`, minus `recipesToIgnore`) → recipes.
- 38 crafter items found (Oven 672, Food Prep Table 1240, Work Bench 668,
  Advanced/Arcane variants…). Advanced variants share the base list (Oven and
  Advanced Oven both have 152 recipes).
- **Crafter subclasses:** the Grinder (667) uses a `Grinder` component (a
  `Crafter` subclass), which a match on the class name `Crafter` misses.
  Phase 2 should find crafters as any component with a `recipeList` field.
  In these two files that's only `Crafter` and `Grinder`.
- **Grinder 667:** Flour 1292 (recipe 333, 35 min), Minced Meat 1276 (334,
  30 min), Breadcrumbs 1277 (335), Paprika 1278 (336), Minced Fish 1453
  (498, 30 min); all make 5. The wiki lists separate Corn, Barley, Rye and
  Wheat Flour recipes; the game files have only the one Flour recipe, so the
  wiki looks out of date.
- **123 of 654 recipes aren't reachable from any crafter** found so far:
  the 49 replaced recipes plus 74 others. Those may be on crafters placed in
  scenes (`level*`), or event/shop recipes. **Open for Phase 2.**

### Other data
- **Crops:** `CropsDatabase` → `Crop` (103): `seed`, `harvestedItems`,
  `daysToGrow`, `reusable`, `daysUntilNewHarvest`, `avaliableSeasons` [sic],
  `bestSeasons`, `amountBestSeason`, `requiresMagicFertilizer`. `Seed` 93,
  `SproutSeed` 20.
- **Fish:** `Fish` items plus `ItemDatabase.fishFile` (method, bait,
  salt/freshwater, mine biome, difficulty, season bitmask, length).
- **Shops:** `ShopDatabase` → `Shop` (27): `shopType`, `shopItems`,
  `recipesShop`, `minItems`/`maxItems`, `updateDays`, `limitedItems`…;
  `MineralsShopDatabase` (levels).
- **Reputation:** `ReputationDatabase` (51 levels: capacity, zones, tiles, repMax).
- **Forage:** `MiscItemHarvest` (51) with `harvestedItems`. Not explored further.

### Designer tables (Spanish, partly stale): don't use as the source
Several databases embed the spreadsheet they were imported from:
`ItemDatabase.itemsFile` (1,571 rows), `RecipeDatabase.recipeFile` (551;
includes `crafterID`, `crafterName`, `unlock` text, `reputation`, `minutes`),
`CropsDatabase.cropsFile` (79), `ShopDatabase.shopItemsLines` (553; prices,
reputation requirements, shop type), `ReputationDatabase.reputationFile`,
`ItemDatabase.fishFile`. They have fewer rows than the live objects, so
they're **behind the live data**. Use them only as cross-checks or to
decode enums; never as the source.

**Language decision (the user):** use English wherever possible. Spanish
(designer table or object label) is only a fallback for the few items with
no English term, and is marked as such.

## Localization: I2 Localization
- One `I2.Loc.LanguageSourceAsset` ("I2Languages") in `resources.assets`.
  9,775 terms × 30 languages; **English is column 0**, Spanish column 1.
- Term prefixes: `Dialogue System/` 4,564, `Items/` 2,678, `Perks/` 266,
  and the rest are UI strings.

## Fact checks (CLAUDE.md)

| Fact | Expected | Found | |
|---|---|---|---|
| Mono build | Assembly-CSharp.dll exists | yes | ✓ |
| 1245 / 148 / 1248 / 3437 | Beef / Lime / Lamb Meat / Sardine | same | ✓ |
| Minced Ingredients | group **−23** | **−34** "Minced Ingredients" = {1276 Minced Meat, 1453 Minced Fish} | ✗ |
| Group −23 | Minced Ingredients | **"Milk"** = {1252 Cow Milk, 1253 Sheep Milk} | ✗ |
| Meat group | Wild Turkey, Beef, Pork, Chicken, Lamb, Vegetable Meat | same (via ingredientType 6), **plus** Arcane Meat group −50 | ✓ (+1) |
| Cheeseburger 1266 | Oven, 50 min, fuel 10, ×20 | recipe 321: Oven 672, 50 min, fuel 10, ×20 | ✓ |
| Cheeseburger inputs | Minced ×2, Bread ×20, Cheese ×2 | −34 ×2, −5 Bread ×20, −4 Cheese ×2 | ✓ |
| Cheeseburger unlock | Altar, rep 10 | unlock 1 = "Templo Recetas"; table rep 10 | ✓ (inferred) |
| Cheeseburger price | 2s 90c – 6s 5c | `sellPrice` 2s 83c, `price` 6s 0c | ≈ (in-game range likely adds modifiers) |
| Minced Meat 1276 | Grinder, 30 min, fuel 0, ×5, Meat ×1 | recipe 334: Grinder 667, 30 min, fuel 0, ×5, Meat −1 ×1 | ✓ |
| Chocolate 1220 | recipe 307, Food Prep Table, 2 h, fuel 10, ×5, Cocoa ×2, Cow Milk ×2 | same (crafter 1240 Food Prep Table) | ✓ |
| Cheese group −4 | wiki: Brie, Cheddar, Emmental, Blue, Manchego, Feta, Mozzarella; not Cream Cheese | type 9: those 7 plus 5 Unaged variants (unusable until aged, `hasToBeAgedMeal`); Cream Cheese excluded | ✓ |
| Save leaf example | 3016 = Wheat | **3016 = Corn** | ✗ (see below) |

## Open guesses in `items_curated.tsv`, settled by the game's English names

| ID | Curated | Game | |
|---|---|---|---|
| 1246 | Pork (likely) | Pork | ✓ |
| 3073 | Shrimp (guess) | **Wild Berries** | ✗ swapped |
| 1376 | Wild Berries (guess) | **Shrimp** | ✗ swapped |
| 218 / 3069 / 256 | one of Watermelon / Mango / Pineapple | Watermelon / Pineapple / Mango | settled |
| 3048 / 3050 | Hops (one kind / another) | Citra Hops / Galaxy Hops | settled |
| 1252 / 1253 | Milk (one kind / another) | Cow Milk / Sheep Milk | settled |
| 244 | Onion (likely) | **Pumpkin** | ✗ |
| 3093 | Pistachio | Pistachio | ✓ |
| 1377 | Seaweed | Seaweed | ✓ |
| 3455 | Sea Urchin | Sea Urchin | ✓ |
| 3016 | Wheat (likely) | **Corn** (Wheat is 3018) | ✗ |
| Tap drinks | 12, 121, 131–133, 1517–1522, 1531, 1546, 371 | all beers/ciders as expected; 1531 Flavored Beer and 371 Cider have `ingredientType` 0, the rest 15 | ✓ |

Not changed in the TSVs. Per the plan, these become overrides only where the
user disagrees with the extracted names.

## Mismatches (resolved)
1. **Minced Ingredients is −34, not −23** (−23 is Milk). CLAUDE.md is corrected.
2. **3016 is Corn, not Wheat** (Wheat is 3018). The CLAUDE.md save example now
   says Corn, reached through Bread −5 → a grain bread → Grain −3.
3. **Shrimp/Wild Berries are swapped** and **244 is Pumpkin, not Onion** in
   `items_curated.tsv`.

## Open questions for Phase 2
- "Dishes" −6: anything sellable as food (the user); only Leftovers (pig
  food) uses it. **Ignored for now** (decision by the user).
- The 74 non-replaced recipes with no crafter found yet: scan `level*` for
  components with a `recipeList` field, and check event/shop recipes.
- Enum names (`ingredientType`, `unlock`, `category`, `foodType`, `shopType`)
  from the DLL, rather than inferring them from the Spanish table.
- `reputationRequired` / `requiredRep` targets: decode those objects.
- Proposed schema changes from these findings: `group_members` needs a `rule`
  column (explicit / by ingredient type) and a `mod` column, or an
  expansion step at extraction;
  `items` needs `must_age` (from `hasToBeAgedMeal`); `recipes` needs `replaced_by`; `crafters` is its own table (crafter item →
  recipe list), with the base and Advanced variants both listed.

## Phase 2: catalogue (`trtool extract` → `build/catalogue.db`)

Takes about 6 s. Counts for 0.7.6.19: 1,691 items (90 with only a Spanish
name, marked `name_lang = 'es'`), 387 group memberships, 654 recipes (49
replaced), 1,878 recipe inputs, 945 crafter–recipe pairs, 96 crops, 68 fish,
27 shops with 707 shop items and 332 shop recipes.

**Schema changes from the CLAUDE.md proposal, and why:**
- `recipes.crafter_id` became a separate **`crafter_recipes`** table:
  stations share recipe lists (Oven, Advanced Oven and a third oven all make
  Cheeseburger), so it's many-to-many.
- `group_members` gained **`rule`** (explicit / type), **`ingredient_type`**
  and **`mod_id`**: groups match by explicit (item, mod) pairs *and* by
  ingredient type.
- `items` gained **`must_age`** (unusable until aged), `class`, `name_lang`,
  raw enum ints (`category`, `food_type`, `ingredient_type`) and
  `required_reputation`. Enum names aren't known, so they stay as numbers.
- `recipes` gained **`replaced` / `replaced_by`** (kept but ignored by the
  helpers), `save_ingredients`, reputation fields, `recipe_fragments` and
  `shop_silver_price`.
- `sources` is a **view** over craft (current recipes), crop, fish and shop
  rows, with detail tables: `crops` + `crop_harvests`, `fish`, `shops` +
  `shop_items` + `shop_recipes`. Seasons use 0/1/2 = no / yes / best (mask
  spring 1, summer 2, autumn 4, winter 8, checked against the designer table).
  **Forage and events aren't covered yet.**
- `meta`: game_version, unity_version, extracted_at, schema_version, game_dir.

**How saves flatten ingredients** (`trtool/catalogue.py`, `leaf_inputs`):
`ingredientsID` holds the item chosen for each *group* slot, followed down
through intermediates. Fixed inputs aren't stored. Tacos (inputs Minced,
Tortilla, Onion, Lemon - Lime, Lettuce) stores `[Beef, Lard, Lime]`: Onion
and Lettuce are fixed, and Lard is a choice inside Tortilla. Sometimes a chosen
intermediate is replaced by its own choices (Minced Meat → Lamb Meat), and
sometimes it isn't (Brandy stores the Wine itself). The files don't show
why, so `leaf_inputs` returns both: a superset. It explains **all 181**
dish/ingredient pairs learned from the user's saves (179 with the stricter
rule; the 2 misses were Brandy).

**Not done yet:** forage sources (`MiscItemHarvest`), crafters placed only in
scenes (74 non-replaced recipes have no crafter yet), enum names, and the
shop reputation requirements (only in the designer table so far).

## Other notes
- README says CLAUDE.md documents the name confidence levels and how to add
  a table; it no longer does (they're in `trtool/schema.sql` and the
  `trtool/db.py` docstring).
