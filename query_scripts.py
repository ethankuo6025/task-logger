from db import get_cursor
from datetime import datetime, date, timedelta

def print_help():
    return """
┌────────────────────────────────────────────────────────────────────────┐
│                           TASK LOGGER                                  │
├────────────────────────────────────────────────────────────────────────┤
│  CORE COMMANDS                                                         │
│    log     Log activities (supports chaining)                          │
│    edit    Edit an existing activity                                   │
│    delete  Delete an activity                                          │
│                                                                        │
│  VIEW COMMAND                                                          │
│    view    View activities:                                            │
│            - t/today (default), y/yesterday, -N (N days ago)           │
│            - w (this week), w-N (N weeks ago)                          │
│            - r/range (date range), or enter date (YYYY-MM-DD)          │
│                                                                        │
│  REPORT COMMAND                                                        │
│    report  Generate reports:                                           │
│            - daily (summary by day)                                    │
│            - category (time by category)                               │
│            - tag (time by tag within category)                         │
│                                                                        │
│  MANAGE COMMAND                                                        │
│    manage  Manage categories and their tags                            │
│                                                                        │
│  OTHER                                                                 │
│    help    Show this help screen                                       │
│                                                                        │
│  TIME FORMAT: 9:30, 9:30am, 9:30pm (defaults to AM)                    │
│  Ctrl+C to exit  |  Ctrl+Z to cancel current input                     │
└────────────────────────────────────────────────────────────────────────┘
"""

def format_duration(minutes):
    if not minutes:
        return "0m"
    hours, mins = divmod(minutes, 60)
    return f"{hours}h {mins}m" if hours else f"{mins}m"

def format_time(ts):
    return ts.strftime("%I:%M%p").lstrip("0").lower() if isinstance(ts, datetime) else (str(ts) if ts else "")

def format_date_short(ts):
    return ts.strftime("%m/%d") if isinstance(ts, (datetime, date)) else (str(ts) if ts else "")

def format_table(headers, rows):
    rows = list(rows)
    if not rows:
        return ["(no data)"]
    
    widths = [max(len(str(h)), max(len(str(cell) if cell else "") for cell in col)) 
              for h, col in zip(headers, zip(*rows))]
    
    fmt = " | ".join(f"{{:<{w}}}" for w in widths)
    sep = "-+-".join("-" * w for w in widths)
    
    return [fmt.format(*headers), sep] + [fmt.format(*(str(c) if c else "" for c in row)) for row in rows]


def format_activities_table(rows, show_date=False):
    if not rows:
        return ["No activities found."]
    
    formatted = []
    total_minutes = 0
    
    for id, start, end, category, dur, tags, notes in rows:
        start_str = f"{format_date_short(start)} {format_time(start)}" if show_date else format_time(start)
        cat_tags = f"{category}: {tags[:20]}..." if tags and len(tags) > 20 else (f"{category}: {tags}" if tags else category)
        cat_tags = cat_tags[:30] + "..." if len(cat_tags) > 30 else cat_tags
        notes_display = (notes[:20] + "..." if len(notes) > 20 else notes) if notes else "-"
        
        formatted.append((id, start_str, format_time(end), format_duration(dur), cat_tags, notes_display))
        total_minutes += dur or 0
    
    lines = format_table(["ID", "Start", "End", "Duration", "Category/Tags", "Notes"], formatted)
    lines.extend(["", f"Total: {len(rows)} activities, {format_duration(total_minutes)}"])
    return lines

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
    with get_cursor(write=False) as cursor:
        cursor.execute("SELECT id, name, color FROM categories ORDER BY name")
        return cursor.fetchall()

def get_or_create_category(name):
    return _get_or_create("categories", name, ["color"], [None])[0]

def rename_category(category_id, new_name):
    return _rename("categories", category_id, new_name)

def delete_category(category_id):
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
    with get_cursor(write=False) as cursor:
        cursor.execute("SELECT id, name FROM tags WHERE category_id = %s ORDER BY name", (category_id,))
        return cursor.fetchall()

def get_or_create_tag(category_id, name):
    return _get_or_create("tags", name, ["category_id"], [category_id])[0]

def rename_tag(tag_id, new_name):
    return _rename("tags", tag_id, new_name)

def delete_tag(tag_id):
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
    with get_cursor(write=True) as cursor:
        cursor.execute("UPDATE activities SET category_id = %s WHERE id = %s", (new_category_id, activity_id))

def update_activity_tags(activity_id, tag_ids):
    with get_cursor(write=True) as cursor:
        cursor.execute("DELETE FROM activity_tags WHERE activity_id = %s", (activity_id,))
        for tag_id in tag_ids:
            cursor.execute(
                "INSERT INTO activity_tags (activity_id, tag_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (activity_id, tag_id),
            )

def delete_activity(activity_id):
    with get_cursor(write=True) as cursor:
        cursor.execute("SELECT start_time, end_time FROM activities WHERE id = %s", (activity_id,))
        row = cursor.fetchone()
        if not row:
            return None
        cursor.execute("DELETE FROM activities WHERE id = %s", (activity_id,))
    return f"{format_time(row[0])} - {format_time(row[1])}"

def get_activity(activity_id):
    with get_cursor(write=False) as cursor:
        cursor.execute(
            "SELECT id, start_time, end_time, category_id, category_name, notes, duration_minutes, tags FROM activities_view WHERE id = %s",
            (activity_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        
        cursor.execute("SELECT tag_id FROM activity_tags WHERE activity_id = %s", (activity_id,))
        
        return {
            'id': row[0], 'start_time': row[1], 'end_time': row[2], 'category_id': row[3],
            'category_name': row[4], 'notes': row[5], 'duration_minutes': row[6], 'tags': row[7],
            'tag_ids': [r[0] for r in cursor.fetchall()],
        }

def _get_activities(where_clause, params, order="ASC", limit=None):
    """Generic activity fetcher."""
    query = f"SELECT id, start_time, end_time, category_name, duration_minutes, tags, notes FROM activities_view WHERE {where_clause} ORDER BY start_time {order}"
    if limit:
        query += f" LIMIT {limit}"
    
    with get_cursor(write=False) as cursor:
        cursor.execute(query, params)
        return cursor.fetchall()

def get_activities_by_date(target_date):
    return _get_activities("DATE(start_time) = %s", (target_date,))

def get_activities_in_range(start_date, end_date):
    return _get_activities("DATE(start_time) >= %s AND DATE(start_time) <= %s", (start_date, end_date))

def get_recent_activities(limit=10):
    return _get_activities("1=1", (), order="DESC", limit=limit)

def report_daily(start_date, end_date):
    with get_cursor(write=False) as cursor:
        cursor.execute("""
            SELECT DATE(start_time), COUNT(*), 
                   COALESCE(SUM(EXTRACT(EPOCH FROM (end_time - start_time)) / 60), 0)::INTEGER
            FROM activities WHERE DATE(start_time) >= %s AND DATE(start_time) <= %s
            GROUP BY DATE(start_time) ORDER BY DATE(start_time) DESC
        """, (start_date, end_date))
        rows = cursor.fetchall()
    
    if not rows:
        return [f"No data between {start_date} and {end_date}"]
    
    total_activities = sum(r[1] for r in rows)
    total_minutes = sum(r[2] for r in rows)
    
    formatted = [(str(d), d.strftime("%a"), count, format_duration(mins)) for d, count, mins in rows]
    
    lines = [f"Daily Summary: {start_date} to {end_date}", ""]
    lines.extend(format_table(["Date", "Day", "Activities", "Duration"], formatted))
    lines.extend(["", f"Total: {total_activities} activities, {format_duration(total_minutes)}"])
    return lines

def report_categories(start_date, end_date):
    with get_cursor(write=False) as cursor:
        cursor.execute("""
            SELECT c.name, COUNT(a.id), 
                   COALESCE(SUM(EXTRACT(EPOCH FROM (a.end_time - a.start_time)) / 60), 0)::INTEGER
            FROM categories c
            LEFT JOIN activities a ON c.id = a.category_id AND DATE(a.start_time) >= %s AND DATE(a.start_time) <= %s
            GROUP BY c.id, c.name HAVING COUNT(a.id) > 0 ORDER BY 3 DESC
        """, (start_date, end_date))
        rows = cursor.fetchall()
    
    if not rows:
        return [f"No data between {start_date} and {end_date}"]
    
    total_minutes = sum(r[2] for r in rows)
    formatted = [(name, count, format_duration(mins), f"{mins/total_minutes*100:.1f}%" if total_minutes else "0%") 
                 for name, count, mins in rows]
    
    lines = [f"Time by Category: {start_date} to {end_date}", ""]
    lines.extend(format_table(["Category", "Activities", "Duration", "% of Total"], formatted))
    lines.extend(["", f"Total: {format_duration(total_minutes)}"])
    return lines

def report_tags(start_date, end_date):
    with get_cursor(write=False) as cursor:
        cursor.execute("""
            SELECT c.name, t.name, COUNT(DISTINCT a.id),
                   COALESCE(SUM(EXTRACT(EPOCH FROM (a.end_time - a.start_time)) / 60), 0)::INTEGER
            FROM tags t
            JOIN categories c ON t.category_id = c.id
            LEFT JOIN activity_tags at ON t.id = at.tag_id
            LEFT JOIN activities a ON at.activity_id = a.id AND DATE(a.start_time) >= %s AND DATE(a.start_time) <= %s
            GROUP BY c.id, c.name, t.id, t.name HAVING COUNT(a.id) > 0 ORDER BY c.name, 4 DESC
        """, (start_date, end_date))
        rows = cursor.fetchall()
    
    if not rows:
        return [f"No tagged activities between {start_date} and {end_date}"]
    
    formatted = [(cat, tag, count, format_duration(mins)) for cat, tag, count, mins in rows]
    
    lines = [f"Time by Tag: {start_date} to {end_date}", ""]
    lines.extend(format_table(["Category", "Tag", "Activities", "Duration"], formatted))
    return lines