"""Shared, deterministic candidates for finding one admissible password.

The order favours common policy boundaries, then exhaustively fills gaps.  It
therefore reaches modern 14/16/20+ minimum-length policies quickly without
silently abandoning uncommon exact ranges.
"""
from typing import List


_COMMON_LENGTHS = (8, 10, 12, 16, 14, 15, 13, 20, 24, 32, 48, 64)


def admissible_candidate_lengths(
    minimum: int = 8, maximum: int = 64
) -> List[int]:
    """Return unique probe lengths, common boundaries first, with full coverage."""
    minimum = max(4, int(minimum))
    maximum = max(minimum, int(maximum))
    preferred = [n for n in _COMMON_LENGTHS if minimum <= n <= maximum]
    return preferred + [
        n for n in range(minimum, maximum + 1) if n not in preferred
    ]


def stratified_password_candidates(length: int) -> List[str]:
    """Cover 2/3/4 character-class policies at exactly ``length`` chars."""
    if length < 4:
        return []
    filler = ("kqmxvzptnryfbw" * ((length // 14) + 2))[:length]

    def build(prefix: str) -> str:
        return (prefix + filler)[:length]

    return list(dict.fromkeys([
        build("a3"),       # lowercase + digit
        build("Aa3"),      # uppercase + lowercase + digit
        build("a3!"),      # lowercase + digit + symbol
        build("Aa3!"),     # all four common classes
    ]))
