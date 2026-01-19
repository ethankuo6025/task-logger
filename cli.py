from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.shortcuts import clear as clear_screen
import shutil
import re
from datetime import datetime, date, timedelta

from db import setup_database
from query_scripts import (
    log_activity, update_activity, update_activity_tags, update_activity_category,
    delete_activity, get_activity, get_activities_by_date, get_activities_in_range,
    get_recent_activities, get_all_categories, get_or_create_category,
    get_tags_for_category, get_or_create_tag, rename_category, delete_category,
    rename_tag, delete_tag, update_category_color, report_daily, report_categories, 
    report_tags
)
from display import (
    format_duration, format_time, format_activities_table, print_help,
    format_categories_list, display_color_samples, get_color_samples, print_colored,
    format_table, format_date_short
)

MAX_UI_HEIGHT = 30
COMMANDS = ["log", "edit", "delete", "view", "report", "manage", "help"]

ui_state = []
cmd_session = None
form_session = None

class AbortInput(Exception):
    pass

kb = KeyBindings()
kb.add("c-z")(lambda event: event.app.exit(exception=AbortInput()))

def header_line():
    return "═" * shutil.get_terminal_size(fallback=(80, 24))[0]

def reset_ui():
    global ui_state
    ui_state = []

def add_ui(*lines):
    for line in lines:
        ui_state.extend(line if isinstance(line, list) else [str(line)])

def render():
    clear_screen()
    rows = shutil.get_terminal_size(fallback=(80, 24))[1]
    visible = ui_state[-min(len(ui_state), min(MAX_UI_HEIGHT, max(5, rows - 5))):]
    
    print(header_line())
    print("  TASK LOGGER  │  'help' for commands  │  Ctrl+Z cancel  │  Ctrl+C exit")
    print(header_line())
    for line in visible:
        print(line)
    print(header_line())

def parse_time_string(time_str, base_date):
    """Parse time string (e.g., 9:30, 9:30am, 2:00pm) into datetime."""
    match = re.match(r'^(\d{1,2}):(\d{2})\s*(am|pm)?$', time_str.strip().lower())
    if not match:
        return None
    
    hour, minute, period = int(match.group(1)), int(match.group(2)), match.group(3)
    
    if not (0 <= minute <= 59 and 0 <= hour <= 23):
        return None
    
    if period == 'pm' and hour != 12:
        hour += 12
    elif period == 'am' and hour == 12:
        hour = 0
    
    if hour > 23:
        return None
    
    return datetime.combine(base_date, datetime.strptime(f"{hour:02d}:{minute:02d}", "%H:%M").time())

def format_time_prompt(dt):
    return dt.strftime("%I:%M%p").lstrip("0").lower() if dt else ""

def prompt_str(prompt_text, required=True, default=None):
    prompt_text = f"{prompt_text} [{default}]: " if default else f"{prompt_text}: "
    while True:
        val = form_session.prompt(prompt_text).strip()
        if val:
            return val
        if default:
            return default
        if not required:
            return None
        print("  This field is required.")

def prompt_time(prompt_text, base_date, default=None, required=True):
    prompt_text = f"{prompt_text} [{format_time_prompt(default)}]: " if default else f"{prompt_text}: "
    
    while True:
        val = form_session.prompt(prompt_text).strip()
        
        if not val:
            if default and isinstance(default, datetime):
                return default
            if not required:
                return None
            print("  This field is required.")
            continue
        
        parsed = parse_time_string(val, base_date)
        if parsed:
            return parsed
        print("  Invalid time. Use format like: 9:30, 9:30am, 2:00pm")

def prompt_yes_no(prompt_text, default=False):
    hint = "[Y/n]" if default else "[y/N]"
    val = form_session.prompt(f"{prompt_text} {hint}: ").strip().lower()
    return val in ("y", "yes") if val else default

def prompt_from_list(items, prompt_text, display_fn, allow_create=False, create_hint=""):
    """Generic prompt to select from a list or create new."""
    print(f"\n  {prompt_text}:")
    if items:
        for i, item in enumerate(items, 1):
            print(f"    {i}. {display_fn(item)}")
    else:
        print("    (none yet)")
    
    if allow_create:
        print(f"  Enter number for existing, or type new name to create.{create_hint}")
    
    return items

def prompt_category():
    """Prompt for category selection or creation. Returns category_id."""
    categories = prompt_from_list(
        get_all_categories(), "Categories",
        lambda c: print_colored(c[1], c[2]) if c[2] else c[1], 
        allow_create=True
    )
    
    while True:
        val = form_session.prompt("  Category: ").strip()
        if not val:
            print("  Category is required.")
            continue
        
        if val.isdigit():
            idx = int(val)
            if 1 <= idx <= len(categories):
                return categories[idx - 1][0]
            print(f"    Invalid number: {idx}")
            continue
        
        category_id = get_or_create_category(val)
        if not any(c[1].lower() == val.lower() for c in categories):
            print(f"    Created new category: '{val}'")
        return category_id

def prompt_tags_for_category(category_id):
    """Prompt for tags within a specific category. Returns list of tag IDs."""
    existing_tags = get_tags_for_category(category_id)
    
    print("\n  Tags for this category:")
    if existing_tags:
        for i, (id, name) in enumerate(existing_tags, 1):
            print(f"    {i}. {name}")
    else:
        print("    (no tags yet)")
    print("  Enter numbers for existing, or type new names to create.")
    print("  Separate multiple with commas. Press Enter to skip.")
    
    val = form_session.prompt("  Tags: ").strip()
    if not val:
        return []
    
    tag_ids = []
    for part in (p.strip() for p in val.split(",") if p.strip()):
        if part.isdigit():
            idx = int(part)
            if 1 <= idx <= len(existing_tags):
                tag_ids.append(existing_tags[idx - 1][0])
            else:
                print(f"    Invalid number: {idx}")
        else:
            tag_id = get_or_create_tag(category_id, part)
            tag_ids.append(tag_id)
            if not any(t[1].lower() == part.lower() for t in existing_tags):
                print(f"    Created new tag: '{part}'")
    
    return tag_ids

def prompt_date(prompt_text, default=None, required=True):
    hint = "(YYYY-MM-DD, 'today', 'yesterday', '-N')"
    default_str = str(default) if isinstance(default, date) else default
    prompt_text = f"{prompt_text} {hint} [{default_str}]: " if default else f"{prompt_text} {hint}: "
    
    while True:
        val = form_session.prompt(prompt_text).strip().lower()
        
        if not val:
            if default:
                return default if isinstance(default, date) else date.fromisoformat(default)
            if not required:
                return None
            print("  This field is required.")
            continue
        
        if val in ("today", "t"):
            return date.today()
        if val in ("yesterday", "y"):
            return date.today() - timedelta(days=1)
        if re.match(r'^-\d+$', val):
            days = int(val[1:])
            if days == 0:
                return date.today()
            return date.today() - timedelta(days=days)
        
        try:
            return date.fromisoformat(val)
        except ValueError:
            print("  Invalid date. Use YYYY-MM-DD, 'today', 'yesterday', or '-N'.")

def prompt_date_range(start_prompt="Start date", end_prompt="End date", default_start=None, default_end=None):
    """Prompt for a date range, ensuring end >= start."""
    start = prompt_date(start_prompt, default=default_start)
    
    while True:
        end = prompt_date(end_prompt, default=default_end or start)
        if end >= start:
            return start, end
        print(f"  End date must be on or after {start}.")

def prompt_int(prompt_text, default=None, min_val=None, max_val=None):
    prompt_text = f"{prompt_text} [{default}]: " if default is not None else f"{prompt_text}: "
    while True:
        val = form_session.prompt(prompt_text).strip()
        if not val and default is not None:
            return default
        try:
            n = int(val)
            if min_val is not None and n < min_val:
                print(f"  Must be at least {min_val}.")
                continue
            if max_val is not None and n > max_val:
                print(f"  Must be at most {max_val}.")
                continue
            return n
        except ValueError:
            print("  Enter a number.")

def prompt_select_activity(target_date=None, prompt_text="Select activity"):
    """Let user select from a list of activities. Returns activity tuple or None if cancelled."""
    activities = get_activities_by_date(target_date) if target_date else get_recent_activities(20)
    
    if not activities:
        return None, "empty"
    
    print(f"\n  {prompt_text}:")
    for i, row in enumerate(activities, 1):
        id, start, end, desc = row[0], row[1], row[2], row[3]
        color = row[7] if len(row) > 7 else None
        line = f"    {i}. {start.strftime('%m/%d')} {format_time(start)}-{format_time(end)} | {desc[:30]}"
        if color:
            line = print_colored(line, color)
        print(line)
    
    while True:
        val = form_session.prompt("  Enter number (or 'c' to cancel): ").strip()
        if val.lower() == 'c':
            return None, "cancelled"
        try:
            n = int(val)
            if 1 <= n <= len(activities):
                return activities[n - 1], "selected"
            print(f"  Enter a number between 1 and {len(activities)}.")
        except ValueError:
            print("  Enter a number.")

def prompt_color():
    """Prompt for hex color with presets."""
    for line in display_color_samples():
        print(line)
    print("  Or enter 'none' to clear color")
    
    while True:
        val = form_session.prompt("  Color: ").strip().lower()
        
        if not val:
            return None
        
        if val == "none":
            return None
        
        # Check presets
        presets = get_color_samples()
        if val in presets:
            return presets[val]
        
        # Validate hex format
        if re.match(r'^#[0-9A-Fa-f]{6}$', val):
            return val
        
        print("  Invalid color. Use preset name, #RRGGBB format, or 'none'.")

def cmd_log():
    """Log activities with chaining support."""
    print("\n── Log Activities ──")
    
    all_results = []
    activity_date = prompt_date("Date", default=date.today())
    start_time = prompt_time("Start time (e.g. 9:00am)", activity_date)
    
    while True:
        # Get end time (must be after start)
        while True:
            end_time = prompt_time("End time", activity_date)
            if end_time > start_time:
                break
            print(f"  End time must be after {format_time_prompt(start_time)}")
        
        category_id = prompt_category()
        if category_id is None:
            return ["Cancelled - category is required."]
        
        tag_ids = prompt_tags_for_category(category_id)
        notes = prompt_str("Notes", required=False)
        
        try:
            activity_id, duration = log_activity(start_time, end_time, category_id, tag_ids, notes)
            result = ["", f"Logged: {format_time_prompt(start_time)} - {format_time_prompt(end_time)} ({format_duration(duration)})", f"  ID: {activity_id}"]
            all_results.extend(result)
            for line in result:
                print(line)
        except ValueError as e:
            print("\n  ✗ Cannot log: overlaps with existing activities:")
            for ov_id, ov_start, ov_end in e.args[0]:
                print(f"    [{ov_id}] {format_time(ov_start)} - {format_time(ov_end)}")
            if prompt_yes_no("\nTry different times?", default=True):
                continue
            break
        
        print("")
        if not prompt_yes_no(f"Log next activity starting at {format_time_prompt(end_time)}?", default=False):
            break
        
        print(f"\n── Next Activity (from {format_time_prompt(end_time)}) ──")
        start_time = end_time
    
    return all_results if all_results else ["No activities logged."]

def cmd_edit():
    """Edit an existing activity."""
    print("\n── Edit Activity ──")
    
    target_date = prompt_date("Date of task to edit", required=True)
    activity, status = prompt_select_activity(target_date)
    
    if status == "empty":
        return ["No activities found for that date."]
    if status == "cancelled":
        return ["Cancelled."]
    
    # Handle both 7 and 8-tuple formats
    activity_id = activity[0]
    start_dt = activity[1]
    end_dt = activity[2]
    category = activity[3]
    tags = activity[5]
    notes = activity[6]
    
    activity_details = get_activity(activity_id)
    
    print(f"\n  Current values:")
    print(f"    Time: {format_time(start_dt)} - {format_time(end_dt)}")
    print(f"    Category: {category}")
    print(f"    Tags: {tags or '(none)'}")
    print(f"    Notes: {notes or '(none)'}")
    print("\n  Press Enter to keep current value.\n")
    
    current_date = start_dt.date()
    new_date = prompt_date("Date", default=current_date, required=False) or current_date
    new_start = prompt_time("Start time", new_date, default=start_dt, required=False)
    new_start = new_start or datetime.combine(new_date, start_dt.time())
    
    while True:
        new_end = prompt_time("End time", new_date, default=end_dt, required=False)
        new_end = new_end or datetime.combine(new_date, end_dt.time())
        if new_end > new_start:
            break
        print("  End time must be after start time.")
    
    if prompt_yes_no("Update category?", default=False):
        update_activity_category(activity_id, prompt_category())
        if prompt_yes_no("Update tags?", default=False):
            activity_details = get_activity(activity_id)
            update_activity_tags(activity_id, prompt_tags_for_category(activity_details['category_id']))
    elif prompt_yes_no("Update tags?", default=False):
        activity_details = get_activity(activity_id)
        update_activity_tags(activity_id, prompt_tags_for_category(activity_details['category_id']))
    
    new_notes = prompt_str("Notes", required=False, default=notes or "")
    
    update_activity(
        activity_id,
        start_time=new_start if new_start != start_dt else None,
        end_time=new_end if new_end != end_dt else None,
        notes=new_notes if new_notes != notes else None,
    )
    
    return ["Successfully updated activity"]

def cmd_delete():
    """Delete an activity."""
    print("\n── Delete Activity ──")
    
    target_date = prompt_date("Date of activity to delete", required=True)
    activity, status = prompt_select_activity(target_date, "Select activity to delete")
    
    if status == "empty":
        return ["No activities found for that date."]
    if status == "cancelled":
        return ["Cancelled."]
    
    activity_details = get_activity(activity[0])
    if not activity_details:
        return [f"Activity {activity[0]} not found."]
    
    print(f"\n  About to delete:")
    print(f"    Date: {activity_details['start_time'].date()}")
    print(f"    Time: {format_time(activity_details['start_time'])} - {format_time(activity_details['end_time'])}")
    print(f"    Category: {activity_details['category_name']}")
    if activity_details['tags']:
        print(f"    Tags: {activity_details['tags']}")
    if activity_details['notes']:
        print(f"    Notes: {activity_details['notes']}")
    
    if not prompt_yes_no("Are you sure?", default=False):
        return ["Cancelled."]
    
    result = delete_activity(activity[0])
    return [f"Deleted activity from {activity_details['start_time'].date()}"] if result else ["Failed to delete activity."]

def cmd_view():
    """Unified view command."""
    print("\n── View Activities ──")
    print("  Enter: date, t/today, y/yesterday, -N (N days ago),")
    print("         w (this week), w-N (N weeks ago), r/range (date range)")
    
    val = form_session.prompt("  View: ").strip().lower()
    today = date.today()
    
    # Empty or today
    if not val or val in ("t", "today"):
        rows = get_activities_by_date(today)
        return [f"Activities for {today} (today)", ""] + format_activities_table(rows, show_date=False)
    
    # yesterday
    if val in ("y", "yesterday"):
        yesterday = today - timedelta(days=1)
        rows = get_activities_by_date(yesterday)
        return [f"Activities for {yesterday} (yesterday)", ""] + format_activities_table(rows, show_date=False)
    
    # -N days ago
    if re.match(r'^-\d+$', val):
        days = int(val[1:])
        target = today - timedelta(days=days) if days > 0 else today
        rows = get_activities_by_date(target)
        return [f"Activities for {target}", ""] + format_activities_table(rows, show_date=False)
    
    # this week
    if val == "w":
        start_of_week = today - timedelta(days=today.weekday())
        rows = get_activities_in_range(start_of_week, today)
        return [f"Activities for {start_of_week} to {today} (this week)", ""] + format_activities_table(rows, show_date=True)
    
    # N weeks ago
    week_match = re.match(r'^w\s*-?\s*(\d+)$', val)
    if week_match:
        weeks_ago = int(week_match.group(1))
        if weeks_ago == 0:
            start_of_week = today - timedelta(days=today.weekday())
            rows = get_activities_in_range(start_of_week, today)
            return [f"Activities for {start_of_week} to {today} (this week)", ""] + format_activities_table(rows, show_date=True)
        
        start_of_this_week = today - timedelta(days=today.weekday())
        start_of_target_week = start_of_this_week - timedelta(weeks=weeks_ago)
        end_of_target_week = start_of_target_week + timedelta(days=6)
        rows = get_activities_in_range(start_of_target_week, end_of_target_week)
        week_label = "last week" if weeks_ago == 1 else f"{weeks_ago} weeks ago"
        return [f"Activities for {start_of_target_week} to {end_of_target_week} ({week_label})", ""] + format_activities_table(rows, show_date=True)
    
    # range
    if val in ("r", "range"):
        start, end = prompt_date_range("Start date", "End date", default_end=today)
        rows = get_activities_in_range(start, end)
        return [f"Activities for {start} to {end}", ""] + format_activities_table(rows, show_date=True)
    
    # try to parse as a date
    try:
        target = date.fromisoformat(val)
        rows = get_activities_by_date(target)
        return [f"Activities for {target}", ""] + format_activities_table(rows, show_date=False)
    except ValueError:
        pass
    
    return ["Invalid input. Use: date, t/today, y/yesterday, -N, w, w-N, r/range"]

def cmd_report():
    """Generate reports."""
    print("\n── Generate Report ──")
    print("  Options:")
    print("    1. daily    - Daily summary")
    print("    2. category - Time by category")
    print("    3. tag      - Time by tag")
    
    choice = form_session.prompt("  Select option (1-3): ").strip()
    
    if choice not in ("1", "2", "3", "daily", "category", "tag"):
        return ["Invalid option."]
    
    report_name = {"1": "Daily", "2": "Category", "3": "Tag", "daily": "Daily", "category": "Category", "tag": "Tag"}[choice]
    print(f"\n── {report_name} Report ──")
    
    start, end = prompt_date_range(
        "Start date", "End date",
        default_start=date.today() - timedelta(days=7),
        default_end=date.today()
    )
    
    # Get raw data from query_scripts
    if choice in ("1", "daily"):
        rows = report_daily(start, end)
        if not rows:
            return [f"No data between {start} and {end}"]
        
        total_activities = sum(r[1] for r in rows)
        total_minutes = sum(r[2] for r in rows)
        
        formatted = [(str(d), d.strftime("%a"), count, format_duration(mins)) for d, count, mins in rows]
        
        lines = [f"Daily Summary: {start} to {end}", ""]
        lines.extend(format_table(["Date", "Day", "Activities", "Duration"], formatted))
        lines.extend(["", f"Total: {total_activities} activities, {format_duration(total_minutes)}"])
        return lines
    
    elif choice in ("2", "category"):
        rows = report_categories(start, end)
        if not rows:
            return [f"No data between {start} and {end}"]
        
        total_minutes = sum(r[3] for r in rows)
        formatted = []
        colors = []
        
        for name, color, count, mins in rows:
            pct = f"{mins/total_minutes*100:.1f}%" if total_minutes else "0%"
            formatted.append((name, count, format_duration(mins), pct))
            colors.append(color)
        
        lines = [f"Time by Category: {start} to {end}", ""]
        lines.extend(format_table(["Category", "Activities", "Duration", "% of Total"], formatted, colors))
        lines.extend(["", f"Total: {format_duration(total_minutes)}"])
        return lines
    
    else:  # tag
        rows = report_tags(start, end)
        if not rows:
            return [f"No tagged activities between {start} and {end}"]
        
        formatted = []
        colors = []
        
        for cat, color, tag, count, mins in rows:
            formatted.append((cat, tag, count, format_duration(mins)))
            colors.append(color)
        
        lines = [f"Time by Tag: {start} to {end}", ""]
        lines.extend(format_table(["Category", "Tag", "Activities", "Duration"], formatted, colors))
        return lines

def cmd_manage():
    """Manage categories and tags."""
    print("\n── Manage Categories & Tags ──")
    print("  Options:")
    print("    1. List categories")
    print("    2. Rename category")
    print("    3. Delete category (WARNING: deletes all its activities)")
    print("    4. Change category color")
    print("    5. Manage tags within a category")
    
    choice = form_session.prompt("  Select option (1-5): ").strip()
    categories = get_all_categories()
    
    if choice == "1":
        if not categories:
            return ["No categories yet."]
        lines = ["Categories:"]
        for id, name, color in categories:
            tags = get_tags_for_category(id)
            tags_str = f" (tags: {', '.join(t[1] for t in tags)})" if tags else ""
            color_str = f" [{color}]" if color else ""
            line = f"  [{id}] {name}{color_str}{tags_str}"
            if color:
                line = print_colored(line, color)
            lines.append(line)
        return lines
    
    if choice in ("2", "3", "4"):
        if not categories:
            return ["No categories to modify."]
        
        action_name = {"2": "rename", "3": "delete", "4": "change color of"}[choice]
        print(f"\n  Select category to {action_name}:")
        for i, (id, name, color) in enumerate(categories, 1):
            line = f"    {i}. {name}"
            if color:
                line = print_colored(line, color)
            print(line)
        
        idx = prompt_int("Category number", min_val=1, max_val=len(categories))
        category_id, cat_name, old_color = categories[idx - 1]
        
        if choice == "2":
            return rename_category(category_id, prompt_str("New name"))
        elif choice == "3":
            print(f"\n  WARNING: This will delete category '{cat_name}' and ALL its activities!")
            return delete_category(category_id) if prompt_yes_no("Are you sure?", default=False) else ["Cancelled."]
        else:  # choice == "4"
            print(f"\n  Current color: {old_color or 'none'}")
            if old_color:
                print("  Preview: " + print_colored(f"{cat_name}", old_color))
            new_color = prompt_color()
            if update_category_color(category_id, new_color):
                return [f"Updated color for '{cat_name}'" + (f" to {new_color}" if new_color else " (removed)")]
            return ["Failed to update color."]
    
    if choice == "5":
        if not categories:
            return ["No categories yet."]
        
        print("\n  Select category:")
        for i, (id, name, color) in enumerate(categories, 1):
            line = f"    {i}. {name}"
            if color:
                line = print_colored(line, color)
            print(line)
        
        idx = prompt_int("Category number", min_val=1, max_val=len(categories))
        category_id, cat_name, _ = categories[idx - 1]
        
        print(f"\n  Managing tags for category: {cat_name}")
        print("    1. List tags")
        print("    2. Rename tag")
        print("    3. Delete tag")
        
        action = form_session.prompt("  Select action (1-3): ").strip()
        tags = get_tags_for_category(category_id)
        
        if action == "1":
            if not tags:
                return [f"No tags in category '{cat_name}'."]
            return [f"Tags in '{cat_name}':"] + [f"  [{id}] {name}" for id, name in tags]
        
        if action in ("2", "3"):
            if not tags:
                return [f"No tags to modify in '{cat_name}'."]
            
            print(f"\n  Tags in '{cat_name}':")
            for i, (id, name) in enumerate(tags, 1):
                print(f"    {i}. {name}")
            
            idx = prompt_int("Tag number", min_val=1, max_val=len(tags))
            tag_id, tag_name = tags[idx - 1]
            
            if action == "2":
                return rename_tag(tag_id, prompt_str("New name"))
            else:
                return delete_tag(tag_id) if prompt_yes_no(f"Delete tag '{tag_name}'?", default=False) else ["Cancelled."]
        
        return ["Invalid action."]
    
    return ["Invalid option."]

COMMAND_MAP = {
    "help": lambda: [print_help()],
    "log": cmd_log,
    "edit": cmd_edit,
    "delete": cmd_delete,
    "view": cmd_view,
    "report": cmd_report,
    "manage": cmd_manage,
}

def process_command(cmd):
    cmd = cmd.strip().lower()
    if not cmd:
        return []
    
    if cmd in COMMAND_MAP:
        return COMMAND_MAP[cmd]()
    
    matches = [c for c in COMMAND_MAP if c.startswith(cmd)]
    if len(matches) == 1:
        return COMMAND_MAP[matches[0]]()
    if len(matches) > 1:
        return [f"Ambiguous: {', '.join(matches)}"]
    
    return [f"Unknown command: '{cmd}'. Type 'help' for commands."]

def main():
    global cmd_session, form_session
    
    cmd_session = PromptSession(completer=WordCompleter(COMMANDS, ignore_case=True, sentence=True), key_bindings=kb)
    form_session = PromptSession(key_bindings=kb)
    
    print(header_line())
    print("  TASK LOGGER")
    print(header_line())
    print("\nConnecting to database...")
    
    if not setup_database():
        print("Failed to setup database. Check private.py settings.")
        return
    
    print("Connected!\n")
    input("Press Enter to continue...")
    
    reset_ui()
    rows = get_activities_by_date(date.today())
    add_ui([f"Activities for {date.today()} (today)", ""] + format_activities_table(rows, show_date=False))
    render()
    
    while True:
        try:
            result = process_command(cmd_session.prompt("\n> ").strip())
            if result:
                reset_ui()
                add_ui(result)
                render()
        except AbortInput:
            reset_ui()
            add_ui("Cancelled.")
            render()
        except (EOFError, KeyboardInterrupt):
            print("\n\nGoodbye!")
            break

if __name__ == "__main__":
    main()