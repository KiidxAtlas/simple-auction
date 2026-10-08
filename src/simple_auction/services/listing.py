"""Auto-generated listing text: make/model at the start, condition at the end."""

import re
from dataclasses import replace

from simple_auction.constants import TITLE_MAX_LENGTH
from simple_auction.models import Condition, Lot

# The sentence added to the description for each condition. Edit freely.
CONDITION_NOTES: dict[Condition, str] = {
    Condition.LIKE_NEW: "Appears unfired or barely used, no notable wear.",
    Condition.EXCELLENT: "Light handling marks, bore bright.",
    Condition.GOOD: "Normal wear and handling marks consistent with use.",
    Condition.FAIR: "Noticeable wear, finish loss or marks. See photos.",
}

_ANY = "|".join(re.escape(c.value) for c in Condition)
_TITLE_SUFFIX = re.compile(rf"\s+-\s+(?:{_ANY})\s*$")
_DESC_LINE = re.compile(rf"^Condition:\s*(?:{_ANY})\..*$", re.MULTILINE)


def _title_parts(title: str, condition: Condition) -> tuple[str, str]:
    return _TITLE_SUFFIX.sub("", title).strip(), f" - {condition.value}"


def condition_title(title: str, condition: Condition) -> str:
    """Append the condition (Colt 1911 -> Colt 1911 - Excellent), replacing any
    old one. The result is at most TITLE_MAX_LENGTH; the title text is trimmed
    to make room for the suffix if needed."""
    base, suffix = _title_parts(title, condition)
    if not base:
        return ""
    return base[: TITLE_MAX_LENGTH - len(suffix)].rstrip() + suffix


def untrimmed_title_length(title: str, condition: Condition) -> int:
    """How long the title would be with its suffix, before any trimming."""
    base, suffix = _title_parts(title, condition)
    return len(base) + len(suffix) if base else 0


def condition_desc(desc: str, condition: Condition) -> str:
    """Add the condition sentence as the last paragraph, replacing any old one."""
    base = re.sub(r"\n{3,}", "\n\n", _DESC_LINE.sub("", desc)).strip()
    line = f"Condition: {condition.value}. {CONDITION_NOTES[condition]}"
    return f"{base}\n\n{line}" if base else line


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


def apply_condition(lot: Lot) -> Lot:
    return replace(
        lot,
        title=condition_title(lot.title, lot.condition),
        desc=condition_desc(lot.desc, lot.condition),
    )
