-- Game catalogue, written by `trtool extract` from the installed game files.
-- Disposable: regenerate after each game update. Never edit by hand
-- (manual fixes will go through overrides in Phase 3).
-- Integer enum columns (category, food_type, ingredient_type, unlock, ...) hold
-- the game's raw values; their names aren't known yet.

CREATE TABLE meta (
    key   TEXT PRIMARY KEY,         -- game_version, unity_version, extracted_at, schema_version, game_dir
    value TEXT
);

-- Every item the game's ItemDatabase lists, ingredient groups included (negative ids).
CREATE TABLE items (
    id                  INTEGER PRIMARY KEY,
    name                TEXT,       -- English when available
    name_lang           TEXT,       -- 'en', or 'es' when only a Spanish name exists
    kind                TEXT NOT NULL,  -- 'item' | 'group'
    class               TEXT NOT NULL,  -- game class: Item, Food, Fish, Seed, IngredientGroup, ...
    category            INTEGER,
    food_type           INTEGER,
    ingredient_type     INTEGER,    -- groups can match items by this (group_members.rule = 'type')
    price_copper        INTEGER,    -- Food.price
    sell_price_copper   INTEGER,    -- Food.sellPrice
    stack_size          INTEGER,    -- 1 when the item can't be stacked
    can_be_sold         INTEGER,
    can_be_aged         INTEGER,
    must_age            INTEGER,    -- hasToBeAgedMeal: unusable as an ingredient until aged
    contains_alcohol    INTEGER,
    excluded_from_trends INTEGER,
    excluded_from_shops INTEGER,
    required_reputation INTEGER,    -- ReputationInfo.repNumber, when the item needs one
    description         TEXT        -- English when available
);

-- Direct members of each ingredient group. Expand recursively with
-- trtool.catalogue.expand(); members can themselves be groups.
CREATE TABLE group_members (
    group_id        INTEGER NOT NULL,
    member_id       INTEGER NOT NULL,
    mod_id          INTEGER,        -- 'explicit' members can name a modifier item (e.g. Malt from Barley)
    rule            TEXT NOT NULL,  -- 'explicit' (possibleItems) | 'type' (ingredientsTypes)
    ingredient_type INTEGER         -- the matching type, for rule = 'type'
);

CREATE TABLE recipes (
    recipe_id           INTEGER PRIMARY KEY,
    output_id           INTEGER,
    output_qty          INTEGER,
    minutes             INTEGER,
    fuel                INTEGER,
    page                INTEGER,
    recipe_group        INTEGER,
    unlock              INTEGER,    -- raw enum; 1 looks like the Altar ("Templo Recetas"), see docs/findings.md
    reputation          INTEGER,    -- ReputationInfo.repNumber
    arcane_reputation   INTEGER,
    sorcery_level       INTEGER,
    recipe_fragments    INTEGER,
    shop_silver_price   REAL,
    exclude_from_trends INTEGER,
    save_ingredients    INTEGER,    -- saveIngredientsAdded
    replaced            INTEGER NOT NULL DEFAULT 0,  -- flagged: kept, but not used by helpers or reports
    replaced_by         INTEGER     -- recipe_id of the successor
);

CREATE TABLE recipe_inputs (
    recipe_id INTEGER NOT NULL,
    slot      INTEGER NOT NULL,     -- 0-based, game order
    input_id  INTEGER NOT NULL,     -- item or group
    mod_id    INTEGER,
    qty       INTEGER,
    PRIMARY KEY (recipe_id, slot)
);

-- Which crafting stations can make which recipes (many-to-many: Oven and
-- Advanced Oven share a list).
CREATE TABLE crafter_recipes (
    crafter_id INTEGER NOT NULL,    -- the station's item id (Oven 672, Grinder 667, ...)
    recipe_id  INTEGER NOT NULL,
    PRIMARY KEY (crafter_id, recipe_id)
);

-- Seasons: 0 = not available, 1 = available, 2 = best season.
CREATE TABLE crops (
    crop_id             INTEGER PRIMARY KEY,
    label               TEXT,       -- the game's internal object name
    seed_id             INTEGER,
    days_to_grow        INTEGER,
    regrow_days         INTEGER,    -- NULL when the crop is harvested once
    spring              INTEGER,
    summer              INTEGER,
    autumn              INTEGER,
    winter              INTEGER,
    best_season_amount  INTEGER,
    needs_magic_fertilizer INTEGER
);

CREATE TABLE crop_harvests (
    crop_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    qty     INTEGER
);

-- Fishing data for Fish items. season_mask is the raw bitmask (for crops the
-- same style of mask is spring 1, summer 2, autumn 4, winter 8; not yet
-- verified for fish).
CREATE TABLE fish (
    item_id        INTEGER PRIMARY KEY,
    fishing_method INTEGER,
    bait_type      INTEGER,
    water_type     INTEGER,
    mine_biome     INTEGER,
    difficulty     INTEGER,
    season_mask    INTEGER,
    min_length     INTEGER,
    max_length     INTEGER
);

CREATE TABLE shops (
    shop_id     INTEGER PRIMARY KEY,
    label       TEXT,               -- the game's internal object name (usually the vendor)
    shop_type   INTEGER,
    update_days TEXT                -- raw Shop.updateDays list, comma-separated (meaning not confirmed)
);

CREATE TABLE shop_items (
    shop_id       INTEGER NOT NULL,
    item_id       INTEGER NOT NULL,
    always_appear INTEGER,
    unlimited     INTEGER,
    min_qty       INTEGER,
    max_qty       INTEGER,
    weight        REAL
);

CREATE TABLE shop_recipes (
    shop_id   INTEGER NOT NULL,
    recipe_id INTEGER NOT NULL
);

CREATE INDEX group_members_by_member ON group_members (member_id);
CREATE INDEX recipe_inputs_by_input ON recipe_inputs (input_id);
CREATE INDEX recipes_by_output ON recipes (output_id);

-- Where an item comes from. Forage is not covered yet.
CREATE VIEW sources AS
    SELECT output_id AS item_id, 'craft' AS source_type, recipe_id AS source_id, output_qty AS qty
      FROM recipes WHERE replaced = 0
    UNION ALL
    SELECT item_id, 'crop', crop_id, qty FROM crop_harvests
    UNION ALL
    SELECT item_id, 'fish', NULL, NULL FROM fish
    UNION ALL
    SELECT item_id, 'shop', shop_id, NULL FROM shop_items;
