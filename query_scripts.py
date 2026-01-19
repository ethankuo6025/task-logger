from db import get_cursor
from datetime import datetime, date

def _get_or_create(table, name, extra_cols=None, extra_vals=None):
    """Generic get-or-create for categories/tags."""
    name = name.strip()
    where_clause = "LOWER(name) = LOWER(%s)"
    where_params = [name]
    
    if extra_cols:
        where_clause = f"{extra_cols[0]} = %s AND " + where_clause
        where_params = [extra_vals[0]] + where_params
    
    with get_cursor(write=True) as cursor:
        cursor.execute(f"SELECT id FROM {table} WHERE {where_clause}", where_params)
        existing = cursor.fetchone()
        if existing:
            return existing[0], False
        
        cols = ["name"] + (extra_cols or [])
        vals = [name] + (extra_vals or [])
        placeholders = ", ".join(["%s"] * len(vals))
        cursor.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) RETURNING id", vals)
        return cursor.fetchone()[0], True

def _rename(table, id, new_name):
    """Generic rename for categories/tags."""
    with get_cursor(write=True) as cursor:
        cursor.execute(f"UPDATE {table} SET name = %s WHERE id = %s", (new_name.strip(), id))
    return [f"Renamed to '{new_name}'"]

def _delete(table, id, name_query="SELECT name FROM {table} WHERE id = %s"):
    """Generic delete for tags."""
    with get_cursor(write=True) as cursor:
        cursor.execute(name_query.format(table=table), (id,))
        row = cursor.fetchone()
        if not row:
            return [f"Not found"]
        cursor.execute(f"DELETE FROM {table} WHERE id = %s", (id,))
    return [f"Deleted '{row[0]}'"]

def get_all_categories():
    """Get all categories with their colors."""
    with get_cursor(write=False) as cursor:
        cursor.execute("SELECT id, name, color FROM categories ORDER BY name")
        return cursor.fetchall()

def get_or_create_category(name, color=None):
    """Create or get existing category."""
    return _get_or_create("categories", name, ["color"], [color])[0]

def rename_category(category_id, new_name):
    """Rename a category."""
    return _rename("categories", category_id, new_name)

def update_category_color(category_id, color):
    """Update category color (hex format: #RRGGBB)."""
    with get_cursor(write=True) as cursor:
        cursor.execute("UPDATE categories SET color = %s WHERE id = %s", (color, category_id))
        return cursor.rowcount > 0

def delete_category(category_id):
    """Delete category and all its activities."""
    with get_cursor(write=True) as cursor:
        cursor.execute("SELECT name FROM categories WHERE id = %s", (category_id,))
        row = cursor.fetchone()
        if not row:
            return ["Category not found"]
        
        cursor.execute("SELECT COUNT(*) FROM activities WHERE category_id = %s", (category_id,))
        count = cursor.fetchone()[0]
        cursor.execute("DELETE FROM categories WHERE id = %s", (category_id,))
    return [f"Deleted category '{row[0]}' and {count} activities"]

def get_tags_for_category(category_id):
    """Get all tags for a specific category."""
    with get_cursor(write=False) as cursor:
        cursor.execute("SELECT id, name FROM tags WHERE category_id = %s ORDER BY name", (category_id,))
        return cursor.fetchall()

def get_or_create_tag(category_id, name):
    """Create or get existing tag within a category."""
    return _get_or_create("tags", name, ["category_id"], [category_id])[0]

def rename_tag(tag_id, new_name):
    """Rename a tag."""
    return _rename("tags", tag_id, new_name)

def delete_tag(tag_id):
    """Delete a tag."""
    return _delete("tags", tag_id)

def check_overlap_range(start_time, end_time, exclude_id=None):
    """Check if the range overlaps with any existing activity."""
    with get_cursor(write=False) as cursor:
        query = "SELECT id, start_time, end_time FROM activities WHERE start_time < %s AND end_time > %s"
        params = [end_time, start_time]
        if exclude_id:
            query += " AND id != %s"
            params.append(exclude_id)
        cursor.execute(query + " ORDER BY start_time", params)
        return cursor.fetchall()

def log_activity(start_time, end_time, category_id, tag_ids=None, notes=None):
    """Log a new activity."""
    overlaps = check_overlap_range(start_time, end_time)
    if overlaps:
        raise ValueError(overlaps)
    
    with get_cursor(write=True) as cursor:
        cursor.execute(
            "INSERT INTO activities (start_time, end_time, category_id, notes) VALUES (%s, %s, %s, %s) RETURNING id",
            (start_time, end_time, category_id, notes or None),
        )
        activity_id = cursor.fetchone()[0]
        
        for tag_id in (tag_ids or []):
            cursor.execute(
                "INSERT INTO activity_tags (activity_id, tag_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (activity_id, tag_id),
            )
    
    return activity_id, int((end_time - start_time).total_seconds() / 60)

def update_activity(activity_id, start_time=None, end_time=None, category_id=None, notes=None):
    """Update activity fields."""
    if start_time is not None or end_time is not None:
        activity = get_activity(activity_id)
        if not activity:
            return False
        
        overlaps = check_overlap_range(
            start_time or activity['start_time'],
            end_time or activity['end_time'],
            exclude_id=activity_id
        )
        if overlaps:
            raise ValueError(overlaps)
    
    updates, params = [], []
    for field, value in [("start_time", start_time), ("end_time", end_time), ("category_id", category_id)]:
        if value is not None:
            updates.append(f"{field} = %s")
            params.append(value)
    
    if notes is not None:
        updates.append("notes = %s")
        params.append(notes.strip() or None)
    
    if not updates:
        return False
    
    params.append(activity_id)
    with get_cursor(write=True) as cursor:
        cursor.execute(f"UPDATE activities SET {', '.join(updates)} WHERE id = %s", params)
        return cursor.rowcount > 0

def update_activity_category(activity_id, new_category_id):
    """Update activity category."""
    with get_cursor(write=True) as cursor:
        cursor.execute("UPDATE activities SET category_id = %s WHERE id = %s", (new_category_id, activity_id))

def update_activity_tags(activity_id, tag_ids):
    """Replace activity tags."""
    with get_cursor(write=True) as cursor:
        cursor.execute("DELETE FROM activity_tags WHERE activity_id = %s", (activity_id,))
        for tag_id in tag_ids:
            cursor.execute(
                "INSERT INTO activity_tags (activity_id, tag_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (activity_id, tag_id),
            )

def delete_activity(activity_id):
    """Delete an activity."""
    with get_cursor(write=True) as cursor:
        cursor.execute("SELECT start_time, end_time FROM activities WHERE id = %s", (activity_id,))
        row = cursor.fetchone()
        if not row:
            return None
        cursor.execute("DELETE FROM activities WHERE id = %s", (activity_id,))
    return row  # Return start/end for confirmation message

def get_activity(activity_id):
    """Get single activity details."""
    with get_cursor(write=False) as cursor:
        cursor.execute(
            """SELECT id, start_time, end_time, category_id, category_name, notes, 
                      duration_minutes, tags, category_color 
               FROM activities_view WHERE id = %s""",
            (activity_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        
        cursor.execute("SELECT tag_id FROM activity_tags WHERE activity_id = %s", (activity_id,))
        
        return {
            'id': row[0], 'start_time': row[1], 'end_time': row[2], 'category_id': row[3],
            'category_name': row[4], 'notes': row[5], 'duration_minutes': row[6], 'tags': row[7],
            'category_color': row[8], 'tag_ids': [r[0] for r in cursor.fetchall()],
        }

def _get_activities(where_clause, params, order="ASC", limit=None):
    """Generic activity fetcher - returns with color."""
    query = f"""SELECT id, start_time, end_time, category_name, duration_minutes, 
                       tags, notes, category_color 
                FROM activities_view 
                WHERE {where_clause} 
                ORDER BY start_time {order}"""
    if limit:
        query += f" LIMIT {limit}"
    
    with get_cursor(write=False) as cursor:
        cursor.execute(query, params)
        return cursor.fetchall()

def get_activities_by_date(target_date):
    """Get activities for a specific date."""
    return _get_activities("DATE(start_time) = %s", (target_date,))

def get_activities_in_range(start_date, end_date):
    """Get activities within date range."""
    return _get_activities("DATE(start_time) >= %s AND DATE(start_time) <= %s", (start_date, end_date))

def get_recent_activities(limit=10):
    """Get most recent activities."""
    return _get_activities("1=1", (), order="DESC", limit=limit)

def report_daily(start_date, end_date):
    """Generate daily summary report."""
    with get_cursor(write=False) as cursor:
        cursor.execute("""
            SELECT DATE(start_time), COUNT(*), 
                   COALESCE(SUM(EXTRACT(EPOCH FROM (end_time - start_time)) / 60), 0)::INTEGER
            FROM activities WHERE DATE(start_time) >= %s AND DATE(start_time) <= %s
            GROUP BY DATE(start_time) ORDER BY DATE(start_time) DESC
        """, (start_date, end_date))
        return cursor.fetchall()

def report_categories(start_date, end_date):
    """Generate category time report."""
    with get_cursor(write=False) as cursor:
        cursor.execute("""
            SELECT c.name, c.color, COUNT(a.id), 
                   COALESCE(SUM(EXTRACT(EPOCH FROM (a.end_time - a.start_time)) / 60), 0)::INTEGER
            FROM categories c
            LEFT JOIN activities a ON c.id = a.category_id 
                AND DATE(a.start_time) >= %s AND DATE(a.start_time) <= %s
            GROUP BY c.id, c.name, c.color 
            HAVING COUNT(a.id) > 0 
            ORDER BY 4 DESC
        """, (start_date, end_date))
        return cursor.fetchall()

def report_tags(start_date, end_date):
    """Generate tag time report."""
    with get_cursor(write=False) as cursor:
        cursor.execute("""
            SELECT c.name, c.color, t.name, COUNT(DISTINCT a.id),
                   COALESCE(SUM(EXTRACT(EPOCH FROM (a.end_time - a.start_time)) / 60), 0)::INTEGER
            FROM tags t
            JOIN categories c ON t.category_id = c.id
            LEFT JOIN activity_tags at ON t.id = at.tag_id
            LEFT JOIN activities a ON at.activity_id = a.id 
                AND DATE(a.start_time) >= %s AND DATE(a.start_time) <= %s
            GROUP BY c.id, c.name, c.color, t.id, t.name 
            HAVING COUNT(a.id) > 0 
            ORDER BY c.name, 5 DESC
        """, (start_date, end_date))
        return cursor.fetchall()