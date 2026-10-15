"""Visible Blend names. The stored group name stays whatever was saved."""


def first_name(display_name: str | None, username: str) -> str:
    """First word of the display name, or the username when that is missing."""
    source = (display_name or username or "").strip()
    if not source:
        return "Someone"
    return source.split()[0]


def default_blend_name(first_names: list[str]) -> str:
    """'Alex', 'Alex & Sam', or 'Alex, Sam & 2 others'."""
    names = [name for name in first_names if name]
    if not names:
        return "Blend"
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} & {names[1]}"
    others = len(names) - 2
    label = "other" if others == 1 else "others"
    return f"{names[0]}, {names[1]} & {others} {label}"


def blend_display_name(stored_name: str | None, first_names: list[str]) -> str:
    """Stored name when one was set, otherwise the member default."""
    if stored_name and stored_name.strip():
        return stored_name.strip()
    return default_blend_name(first_names)
