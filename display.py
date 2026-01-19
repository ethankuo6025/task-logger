import shutil
from datetime import datetime, date

# ANSI color codes
RESET = "\033[0m"
BOLD = "\033[1m"

def hex_to_ansi(hex_color):
    """Convert hex color (#RRGGBB) to ANSI 24-bit color code."""
    if not hex_color or not hex_color.startswith('#'):
        return ""
    
    try:
        hex_color = hex_color.lstrip('#')
        r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
        return f"\033[38;2;{r};{g};{b}m"
    except (ValueError, IndexError):
        return ""

def print_colored(text, hex_color=None, bold=False):
    """Print text with optional color and bold."""
    output = ""
    if bold:
        output += BOLD
    if hex_color:
        output += hex_to_ansi(hex_color)
    output += text
    if hex_color or bold:
        output += RESET
    return output

def format_duration(minutes):
    """Format minutes as 'Xh Ym' or 'Ym'."""
    if not minutes:
        return "0m"
    hours, mins = divmod(minutes, 60)
    return f"{hours}h {mins}m" if hours else f"{mins}m"

def format_time(ts):
    """Format timestamp as '9:30am'."""
    return ts.strftime("%I:%M%p").lstrip("0").lower() if isinstance(ts, datetime) else (str(ts) if ts else "")

def format_date_short(ts):
    """Format date as 'MM/DD'."""
    return ts.strftime("%m/%d") if isinstance(ts, (datetime, date)) else (str(ts) if ts else "")

def format_table(headers, rows, colors=None):
    """
    Format data as ASCII table.
    
    Args:
        headers: List of header strings
        rows: List of row tuples
        colors: Optional list of hex colors (one per row)
    
    Returns:
        List of formatted lines
    """
    rows = list(rows)
    if not rows:
        return ["(no data)"]
    
    # Calculate column widths
    widths = [max(len(str(h)), max(len(str(cell) if cell else "") for cell in col)) 
              for h, col in zip(headers, zip(*rows))]
    
    fmt = " | ".join(f"{{:<{w}}}" for w in widths)
    sep = "-+-".join("-" * w for w in widths)
    
    # Format header
    lines = [fmt.format(*headers), sep]
    
    # Format rows with optional colors
    for i, row in enumerate(rows):
        row_str = fmt.format(*(str(c) if c else "" for c in row))
        if colors and i < len(colors) and colors[i]:
            row_str = print_colored(row_str, colors[i])
        lines.append(row_str)
    
    return lines

def format_activities_table(rows, show_date=False):
    """
    Format activities as a table with color coding by category.
    
    Args:
        rows: Activity tuples (id, start, end, category, dur, tags, notes, color)
        show_date: Whether to show date in start column
    
    Returns:
        List of formatted lines
    """
    if not rows:
        return ["No activities found."]
    
    formatted = []
    colors = []
    total_minutes = 0
    
    for row in rows:
        # Handle both 7-tuple (no color) and 8-tuple (with color) formats
        if len(row) == 8:
            id, start, end, category, dur, tags, notes, color = row
        else:
            id, start, end, category, dur, tags, notes = row
            color = None
        
        start_str = f"{format_date_short(start)} {format_time(start)}" if show_date else format_time(start)
        
        # Format category/tags column
        cat_tags = f"{category}: {tags[:20]}..." if tags and len(tags) > 20 else (f"{category}: {tags}" if tags else category)
        cat_tags = cat_tags[:30] + "..." if len(cat_tags) > 30 else cat_tags
        
        # Format notes
        notes_display = (notes[:20] + "..." if len(notes) > 20 else notes) if notes else "-"
        
        formatted.append((id, start_str, format_time(end), format_duration(dur), cat_tags, notes_display))
        colors.append(color)
        total_minutes += dur or 0
    
    lines = format_table(["ID", "Start", "End", "Duration", "Category/Tags", "Notes"], formatted, colors)
    lines.extend(["", f"Total: {len(rows)} activities, {format_duration(total_minutes)}"])
    return lines

def format_categories_list(categories, show_stats=False):
    """
    Format categories list with colors.
    
    Args:
        categories: List of (id, name, color) or (id, name, color, count, minutes) tuples
        show_stats: Whether to show activity count and duration
    
    Returns:
        List of formatted lines
    """
    if not categories:
        return ["No categories yet."]
    
    lines = []
    for cat in categories:
        if show_stats and len(cat) >= 5:
            id, name, color, count, minutes = cat[:5]
            stat_str = f" ({count} activities, {format_duration(minutes)})"
        else:
            id, name, color = cat[:3]
            stat_str = ""
        
        color_indicator = f" [{color}]" if color else ""
        line = f"  [{id}] {name}{color_indicator}{stat_str}"
        
        if color:
            line = print_colored(line, color)
        
        lines.append(line)
    
    return lines

def print_help():
    """Return help text."""
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
│    manage  Manage categories and their tags:                           │
│            - List, rename, delete categories                           │
│            - Change category colors                                    │
│            - Manage tags within categories                             │
│                                                                        │
│  OTHER                                                                 │
│    help    Show this help screen                                       │
│                                                                        │
│  TIME FORMAT: 9:30, 9:30am, 9:30pm (defaults to AM)                    │
│  COLOR FORMAT: #RRGGBB (e.g., #FF5733, #3498DB)                        │
│  Ctrl+C to exit  |  Ctrl+Z to cancel current input                     │
└────────────────────────────────────────────────────────────────────────┘
"""

def get_color_samples():
    """Return a dict of named color samples."""
    return {
        "red": "#E74C3C",
        "blue": "#3498DB",
        "green": "#2ECC71",
        "yellow": "#F1C40F",
        "purple": "#9B59B6",
        "orange": "#E67E22",
        "pink": "#FD79A8",
        "cyan": "#00CEC9",
        "gray": "#95A5A6",
        "brown": "#8B4513",
    }

def display_color_samples():
    """Display available color presets."""
    samples = get_color_samples()
    lines = ["  Color presets (or enter custom #RRGGBB):"]
    for name, hex_val in samples.items():
        colored_sample = print_colored(f"    {name:8} {hex_val}", hex_val, bold=True)
        lines.append(colored_sample)
    return lines