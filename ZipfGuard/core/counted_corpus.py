"""Strict, byte-preserving counted-password line format (LF framed)."""
import re

_COUNTED = re.compile(rb"^[ \t]*([0-9]+)[ \t](.*)$", re.DOTALL)


def parse_counted_line(raw: bytes, line_number: int) -> tuple[int, bytes]:
    # Exactly one field separator; any subsequent whitespace is password data.
    content = raw[:-1] if raw.endswith(b"\n") else raw
    match = _COUNTED.fullmatch(content)
    if not match or int(match[1]) <= 0:
        # Do not include input content in exceptions/logs.
        raise ValueError(f"invalid positive counted record at line {line_number}")
    return int(match[1]), match[2]
