"""Auto-generated listing text: make/model at the start, condition at the end."""

import re
from collections.abc import Iterable
from dataclasses import replace

from simple_auction.constants import TITLE_MAX_LENGTH
from simple_auction.models import Lot
from simple_auction.services.conditions import ConditionOption


def _any_of(names: Iterable[str]) -> str | None:
    """Regex alternation for condition names (longest first), or None."""
    unique = sorted({n for n in names if n}, key=len, reverse=True)
    return "|".join(re.escape(n) for n in unique) or None


def _strip_suffix(title: str, known: Iterable[str]) -> str:
    alts = _any_of(known)
    if alts:
        title = re.sub(rf"\s+-\s+(?:{alts})\s*$", "", title, flags=re.IGNORECASE)
    return title.strip()


def condition_title(title: str, condition: str, known: Iterable[str] = ()) -> str:
    """Append the condition (Colt 1911 -> Colt 1911 - Excellent), replacing any
    earlier one from `known`. The result is at most TITLE_MAX_LENGTH; the
    title text is trimmed to make room for the suffix if needed."""
    base = _strip_suffix(title, [*known, condition])
    if not base:
        return ""
    suffix = f" - {condition}" if condition else ""
    return base[: TITLE_MAX_LENGTH - len(suffix)].rstrip() + suffix


def untrimmed_title_length(
    title: str, condition: str, known: Iterable[str] = ()
) -> int:
    """How long the title would be with its suffix, before any trimming."""
    base = _strip_suffix(title, [*known, condition])
    if not base:
        return 0
    return len(base) + (len(f" - {condition}") if condition else 0)


def condition_desc(
    desc: str, condition: str, note: str, known: Iterable[str] = ()
) -> str:
    """Make the last paragraph "Condition: <name>. <note>", replacing the
    line for any earlier condition from `known`."""
    alts = _any_of([*known, condition])
    if alts:
        line_re = rf"^Condition:\s*(?:{alts})\..*$"
        desc = re.sub(line_re, "", desc, flags=re.MULTILINE | re.IGNORECASE)
    base = re.sub(r"\n{3,}", "\n\n", desc).strip()
    if not condition:
        return base
    line = f"Condition: {condition}. {note}".strip()
    return f"{base}\n\n{line}" if base else line


def find_option(options: list[ConditionOption], name: str) -> ConditionOption | None:
    return next((o for o in options if o.name.lower() == name.lower()), None)


_MAKE_MODEL_LINE = re.compile(r"^(?:Make|Model):.*(?:\n|$)", re.MULTILINE)


def make_model_prefix(make: str, model: str) -> str:
    """ "Remington" + "870 Wingmaster" -> "Remington 870 Wingmaster"."""
    return " ".join(part for part in (make.strip(), model.strip()) if part)


def make_model_title(title: str, old_prefix: str, make: str, model: str) -> str:
    """Start the title with make and model, replacing the previous make/model
    start (old_prefix) so editing them later doesn't stack up."""
    new = make_model_prefix(make, model)
    rest = title.strip()
    for prefix in sorted({old_prefix, new}, key=len, reverse=True):
        if prefix and rest.lower().startswith(prefix.lower()):
            rest = rest[len(prefix) :].strip()
            break
    return f"{new} {rest}".strip()


def make_model_desc(desc: str, make: str, model: str) -> str:
    """Put "Make: ..." and "Model: ..." lines at the top, replacing old ones."""
    rest = re.sub(r"\n{3,}", "\n\n", _MAKE_MODEL_LINE.sub("", desc)).strip()
    lines = [
        f"{label}: {value.strip()}"
        for label, value in (("Make", make), ("Model", model))
        if value.strip()
    ]
    head = "\n".join(lines)
    return "\n\n".join(part for part in (head, rest) if part)


def apply_condition(lot: Lot, options: list[ConditionOption]) -> Lot:
    """Condition suffix on the title and sentence in the description.

    With no condition picked, the lot is left exactly as it is.
    A condition that's no longer in the list (renamed or removed in Settings)
    keeps its title suffix, and its description text is left alone.
    """
    if not lot.condition:
        return lot  # nothing picked yet: leave title and description alone
    known = [o.name for o in options]
    option = find_option(options, lot.condition)
    desc = lot.desc
    if option is not None:
        desc = condition_desc(lot.desc, option.name, option.note, known)
    return replace(
        lot, title=condition_title(lot.title, lot.condition, known), desc=desc
    )
