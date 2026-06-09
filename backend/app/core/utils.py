def human_size(nbytes: int) -> str:
    """Format a byte count as a human-readable string (e.g. '1.2 GB')."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(nbytes) < 1024:
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024  # type: ignore[assignment]
    return f"{nbytes:.1f} PB"
