-- Built from the TSV files in data/ by `trtool build-db`.
-- The database is disposable: edit the TSVs, then rebuild.

CREATE TABLE items (
    id              INTEGER PRIMARY KEY,   -- in-game item ID (as in the save)
    name            TEXT,
    category        TEXT,                  -- Food, Drinks, Ingredient, Decor, ...
    serving         TEXT,                  -- 'tap' if it can go on a tap; any drink fits a keg
    name_confidence TEXT,                  -- wiki | confirmed | likely | guess | set known
    name_basis      TEXT                   -- why we believe the name
);

-- Where to get an item: shop, crop, forage, fishing, crafted, ...
CREATE TABLE item_sources (
    item_id     INTEGER NOT NULL,
    source_type TEXT NOT NULL,
    source      TEXT,
    notes       TEXT
);

-- Seen in a save: dish `dish_id` cooked with ingredient `ingredient_id`.
-- This is how the tool knows which ingredient choices a dish accepts.
CREATE TABLE dish_ingredients (
    dish_id       INTEGER NOT NULL,
    ingredient_id INTEGER NOT NULL,
    seen_count    INTEGER NOT NULL DEFAULT 1,
    first_seen    TEXT,
    last_seen     TEXT,
    PRIMARY KEY (dish_id, ingredient_id)
);

-- Seen in a save's crafting history: recipe inputs (one row per input).
CREATE TABLE recipe_inputs (
    recipe_id     INTEGER NOT NULL,
    output_id     INTEGER NOT NULL,
    ingredient_id INTEGER NOT NULL,
    amount        INTEGER,
    first_seen    TEXT,
    last_seen     TEXT,
    PRIMARY KEY (recipe_id, ingredient_id, amount)
);

CREATE INDEX dish_ingredients_by_ingredient ON dish_ingredients (ingredient_id);
CREATE INDEX recipe_inputs_by_output ON recipe_inputs (output_id);

-- Handy for ad-hoc queries: names on both sides.
CREATE VIEW dish_ingredients_named AS
SELECT d.dish_id, di.name AS dish, d.ingredient_id, ii.name AS ingredient,
       d.seen_count, d.first_seen, d.last_seen
FROM dish_ingredients d
LEFT JOIN items di ON di.id = d.dish_id
LEFT JOIN items ii ON ii.id = d.ingredient_id;
