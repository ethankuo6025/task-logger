CREATE TABLE categories (
    id INTEGER PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE
);


CREATE TABLE tags (
    id INTEGER PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE
);

CREATE TABLE entries (
    id INTEGER PRIMARY KEY,
    category_id INTEGER NOT NULL,
    title VARCHAR(200) NOT NULL,
    notes TEXT,
    start_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    duration_minutes INTEGER,
    FOREIGN KEY (category_id) REFERENCES categories(id)
);


-- junction table for entries to tags
CREATE TABLE entry_tags (
    entry_id INTEGER,
    tag_id INTEGER,
    PRIMARY KEY (entry_id, tag_id),
    FOREIGN KEY (entry_id) REFERENCES entries(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);

CREATE INDEX idx_entries_start_time ON entries(start_time);
CREATE INDEX idx_entries_category_id ON entries(category_id);