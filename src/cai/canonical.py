"""Canonical JSON, so the digest means something outside this process.

WHY NOT json.dumps(sort_keys=True)
----------------------------------
That is deterministic *for Python*. The claim being made is stronger -- a platform-neutral
contract another implementation can verify -- and Python's sorting and float formatting are
not the same thing as a specification.

Two differences that actually bite:

  * `sort_keys=True` orders by Python string comparison, which is by Unicode code POINT.
    RFC 8785 orders by UTF-16 code UNIT. These disagree above the BMP, so a record
    containing an emoji key can be canonicalised two different ways by two conforming
    implementations, and the digests will not match.
  * Python's `repr` for floats and JavaScript's `Number::toString` agree far more often
    than people expect, and not always. Rather than pretend otherwise, non-integer floats
    are refused outright here -- see below.

WHAT THIS IMPLEMENTS
--------------------
The subset of RFC 8785 (JSON Canonicalization Scheme) this contract needs: UTF-8 output,
object keys sorted by UTF-16 code unit, no insignificant whitespace, and the JSON string
escaping rules. Numbers are restricted rather than approximated.

WHAT IT REFUSES RATHER THAN GUESS
---------------------------------
Non-integer floats, NaN and infinities are rejected. A canonicalizer that quietly formats
0.1 differently from another implementation produces two valid-looking digests for one
record, which is worse than refusing to serialize it. Scores travel as strings carrying
their own precision; nothing in this contract needs a raw float on the wire.
"""

from __future__ import annotations

import json
import math
from typing import Any

CANONICALIZATION = "RFC8785-subset/1"


class NotCanonicalizable(Exception):
    """Raised rather than emitting bytes another implementation might not reproduce."""


def _key_order(key: str) -> tuple[int, ...]:
    """UTF-16 code units, per RFC 8785 section 3.2.3.

    Python sorts by code point. For anything outside the Basic Multilingual Plane the two
    disagree, and a contract that only works for ASCII keys should say so rather than
    discover it later.
    """
    return tuple(key.encode("utf-16-be").hex(" ").split())  # ordered code units


def _canonical(value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise NotCanonicalizable(f"{value!r} has no canonical JSON form")
        if value != int(value):
            raise NotCanonicalizable(
                f"non-integer float {value!r} cannot be canonicalised portably; carry it "
                f"as a string with explicit precision"
            )
        return int(value)
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if isinstance(value, dict):
        items = sorted(value.items(), key=lambda kv: _key_order(kv[0]))
        return {k: _canonical(v) for k, v in items}
    raise NotCanonicalizable(f"{type(value).__name__} has no canonical JSON form")


def canonicalize(payload: dict[str, Any]) -> str:
    """Deterministic, cross-implementation-reproducible JSON text."""
    return json.dumps(
        _canonical(payload),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=False,  # ordering already applied, by UTF-16 code unit
    )
