from db import get_cursor
from datetime import datetime, date, timedelta


def format_table(headers, rows):
    rows = list(rows)
    if not rows:
        return ["(no rows)"]

    widths = [len(str(h)) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell) if cell is not None else ""))

    header_fmt = " | ".join(f"{{:<{w}}}" for w in widths)
    sep = "-+-".join("-" * w for w in widths)

    lines = [header_fmt.format(*headers), sep]
    for row in rows:
        cells = [str(c) if c is not None else "" for c in row]
        lines.append(header_fmt.format(*cells))
    return lines


def format_duration(minutes):
    if minutes is None or minutes == 0:
        return "0m"
    hours = minutes // 60
    mins = minutes % 60
    if hours > 0:
        return f"{hours}h {mins}m"
    return f"{mins}m"


def format_time(ts):
    if ts is None:
        return ""
    if isinstance(ts, datetime):
        return ts.strftime("%I:%M%p").lstrip("0").lower()
    return str(ts)


def format_datetime(ts):
    if ts is None:
        return ""
    if isinstance(ts, datetime):
        return ts.strftime("%Y-%m-%d %I:%M%p").replace(" 0", " ").lower()
    return str(ts)


def format_date_short(ts):
    if ts is None:
        return ""
    if isinstance(ts, (datetime, date)):
        return ts.strftime("%m/%d")
    return str(ts)


# ============================================================
# HELP
# ============================================================

def print_help():
    return """
┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                        TASK LOGGER                                                                                               │
├──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│  LOGGING                                                          VIEWING                                                        │
│    log              Log activities (supports chaining)              today            View today's activities                     │
│    edit             Edit an existing activity                       yesterday        View yesterday's activities                 │
│    delete           Delete an activity                              week             View this week's activities                 │
│                                                                     range            View activities in date range               │
│  CATEGORIES & TAGS                                                                                                               │
│    recent           View N most recent activities                 REPORTS                                                        │
│    categories       List all categories with stats                  report daily     Daily breakdown for date range              │
│    tags             List all tags by category                       report categories Time per category for date range           │
│    rename category  Rename a category                               report tags      Time per tag for date range                 │
│    rename tag       Rename a tag                                                                                                 │
│    delete category  Delete a category (and its activities!)       OTHER                                                          │
│    delete tag       Delete a tag                                    help             Show this help screen                       │
│                                                                                                                                  │
│  TIME FORMAT: 9:30, 9:30am, 9:30pm (defaults to AM)                                                                              │
│  Ctrl+C to exit  |  Ctrl+Z to cancel current input                                                                               │
└──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
"""


# ============================================================
# OVERLAP CHECKING
# ============================================================

def check_overlap_at_start(start_time, exclude_id=None):
    """
    Check if start_time falls within any existing activity.
    Returns the conflicting activity or None.
    """
    with get_cursor(write=False) as cursor:
        if exclude_id is None:
            cursor.execute(
                """
                SELECT id, start_time, end_time
                FROM activities
                WHERE start_time <= %s AND end_time > %s
                ORDER BY start_time
                LIMIT 1
                """,
                (start_time, start_time)
            )
        else:
            cursor.execute(
                """
                SELECT id, start_time, end_time
                FROM activities
                WHERE start_time <= %s AND end_time > %s AND id != %s
                ORDER BY start_time
                LIMIT 1
                """,
                (start_time, start_time, exclude_id)
            )
        return cursor.fetchone()


def check_overlap_range(start_time, end_time, exclude_id=None):
    """
    Check if the range [start_time, end_time) overlaps with any existing activity.
    Returns list of conflicting activities.
    """
    with get_cursor(write=False) as cursor:
        if exclude_id is None:
            cursor.execute(
                """
                SELECT id, start_time, end_time
                FROM activities
                WHERE start_time < %s AND end_time > %s
                ORDER BY start_time
                LIMIT 5
                """,
                (end_time, start_time)
            )
        else:
            cursor.execute(
                """
                SELECT id, start_time, end_time
                FROM activities
                WHERE start_time < %s AND end_time > %s AND id != %s
                ORDER BY start_time
                LIMIT 5
                """,
                (end_time, start_time, exclude_id)
            )
        return cursor.fetchall()


# ============================================================
# CATEGORIES
# ============================================================

def create_category(name, color=None):
    """Create a new category. Returns (id, was_created)."""
    name = name.strip()
    with get_cursor(write=True) as cursor:
        cursor.execute(
            "SELECT id FROM categories WHERE LOWER(name) = LOWER(%s)",
            (name,)
        )
        existing = cursor.fetchone()
        if existing:
            return existing[0], False
        
        cursor.execute(
            "INSERT INTO categories (name, color) VALUES (%s, %s) RETURNING id",
            (name, color),
        )
        return cursor.fetchone()[0], True


def rename_category(category_id, new_name):
    with get_cursor(write=True) as cursor:
        cursor.execute(
            "UPDATE categories SET name = %s WHERE id = %s",
            (new_name.strip(), category_id),
        )
    return [f"Category renamed to '{new_name}'"]


def delete_category(category_id):
    with get_cursor(write=True) as cursor:
        cursor.execute("SELECT name FROM categories WHERE id = %s", (category_id,))
        row = cursor.fetchone()
        if not row:
            return [f"Category not found"]
        name = row[0]
        
        # Count activities that will be deleted
        cursor.execute(
            "SELECT COUNT(*) FROM activities WHERE category_id = %s",
            (category_id,)
        )
        count = cursor.fetchone()[0]
        
        cursor.execute("DELETE FROM categories WHERE id = %s", (category_id,))
    return [f"Deleted category '{name}' and {count} activities"]


def get_all_categories():
    with get_cursor(write=False) as cursor:
        cursor.execute("SELECT id, name, color FROM categories ORDER BY name")
        return cursor.fetchall()


def get_or_create_category(name):
    category_id, _ = create_category(name)
    return category_id


def view_categories():
    with get_cursor(write=False) as cursor:
        cursor.execute("""
            SELECT id, name, color, activity_count, total_minutes
            FROM category_stats
            ORDER BY name
        """)
        rows = cursor.fetchall()
    
    if not rows:
        return ["No categories yet. Categories are created when you log activities."]
    
    formatted = []
    for id, name, color, count, minutes in rows:
        formatted.append((
            id,
            name,
            color or "-",
            count,
            format_duration(minutes)
        ))
    
    return format_table(["ID", "Name", "Color", "Activities", "Total Time"], formatted)


# ============================================================
# TAGS
# ============================================================

def create_tag(category_id, name):
    """Create a new tag under a category. Returns (id, was_created)."""
    name = name.strip()
    with get_cursor(write=True) as cursor:
        cursor.execute(
            "SELECT id FROM tags WHERE category_id = %s AND LOWER(name) = LOWER(%s)",
            (category_id, name)
        )
        existing = cursor.fetchone()
        if existing:
            return existing[0], False
        
        cursor.execute(
            "INSERT INTO tags (category_id, name) VALUES (%s, %s) RETURNING id",
            (category_id, name),
        )
        return cursor.fetchone()[0], True


def rename_tag(tag_id, new_name):
    with get_cursor(write=True) as cursor:
        cursor.execute(
            "UPDATE tags SET name = %s WHERE id = %s",
            (new_name.strip(), tag_id),
        )
    return [f"Tag renamed to '{new_name}'"]


def delete_tag(tag_id):
    with get_cursor(write=True) as cursor:
        cursor.execute("SELECT name FROM tags WHERE id = %s", (tag_id,))
        row = cursor.fetchone()
        if not row:
            return [f"Tag not found"]
        name = row[0]
        cursor.execute("DELETE FROM tags WHERE id = %s", (tag_id,))
    return [f"Deleted tag '{name}'"]


def get_tags_for_category(category_id):
    """Get all tags for a specific category."""
    with get_cursor(write=False) as cursor:
        cursor.execute(
            "SELECT id, name FROM tags WHERE category_id = %s ORDER BY name",
            (category_id,)
        )
        return cursor.fetchall()


def get_all_tags():
    """Get all tags grouped by category."""
    with get_cursor(write=False) as cursor:
        cursor.execute("""
            SELECT t.id, t.name, t.category_id, c.name as category_name
            FROM tags t
            JOIN categories c ON t.category_id = c.id
            ORDER BY c.name, t.name
        """)
        return cursor.fetchall()


def get_or_create_tag(category_id, name):
    tag_id, _ = create_tag(category_id, name)
    return tag_id


def view_tags():
    with get_cursor(write=False) as cursor:
        cursor.execute("""
            SELECT id, name, category_name, activity_count, total_minutes
            FROM tag_stats
            ORDER BY category_name, name
        """)
        rows = cursor.fetchall()
    
    if not rows:
        return ["No tags yet. Tags are created when you log activities."]
    
    formatted = []
    for id, name, cat_name, count, minutes in rows:
        formatted.append((
            id,
            name,
            cat_name,
            count,
            format_duration(minutes)
        ))
    
    return format_table(["ID", "Tag", "Category", "Uses", "Total Time"], formatted)


# ============================================================
# ACTIVITIES
# ============================================================

def log_activity(start_time, end_time, category_id, tag_ids=None, notes=None):
    """Log a new activity."""
    with get_cursor(write=True) as cursor:
        cursor.execute(
            """
            INSERT INTO activities (start_time, end_time, category_id, notes)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (start_time, end_time, category_id, notes if notes else None),
        )
        activity_id = cursor.fetchone()[0]
        
        if tag_ids:
            for tag_id in tag_ids:
                cursor.execute(
                    """
                    INSERT INTO activity_tags (activity_id, tag_id)
                    VALUES (%s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (activity_id, tag_id),
                )
    
    duration = int((end_time - start_time).total_seconds() / 60)
    return activity_id, duration


def update_activity(activity_id, start_time=None, end_time=None, category_id=None, notes=None):
    """Update activity fields."""
    updates = []
    params = []
    
    if start_time is not None:
        updates.append("start_time = %s")
        params.append(start_time)
    if end_time is not None:
        updates.append("end_time = %s")
        params.append(end_time)
    if category_id is not None:
        updates.append("category_id = %s")
        params.append(category_id)
    if notes is not None:
        updates.append("notes = %s")
        params.append(notes if notes.strip() else None)
    
    if not updates:
        return False
    
    params.append(activity_id)
    
    with get_cursor(write=True) as cursor:
        cursor.execute(
            f"UPDATE activities SET {', '.join(updates)} WHERE id = %s",
            params,
        )
        return cursor.rowcount > 0


def update_activity_tags(activity_id, tag_ids):
    """Replace all tags for an activity."""
    with get_cursor(write=True) as cursor:
        cursor.execute(
            "DELETE FROM activity_tags WHERE activity_id = %s",
            (activity_id,),
        )
        for tag_id in tag_ids:
            cursor.execute(
                """
                INSERT INTO activity_tags (activity_id, tag_id)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
                """,
                (activity_id, tag_id),
            )


def delete_activity(activity_id):
    with get_cursor(write=True) as cursor:
        cursor.execute(
            "SELECT start_time, end_time FROM activities WHERE id = %s",
            (activity_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        start, end = row
        cursor.execute("DELETE FROM activities WHERE id = %s", (activity_id,))
    return f"{format_time(start)} - {format_time(end)}"


def get_activity(activity_id):
    """Get full activity details."""
    with get_cursor(write=False) as cursor:
        cursor.execute(
            """
            SELECT id, start_time, end_time, category_id, category_name, 
                   notes, duration_minutes, tags
            FROM activities_view
            WHERE id = %s
            """,
            (activity_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        
        cursor.execute(
            "SELECT tag_id FROM activity_tags WHERE activity_id = %s",
            (activity_id,),
        )
        tag_ids = [r[0] for r in cursor.fetchall()]
        
        return {
            'id': row[0],
            'start_time': row[1],
            'end_time': row[2],
            'category_id': row[3],
            'category_name': row[4],
            'notes': row[5],
            'duration_minutes': row[6],
            'tags': row[7],
            'tag_ids': tag_ids,
        }


def get_activities_by_date(target_date):
    with get_cursor(write=False) as cursor:
        cursor.execute(
            """
            SELECT id, start_time, end_time, category_name, notes, duration_minutes, tags
            FROM activities_view
            WHERE DATE(start_time) = %s
            ORDER BY start_time ASC
            """,
            (target_date,),
        )
        return cursor.fetchall()


def get_activities_in_range(start_date, end_date):
    with get_cursor(write=False) as cursor:
        cursor.execute(
            """
            SELECT id, start_time, end_time, category_name, notes, duration_minutes, tags
            FROM activities_view
            WHERE DATE(start_time) >= %s AND DATE(start_time) <= %s
            ORDER BY start_time ASC
            """,
            (start_date, end_date),
        )
        return cursor.fetchall()


def get_recent_activities(limit=10):
    with get_cursor(write=False) as cursor:
        cursor.execute(
            """
            SELECT id, start_time, end_time, category_name, notes, duration_minutes, tags
            FROM activities_view
            ORDER BY start_time DESC
            LIMIT %s
            """,
            (limit,),
        )
        return cursor.fetchall()


# ============================================================
# VIEW FORMATTING
# ============================================================

def format_activities_table(rows, show_date=False):
    if not rows:
        return ["No activities found."]
    
    formatted = []
    total_minutes = 0
    
    for id, start, end, category, notes, dur, tags in rows:
        if show_date:
            start_str = f"{format_date_short(start)} {format_time(start)}"
        else:
            start_str = format_time(start)
        
        # Combine category and tags
        cat_tags = category
        if tags:
            cat_tags = f"{category}: {tags[:20]}{'...' if len(tags) > 20 else ''}"
        
        notes_display = ""
        if notes:
            notes_display = notes[:20] + "..." if len(notes) > 20 else notes
        
        formatted.append((
            id,
            start_str,
            format_time(end),
            format_duration(dur),
            cat_tags[:30] + "..." if len(cat_tags) > 30 else cat_tags,
            notes_display or "-",
        ))
        total_minutes += dur or 0
    
    headers = ["ID", "Start", "End", "Duration", "Category/Tags", "Notes"]
    
    lines = format_table(headers, formatted)
    lines.append("")
    lines.append(f"Total: {len(rows)} activities, {format_duration(total_minutes)}")
    return lines


def view_today():
    rows = get_activities_by_date(date.today())
    lines = [f"Activities for {date.today()} (today)", ""]
    lines.extend(format_activities_table(rows, show_date=False))
    return lines


def view_yesterday():
    yesterday = date.today() - timedelta(days=1)
    rows = get_activities_by_date(yesterday)
    lines = [f"Activities for {yesterday} (yesterday)", ""]
    lines.extend(format_activities_table(rows, show_date=False))
    return lines


def view_week():
    today = date.today()
    start_of_week = today - timedelta(days=today.weekday())
    rows = get_activities_in_range(start_of_week, today)
    lines = [f"Activities for {start_of_week} to {today} (this week)", ""]
    lines.extend(format_activities_table(rows, show_date=True))
    return lines


def view_range(start_date, end_date):
    rows = get_activities_in_range(start_date, end_date)
    lines = [f"Activities for {start_date} to {end_date}", ""]
    lines.extend(format_activities_table(rows, show_date=True))
    return lines


def view_recent(limit=10):
    rows = get_recent_activities(limit)
    lines = [f"Last {limit} activities", ""]
    lines.extend(format_activities_table(rows, show_date=True))
    return lines


# ============================================================
# REPORTS
# ============================================================

def report_daily(start_date, end_date):
    with get_cursor(write=False) as cursor:
        cursor.execute(
            """
            SELECT 
                DATE(start_time) as activity_date,
                COUNT(*) as activity_count,
                COALESCE(SUM(
                    EXTRACT(EPOCH FROM (end_time - start_time)) / 60
                ), 0)::INTEGER as total_minutes
            FROM activities
            WHERE DATE(start_time) >= %s AND DATE(start_time) <= %s
            GROUP BY DATE(start_time)
            ORDER BY DATE(start_time) DESC
            """,
            (start_date, end_date),
        )
        rows = cursor.fetchall()
    
    if not rows:
        return [f"No data between {start_date} and {end_date}"]
    
    formatted = []
    total_minutes = 0
    total_activities = 0
    
    for activity_date, count, minutes in rows:
        day_name = activity_date.strftime("%a")
        formatted.append((
            str(activity_date),
            day_name,
            count,
            format_duration(minutes),
        ))
        total_minutes += minutes
        total_activities += count
    
    lines = [f"Daily Summary: {start_date} to {end_date}", ""]
    lines.extend(format_table(["Date", "Day", "Activities", "Duration"], formatted))
    lines.append("")
    lines.append(f"Total: {total_activities} activities, {format_duration(total_minutes)}")
    return lines


def report_categories(start_date, end_date):
    with get_cursor(write=False) as cursor:
        cursor.execute(
            """
            SELECT 
                c.name,
                COUNT(a.id) as activity_count,
                COALESCE(SUM(
                    EXTRACT(EPOCH FROM (a.end_time - a.start_time)) / 60
                ), 0)::INTEGER as total_minutes
            FROM categories c
            LEFT JOIN activities a ON c.id = a.category_id 
                AND DATE(a.start_time) >= %s 
                AND DATE(a.start_time) <= %s
            GROUP BY c.id, c.name
            HAVING COUNT(a.id) > 0
            ORDER BY total_minutes DESC
            """,
            (start_date, end_date),
        )
        rows = cursor.fetchall()
    
    if not rows:
        return [f"No data between {start_date} and {end_date}"]
    
    formatted = []
    total_minutes = sum(r[2] for r in rows)
    
    for name, count, minutes in rows:
        pct = (minutes / total_minutes * 100) if total_minutes > 0 else 0
        formatted.append((
            name,
            count,
            format_duration(minutes),
            f"{pct:.1f}%",
        ))
    
    lines = [f"Time by Category: {start_date} to {end_date}", ""]
    lines.extend(format_table(["Category", "Activities", "Duration", "% of Total"], formatted))
    lines.append("")
    lines.append(f"Total: {format_duration(total_minutes)}")
    return lines


def report_tags(start_date, end_date):
    with get_cursor(write=False) as cursor:
        cursor.execute(
            """
            SELECT 
                c.name as category_name,
                t.name as tag_name,
                COUNT(DISTINCT a.id) as activity_count,
                COALESCE(SUM(
                    EXTRACT(EPOCH FROM (a.end_time - a.start_time)) / 60
                ), 0)::INTEGER as total_minutes
            FROM tags t
            JOIN categories c ON t.category_id = c.id
            LEFT JOIN activity_tags at ON t.id = at.tag_id
            LEFT JOIN activities a ON at.activity_id = a.id 
                AND DATE(a.start_time) >= %s 
                AND DATE(a.start_time) <= %s
            GROUP BY c.id, c.name, t.id, t.name
            HAVING COUNT(a.id) > 0
            ORDER BY c.name, total_minutes DESC
            """,
            (start_date, end_date),
        )
        rows = cursor.fetchall()
    
    if not rows:
        return [f"No tagged activities between {start_date} and {end_date}"]
    
    formatted = []
    for cat_name, tag_name, count, minutes in rows:
        formatted.append((
            cat_name,
            tag_name,
            count,
            format_duration(minutes),
        ))
    
    lines = [f"Time by Tag: {start_date} to {end_date}", ""]
    lines.extend(format_table(["Category", "Tag", "Activities", "Duration"], formatted))
    return lines