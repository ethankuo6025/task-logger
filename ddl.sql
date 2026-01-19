-- Categories (e.g., Work, Study, Relaxation, Exercise)
CREATE TABLE IF NOT EXISTS categories (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    color TEXT,  -- Hex color format: #RRGGBB
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT category_name_not_empty CHECK (length(trim(name)) > 0),
    CONSTRAINT valid_color_format CHECK (color IS NULL OR color ~ '^#[0-9A-Fa-f]{6}$')
);

-- Tags belong to a specific category
CREATE TABLE IF NOT EXISTS tags (
    id SERIAL PRIMARY KEY,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT tag_name_not_empty CHECK (length(trim(name)) > 0),
    CONSTRAINT unique_tag_per_category UNIQUE (category_id, name)
);

-- Activities table
CREATE TABLE IF NOT EXISTS activities (
    id SERIAL PRIMARY KEY,
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP NOT NULL,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT valid_time_range CHECK (end_time > start_time)
);

-- Many-to-many: activities <-> tags
CREATE TABLE IF NOT EXISTS activity_tags (
    activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (activity_id, tag_id)
);

-- ============================================================
-- INDEXES (created if not exist)
-- ============================================================

CREATE UNIQUE INDEX IF NOT EXISTS idx_categories_name_lower ON categories(LOWER(name));
CREATE UNIQUE INDEX IF NOT EXISTS idx_tags_name_lower ON tags(category_id, LOWER(name));
CREATE INDEX IF NOT EXISTS idx_activities_start_time ON activities(start_time);
CREATE INDEX IF NOT EXISTS idx_activities_end_time ON activities(end_time);
CREATE INDEX IF NOT EXISTS idx_activities_start_date ON activities(DATE(start_time));
CREATE INDEX IF NOT EXISTS idx_activities_category ON activities(category_id);
CREATE INDEX IF NOT EXISTS idx_tags_category ON tags(category_id);
CREATE INDEX IF NOT EXISTS idx_activity_tags_tag_id ON activity_tags(tag_id);

-- ============================================================
-- FUNCTIONS (drop and recreate to allow updates)
-- ============================================================

DROP FUNCTION IF EXISTS update_updated_at_column() CASCADE;

CREATE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- TRIGGERS
-- ============================================================

DROP TRIGGER IF EXISTS update_activities_updated_at ON activities;

CREATE TRIGGER update_activities_updated_at
    BEFORE UPDATE ON activities
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
-- VIEWS (drop and recreate to allow updates)
-- ============================================================

DROP VIEW IF EXISTS activities_view CASCADE;
DROP VIEW IF EXISTS tag_stats CASCADE;
DROP VIEW IF EXISTS category_stats CASCADE;

-- View: Activities with duration, category, color, and tags
CREATE VIEW activities_view AS
SELECT 
    a.id,
    a.start_time,
    a.end_time,
    a.category_id,
    c.name AS category_name,
    c.color AS category_color,
    a.notes,
    EXTRACT(EPOCH FROM (a.end_time - a.start_time))::INTEGER / 60 AS duration_minutes,
    COALESCE(STRING_AGG(t.name, ', ' ORDER BY t.name), '') AS tags,
    a.created_at,
    a.updated_at
FROM activities a
JOIN categories c ON a.category_id = c.id
LEFT JOIN activity_tags at ON a.id = at.activity_id
LEFT JOIN tags t ON at.tag_id = t.id
GROUP BY a.id, c.id
ORDER BY a.start_time DESC;

-- View: Category statistics
CREATE VIEW category_stats AS
SELECT 
    c.id,
    c.name,
    c.color,
    COUNT(a.id) AS activity_count,
    COALESCE(SUM(
        EXTRACT(EPOCH FROM (a.end_time - a.start_time)) / 60
    ), 0)::INTEGER AS total_minutes
FROM categories c
LEFT JOIN activities a ON c.id = a.category_id
GROUP BY c.id
ORDER BY total_minutes DESC;

-- View: Tag statistics (within their categories)
CREATE VIEW tag_stats AS
SELECT 
    t.id,
    t.name,
    t.category_id,
    c.name AS category_name,
    c.color AS category_color,
    COUNT(at.activity_id) AS activity_count,
    COALESCE(SUM(
        EXTRACT(EPOCH FROM (a.end_time - a.start_time)) / 60
    ), 0)::INTEGER AS total_minutes
FROM tags t
JOIN categories c ON t.category_id = c.id
LEFT JOIN activity_tags at ON t.id = at.tag_id
LEFT JOIN activities a ON at.activity_id = a.id
GROUP BY t.id, c.id
ORDER BY c.name, total_minutes DESC;