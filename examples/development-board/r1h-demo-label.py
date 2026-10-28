def normalize_label(value):
    """Collapse repeated whitespace in a display label."""
    return " ".join(value.split())
