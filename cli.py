from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.shortcuts import clear as clear_screen
import shutil
import re
from datetime import datetime, date, timedelta

from db import get_cursor, test_connection, setup_database
from query_scripts import (
    # Help
    print_help,
    # Tags
    get_all_tags,
    get_or_create_tag,
    view_tags,
    rename_tag,
    delete_tag,
    # Activities
    log_activity,
    update_activity,
    update_activity_tags,
    update_activity_category,
    delete_activity,
    get_activity,
    get_recent_activities,
    # Views
    view_today,
    view_yesterday,
    view_week,
    view_range,
    view_recent,
    # Reports
    report_daily,
    report_tags,
    # Formatting
    format_duration,
    format_time,
    format_datetime,
    get_all_categories,
    get_or_create_category,
    get_tags_for_category,
    get_activities_by_date
)

# ============================================================
# CONSTANTS
# ============================================================

MAX_UI_HEIGHT = 30

COMMANDS = ["log",
            "edit", 
            "delete",
            "today", 
            "yesterday", 
            "week", 
            "range", 
            "recent",
            "tags", 
            "rename tag", 
            "delete tag",
            "report daily", 
            "report tags",
            "help"]


# ============================================================
# GLOBALS
# ============================================================

ui_state = []
cmd_session = None
form_session = None


class AbortInput(Exception):
    """User cancelled with Ctrl+Z."""
    pass


kb = KeyBindings()


@kb.add("c-z")
def _(event):
    event.app.exit(exception=AbortInput())


# ============================================================
# UI HELPERS
# ============================================================

def header_line():
    cols, _ = shutil.get_terminal_size(fallback=(80, 24))
    return "═" * cols


def reset_ui():
    global ui_state
    ui_state = []


def add_ui(*lines):
    global ui_state
    for line in lines:
        if isinstance(line, list):
            ui_state.extend(line)
        else:
            ui_state.append(str(line))


def render():
    clear_screen()
    _, rows = shutil.get_terminal_size(fallback=(80, 24))
    usable = max(5, rows - 5)
    visible = ui_state[-min(len(ui_state), min(MAX_UI_HEIGHT, usable)):]
    
    print(header_line())
    print("  TASK LOGGER  │  'help' for commands  │  Ctrl+Z cancel  │  Ctrl+C exit")
    print(header_line())
    for line in visible:
        print(line)
    print(header_line())


# ============================================================
# TIME PARSING
# ============================================================

def parse_time_string(time_str, base_date):
    """
    Parse a time string into a datetime.
    
    Supported formats:
    - "9:30" or "09:30" -> 9:30 AM (no am/pm defaults to AM)
    - "9:30am" or "9:30 am" -> 9:30 AM
    - "9:30pm" or "9:30 pm" -> 9:30 PM
    - "12:00pm" -> 12:00 PM (noon)
    - "12:00am" -> 12:00 AM (midnight)
    
    Returns datetime combined with base_date, or None if invalid.
    """
    time_str = time_str.strip().lower()
    
    # Regex to match time with optional am/pm
    # Matches: 9:30, 09:30, 9:30am, 9:30 am, 9:30pm, 9:30 pm
    pattern = r'^(\d{1,2}):(\d{2})\s*(am|pm)?$'
    match = re.match(pattern, time_str)
    
    if not match:
        return None
    
    hour = int(match.group(1))
    minute = int(match.group(2))
    period = match.group(3)  # None, 'am', or 'pm'
    
    # Validate ranges
    if minute < 0 or minute > 59:
        return None
    if hour < 0 or hour > 23:
        return None
    
    # If no am/pm specified, default to AM
    # But handle edge cases for hour > 12
    if period is None:
        if hour > 12:
            # Already in 24-hour format (e.g., "14:30")
            pass
        else:
            # Default to AM (hour stays as-is for 1-12)
            # 12 without am/pm -> 12 PM (noon) assumption? No, default AM means 12:00 = midnight
            # Actually, let's be more intuitive: default to AM
            pass
    elif period == 'pm':
        if hour == 12:
            pass  # 12pm is noon, hour stays 12
        else:
            hour += 12  # 1pm -> 13, 2pm -> 14, etc.
    elif period == 'am':
        if hour == 12:
            hour = 0  # 12am is midnight
    
    # Final validation
    if hour > 23:
        return None
    
    try:
        t = datetime.strptime(f"{hour:02d}:{minute:02d}", "%H:%M").time()
        return datetime.combine(base_date, t)
    except ValueError:
        return None


def format_time_for_prompt(dt):
    """Format a datetime for display in prompts (12-hour format)."""
    if dt is None:
        return ""
    return dt.strftime("%I:%M%p").lstrip("0").lower()


# ============================================================
# INPUT HELPERS
# ============================================================
def prompt_category():
    """Prompt for category selection or creation. Returns category_id."""
    categories = get_all_categories()
    
    print("\n  Categories:")
    if categories:
        for i, (id, name, color) in enumerate(categories, 1):
            print(f"    {i}. {name}")
    else:
        print("    (no categories yet)")
    print("  Enter number for existing, or type new name to create.")
    
    while True:
        val = form_session.prompt("  Category: ").strip()
        if not val:
            print("  Category is required.")
            continue
        
        # Check if it's a number (index into existing categories)
        if val.isdigit():
            idx = int(val)
            if 1 <= idx <= len(categories):
                return categories[idx - 1][0]
            print(f"    Invalid number: {idx}")
            continue
        
        # It's a category name - get or create
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
    parts = [p.strip() for p in val.split(",")]
    
    for part in parts:
        if not part:
            continue
        
        if part.isdigit():
            idx = int(part)
            if 1 <= idx <= len(existing_tags):
                tag_ids.append(existing_tags[idx - 1][0])
            else:
                print(f"    Invalid number: {idx}")
        else:
            # Create tag under this category
            tag_id = get_or_create_tag(category_id, part)
            tag_ids.append(tag_id)
            if not any(t[1].lower() == part.lower() for t in existing_tags):
                print(f"    Created new tag: '{part}'")
    
    return tag_ids

def prompt_str(prompt_text, required=True, default=None):
    """Prompt for string input."""
    if default:
        prompt_text = f"{prompt_text} [{default}]: "
    else:
        prompt_text = f"{prompt_text}: "
    
    while True:
        val = form_session.prompt(prompt_text).strip()
        if not val:
            if default:
                return default
            if not required:
                return None
            print("  This field is required.")
            continue
        return val


def prompt_date(prompt_text, default=None, required=True):
    """
    Prompt for date. Accepts:
    - YYYY-MM-DD
    - 'today' or 't'
    - 'yesterday' or 'y'
    - '-N' for N days ago
    """
    hint = "(YYYY-MM-DD, 'today', 'yesterday', '-N')"
    if default:
        default_str = str(default) if isinstance(default, date) else default
        prompt_text = f"{prompt_text} {hint} [{default_str}]: "
    else:
        prompt_text = f"{prompt_text} {hint}: "
    
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
        if val.startswith("-") and val[1:].isdigit():
            return date.today() - timedelta(days=int(val[1:]))
        
        try:
            return date.fromisoformat(val)
        except ValueError:
            print("  Invalid date. Use YYYY-MM-DD, 'today', 'yesterday', or '-N'.")


def prompt_time(prompt_text, base_date, default=None, required=True):
    """
    Prompt for time in 12-hour format.
    
    Accepts: 9:30, 9:30am, 9:30pm, 9:30 am, 9:30 pm
    Defaults to AM if not specified.
    """
    if default:
        default_str = format_time_for_prompt(default)
        prompt_text = f"{prompt_text} [{default_str}]: "
    else:
        prompt_text = f"{prompt_text}: "
    
    while True:
        val = form_session.prompt(prompt_text).strip()
        
        if not val:
            if default:
                if isinstance(default, datetime):
                    return default
                # Shouldn't happen, but handle string default
                parsed = parse_time_string(default, base_date)
                if parsed:
                    return parsed
            if not required:
                return None
            print("  This field is required.")
            continue
        
        parsed = parse_time_string(val, base_date)
        if parsed:
            return parsed
        
        print("  Invalid time. Use format like: 9:30, 9:30am, 2:00pm")


def prompt_int(prompt_text, default=None, min_val=None):
    """Prompt for integer."""
    if default:
        prompt_text = f"{prompt_text} [{default}]: "
    else:
        prompt_text = f"{prompt_text}: "
    
    while True:
        val = form_session.prompt(prompt_text).strip()
        if not val and default is not None:
            return default
        try:
            n = int(val)
            if min_val is not None and n < min_val:
                print(f"  Must be at least {min_val}.")
                continue
            return n
        except ValueError:
            print("  Enter a number.")


def prompt_yes_no(prompt_text, default=False):
    """Prompt for yes/no."""
    hint = "[Y/n]" if default else "[y/N]"
    val = form_session.prompt(f"{prompt_text} {hint}: ").strip().lower()
    if not val:
        return default
    return val in ("y", "yes")


def prompt_tags():
    """
    Prompt for tags. User can:
    - Select existing tags by number
    - Type new tag names to create them
    - Mix both
    Returns list of tag IDs.
    """
    existing_tags = get_all_tags()
    
    print("\n  Available tags:")
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
    parts = [p.strip() for p in val.split(",")]
    
    for part in parts:
        if not part:
            continue
        
        # Check if it's a number (index into existing tags)
        if part.isdigit():
            idx = int(part)
            if 1 <= idx <= len(existing_tags):
                tag_ids.append(existing_tags[idx - 1][0])
            else:
                print(f"    Invalid number: {idx}")
        else:
            # It's a tag name - get or create
            tag_id = get_or_create_tag(part)
            tag_ids.append(tag_id)
            # Check if it was newly created
            if not any(t[1].lower() == part.lower() for t in existing_tags):
                print(f"    Created new tag: '{part}'")
    
    return tag_ids


def prompt_select_activity(date=None, prompt_text="Select activity"):
    """
    Let user select from a list of activities.
    Returns activity ID or None.
    """
    if date is None:
        activities = get_recent_activities(20)
    else:
        activities = get_activities_by_date(date)
    
    if not activities:
        print("  No activities found.")
        return None
    
    print(f"\n  {prompt_text}:")
    for i, (id, start, end, desc, dur, tags, notes) in enumerate(activities, 1):
        date_str = start.strftime("%m/%d")
        time_range = f"{format_time(start)}-{format_time(end)}"
        print(f"    {i}. {date_str} {time_range} | {desc[:30]}")
    
    while True:
        val = form_session.prompt("  Enter number (or 'c' to cancel): ").strip()
        
        if val.lower() == 'c':
            return None
        
        try:
            n = int(val)
            if 1 <= n <= len(activities):
                return activities[n - 1]
            print("  Invalid selection.")
        except ValueError:
            print("  Enter a number.")


def prompt_select_tag():
    """Let user select a tag. Returns tag ID or None."""
    tags = get_all_tags()
    if not tags:
        print("  No tags found.")
        return None
    
    print("\n  Select tag:")
    for i, (id, name) in enumerate(tags, 1):
        print(f"    {i}. [{id}] {name}")
    
    while True:
        val = form_session.prompt("  Enter number or ID: ").strip()
        try:
            n = int(val)
            if 1 <= n <= len(tags):
                return tags[n - 1][0]
            for t in tags:
                if t[0] == n:
                    return n
            print("  Invalid selection.")
        except ValueError:
            print("  Enter a number.")


# ============================================================
# COMMAND HANDLERS
# ============================================================

def cmd_log():
    """
    Log activities with chaining support.
    """
    print("\n── Log Activities ──")
    
    all_results = []
    
    # Get date and initial start time once
    activity_date = prompt_date("Date", default=date.today())
    start_time = prompt_time("Start time (e.g. 9:00am)", activity_date)
    
    # Chain logging loop
    while True:
        # Get end time
        while True:
            end_time = prompt_time("End time", activity_date)
            if end_time <= start_time:
                print(f"  End time must be after {format_time_for_prompt(start_time)}")
                continue
            break
        
        # Get category (required)
        category_id = prompt_category()
        if category_id is None:
            return ["Cancelled - category is required."]
        
        # Get tags (optional, filtered by category)
        tag_ids = prompt_tags_for_category(category_id)
        
        # Get notes
        notes = prompt_str("Notes", required=False)
        
        # Try to save the activity
        try:
            activity_id, duration = log_activity(
                start_time=start_time,
                end_time=end_time,
                category_id=category_id,  # <-- ADD THIS
                tag_ids=tag_ids,
                notes=notes,
            )
            
            # Get tag names for display
            tags_display = ""
            if tag_ids:
                all_tags = get_all_tags()
                tag_names = [t[1] for t in all_tags if t[0] in tag_ids]
                tags_display = f" [{', '.join(tag_names)}]"
            
            result = [
                "",
                f"Logged: {format_time_for_prompt(start_time)} - {format_time_for_prompt(end_time)} ({format_duration(duration)}){tags_display}",
                f"  ID: {activity_id}",
            ]
            all_results.extend(result)
            
            for line in result:
                print(line)
            
        except ValueError as e:
            # Overlap detected
            overlaps = e.args[0]
            print("\n  ✗ Cannot log: overlaps with existing activities:")
            for ov_id, ov_start, ov_end in overlaps:
                print(f"    [{ov_id}] {format_time(ov_start)} - {format_time(ov_end)}")
            print("")
            
            retry = prompt_yes_no("Try different times?", default=True)
            if retry:
                continue
            else:
                break
        
        # Ask about chaining - that's it, no date change question
        print("")
        chain = prompt_yes_no(
            f"Log next activity starting at {format_time_for_prompt(end_time)}?",
            default=False
        )
        
        if not chain:
            break
        
        # Chain: previous end time becomes new start time
        print(f"\n── Next Activity (from {format_time_for_prompt(end_time)}) ──")
        start_time = end_time
    
    return all_results if all_results else ["No activities logged."]


def cmd_edit():
    """Edit an existing activity."""
    print("\n── Edit Activity ──")
    
    date = prompt_date("Date of task to edit: ", required=True)

    activity = prompt_select_activity(date=date)

    activity_id, start_date, end_date, category, tags, _, notes = activity
    print(f"\n  Current values:")
    print(f"    Time: {format_time(start_date)} - {format_time(end_date)}")
    print(f"    Category: {category}")
    print(f"    Tags: {tags or '(none)'}")
    print(f"    Notes: {notes or '(none)'}")
    print("\n  Press Enter to keep current value.\n")
    
    # Edit fields    
    # Date
    current_date = start_date.date()
    new_date = prompt_date("Date", default=current_date, required=False)

    if new_date is None:
        new_date = current_date
    
    # Start time
    new_start = prompt_time(
        "Start time",
        new_date,
        default=start_date,
        required=False
    )
    if new_start is None:
        new_start = datetime.combine(new_date, start_date.time())
    
    # End time
    while True:
        new_end = prompt_time(
            "End time",
            new_date,
            default=end_date,
            required=False
        )
        if new_end is None:
            new_end = datetime.combine(new_date, end_date.time())
        if new_end <= new_start:
            print("  End time must be after start time.")
            continue
        break
    
    if prompt_yes_no("Update category?", default=False):
        new_category = prompt_category()
        update_activity_category(activity_id=activity_id, new_category_id=new_category)

    # Tags
    if prompt_yes_no("Update tags?", default=False):
        new_tag_ids = prompt_tags()
        update_activity_tags(activity_id, new_tag_ids)
    
    # Notes
    new_notes = prompt_str("Notes", required=False, default=notes or "")
    
    # Apply updates
    update_activity(
        activity_id,
        start_time=new_start if new_start != start_date else None,
        end_time=new_end if new_end != end_date else None,
        notes=new_notes if new_notes != notes else None,
    )
    
    return [f"Successfully updated activity"]


def cmd_delete():
    """Delete an activity."""
    print("\n── Delete Activity ──")
    
    # First prompt for date to narrow down the selection
    date_to_check = prompt_date("Date of activity to delete", required=True)
    
    # Show activities from that date
    activity = prompt_select_activity(date=date_to_check, prompt_text="Select activity to delete")
    
    if activity is None:
        return ["Cancelled."]
    
    # Extract just the ID from the returned activity tuple
    activity_id = activity[0]
    
    # Get full activity details for confirmation
    activity_details = get_activity(activity_id)
    if not activity_details:
        return [f"Activity {activity_id} not found."]
    
    # Show what will be deleted
    print(f"\n  About to delete:")
    print(f"    Date: {activity_details['start_time'].date()}")
    print(f"    Time: {format_time(activity_details['start_time'])} - {format_time(activity_details['end_time'])}")
    print(f"    Category: {activity_details['category_name']}")
    if activity_details['tags']:
        print(f"    Tags: {activity_details['tags']}")
    if activity_details['notes']:
        print(f"    Notes: {activity_details['notes']}")
    
    # Confirm deletion
    if not prompt_yes_no("Are you sure?", default=False):
        return ["Cancelled."]
    
    # Perform deletion
    desc = delete_activity(activity_id)
    if desc:
        return [f"Deleted activity from {activity_details['start_time'].date()}"]
    else:
        return ["Failed to delete activity."]


def cmd_rename_tag():
    """Rename a tag."""
    print("\n── Rename Tag ──")
    
    tag_id = prompt_select_tag()
    if tag_id is None:
        return ["No tags to rename."]
    
    new_name = prompt_str("New name")
    return rename_tag(tag_id, new_name)


def cmd_delete_tag():
    """Delete a tag."""
    print("\n── Delete Tag ──")
    
    tag_id = prompt_select_tag()
    if tag_id is None:
        return ["No tags to delete."]
    
    if not prompt_yes_no("Are you sure?", default=False):
        return ["Cancelled."]
    
    return delete_tag(tag_id)


def cmd_range():
    """View activities in date range."""
    print("\n── View Date Range ──")
    start = prompt_date("Start date")
    end = prompt_date("End date", default=start)
    return view_range(start, end)


def cmd_recent():
    """View recent activities."""
    n = prompt_int("How many?", default=10, min_val=1)
    return view_recent(n)


def cmd_report_daily():
    """Generate daily report."""
    print("\n── Daily Report ──")
    start = prompt_date("Start date", default=date.today() - timedelta(days=7))
    end = prompt_date("End date", default=date.today())
    return report_daily(start, end)


def cmd_report_tags():
    """Generate tag report."""
    print("\n── Tag Report ──")
    start = prompt_date("Start date", default=date.today() - timedelta(days=7))
    end = prompt_date("End date", default=date.today())
    return report_tags(start, end)

# ============================================================
# COMMAND DISPATCH
# ============================================================

COMMAND_MAP = {"help": lambda: [print_help()],
               "log": cmd_log,
               "edit": cmd_edit,
               "delete": cmd_delete,
               "today": view_today,
               "yesterday": view_yesterday,
               "week": view_week,
               "range": cmd_range,
               "recent": cmd_recent,
               "tags": view_tags,
               "rename tag": cmd_rename_tag,
               "delete tag": cmd_delete_tag,
               "report daily": cmd_report_daily,
               "report tags": cmd_report_tags,
}


def process_command(cmd):
    """Process a command and return output lines."""
    cmd = cmd.strip().lower()
    
    if not cmd:
        return []
    
    # Exact match
    if cmd in COMMAND_MAP:
        return COMMAND_MAP[cmd]()
    
    # Prefix match
    matches = [c for c in COMMAND_MAP.keys() if c.startswith(cmd)]
    if len(matches) == 1:
        return COMMAND_MAP[matches[0]]()
    elif len(matches) > 1:
        return [f"Ambiguous: {', '.join(matches)}"]
    
    return [f"Unknown command: '{cmd}'. Type 'help' for commands."]


# ============================================================
# MAIN
# ============================================================

def main():
    global cmd_session, form_session
    
    completer = WordCompleter(COMMANDS, ignore_case=True, sentence=True)
    cmd_session = PromptSession(completer=completer, key_bindings=kb)
    form_session = PromptSession(key_bindings=kb)
    
    print(header_line())
    print("  TASK LOGGER")
    print(header_line())
    print("\nConnecting to database...")
    
    # Always run setup - it handles both creation and schema updates
    if not setup_database():
        print("Failed to setup database. Check private.py settings.")
        return
    
    print("Connected!\n")
    input("Press Enter to continue...")
    
    reset_ui()
    add_ui(view_today())
    render()
    
    while True:
        try:
            cmd = cmd_session.prompt("\n> ").strip()
            result = process_command(cmd)
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