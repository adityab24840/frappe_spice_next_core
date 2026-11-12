"""Rules for a card's field kinds and for the labels a person (or a phone) gives its cells. Pure Python: no frappe import, so it is unit-tested alone.

Ported from Card Studio (banglahandwriting/studio/labeling.py + cards.KIND_CHARS) so the Frappe side refuses and warns on the same things:
  - a label may only use characters its field can emit (an error: the reader could never produce the others);
  - a label that is allowed but looks wrong for the kind (a date without a month, a weight outside its range) is a warning, saved anyway
    when the person confirms it.
Bangla digits are stored as 0-9 (the reader's classes).
"""
import re

BN2EN = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
KIND_CHARS = {"number": "-.0123456789", "date": "-./0123456789", "bp": "/0123456789", "mark": "-xy"}      # text = anything
KINDS = ("number", "date", "bp", "mark", "text")
LAYOUTS = ("single", "stacked", "diagonal")
DECODES = ("greedy", "grammar")
NOTES = ("", "blank", "unreadable")
HOW = ("", "typed", "accepted", "corrected", "ai-read", "phone")
MAX_LABEL = 40
KEY = re.compile(r"^[A-Za-z0-9_]{1,40}$")
CARD_KEY = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
WRITER = re.compile(r"^[A-Za-z0-9_-]{1,24}$")
VISIT = re.compile(r"^c\d{1,2}$")
SHAPE = {
    "number": (re.compile(r"^\d+(\.\d+)?$"), "a number like 57 or 9.6"),
    "date": (re.compile(r"^\d{1,2}[./]\d{1,2}[./]\d{2}(\d{2})?$"), "day, month, year like 22/2/26"),
    "bp": (re.compile(r"^\d{2,3}/\d{2,3}$"), "systolic/diastolic like 120/80"),
    "mark": (re.compile(r"^[yx-]$"), "y (tick), x (cross) or - (dash)"),
}


def normalize(label):
    """Bangla digits to 0-9, whitespace squeezed."""
    return " ".join(str(label or "").translate(BN2EN).split())


def check_label(kind, label, key="field", rng=None):
    """-> (error or None, warning or None) for a normalized, non-empty label of a field of this kind. rng: (low, high) or None."""
    if kind not in KINDS:
        return f"unknown field kind {kind!r}", None
    allowed = KIND_CHARS.get(kind)
    if allowed is not None:
        bad = sorted({c for c in label if c not in allowed})
        if bad:
            return f"{key} is a {kind} field and cannot hold {' '.join(repr(c) for c in bad)}: fix the label, or change the field's kind", None
    shape = SHAPE.get(kind)
    if shape and not shape[0].match(label) and not (kind != "mark" and label == "-"):
        return None, f"does not look like {shape[1]}"
    if kind == "number" and rng and shape[0].match(label) and not rng[0] <= float(label) <= rng[1]:
        return None, f"outside the expected range {rng[0]:g} to {rng[1]:g}"
    if kind == "date" and shape[0].match(label):
        d, mo = (int(x) for x in re.split(r"[./]", label)[:2])
        if not (1 <= d <= 31 and 1 <= mo <= 12):
            return None, "not a real day and month"
    return None, None


def check_cell(kind, label, note, key="field", rng=None, how=""):
    """Validate everything about one labelled cell. -> (normalized label, error or None, warning or None).
    A note of blank / unreadable stores no label. how is where the label came from."""
    if note not in NOTES:
        return "", "note must be empty, blank or unreadable", None
    if how not in HOW:
        return "", f"how must be one of {', '.join(h for h in HOW if h)}", None
    if note:
        return "", None, None
    label = normalize(label)
    if not label:
        return "", "type what the cell says, or mark it blank or unreadable", None
    if len(label) > MAX_LABEL:
        return label, f"label is longer than {MAX_LABEL} characters", None
    if any(ord(c) < 32 for c in label):
        return label, "label has control characters", None
    err, warn = check_label(kind, label, key, rng)
    return label, err, warn


def check_field_spec(key, kind, layout="single", decode="greedy", low=None, high=None):
    """-> error or None for one field of a card type (mirrors the cardpack format's field rules)."""
    if not KEY.match(key or ""):
        return f"{key!r}: a field key is letters, digits and _ (at most 40)"
    if kind not in KINDS:
        return f"{key}: unknown kind {kind!r}"
    if layout not in LAYOUTS:
        return f"{key}: unknown layout {layout!r}"
    if (layout == "stacked" and kind != "date") or (layout == "diagonal" and kind != "bp"):
        return f"{key}: layout {layout} does not fit kind {kind}"
    if decode not in DECODES:
        return f"{key}: unknown decode {decode!r}"
    if decode == "grammar" and (layout != "single" or not (kind in ("date", "bp") or (kind == "number" and low is not None and high is not None))):
        return f"{key}: decode grammar needs a one-line date, bp or ranged number"
    if (low is None) != (high is None):
        return f"{key}: give both ends of the range or neither"
    if low is not None and low > high:
        return f"{key}: range low is above range high"
    return None


def writer_problem(writer):
    """None when empty or a valid writer code; otherwise why not (a name is refused)."""
    if not writer:
        return None
    return None if WRITER.match(writer) else "a writer is a code like W07 or a clinic id (letters, digits, _ and -, at most 24), never a name"
