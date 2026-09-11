"""Deterministic CSV header → canonical field resolution.

No model is involved. A header is normalised to a comparable form and looked up
in a fixed alias table; anything that fails to match is reported as unmapped so
the user can map it by hand. That keeps the outcome reproducible: the same file
always produces the same mapping, which matters because the mapping ends up
recorded against an auditable run.
"""

import re
from dataclasses import asdict, dataclass
from typing import Literal

from app.modules.m4.fields import BY_NAME, FIELDS, REQUIRED_FIELDS

MatchKind = Literal["exact", "alias", "manual", "unmapped"]

_PUNCT = re.compile(r"[_\-./\\#()\[\]:;,'\"]+")
_SPACE = re.compile(r"\s+")


def normalize_header(raw: str) -> str:
    """'PO_Number ' -> 'po number'; 'Ordered Qty.' -> 'ordered qty'."""
    text = _PUNCT.sub(" ", str(raw).strip().lower())
    return _SPACE.sub(" ", text).strip()


# Built once. Exact canonical names win over aliases when both would match.
_LOOKUP: dict[str, tuple[str, MatchKind]] = {}
for spec in FIELDS:
    for alias in spec.aliases:
        _LOOKUP.setdefault(normalize_header(alias), (spec.name, "alias"))
for spec in FIELDS:
    _LOOKUP[normalize_header(spec.name)] = (spec.name, "exact")
    _LOOKUP[normalize_header(spec.label)] = (spec.name, "exact")


@dataclass
class ColumnMatch:
    canonical_field: str
    source_column: str
    match: MatchKind


@dataclass
class MappingResult:
    mapping: dict[str, ColumnMatch]        # canonical_field -> match
    unmapped_columns: list[str]            # headers we could not place
    missing_required: list[str]            # required fields with no column
    duplicate_targets: dict[str, list[str]]  # canonical_field -> extra columns

    @property
    def is_usable(self) -> bool:
        return not self.missing_required

    def to_json(self) -> dict:
        return {
            "mapping": {k: asdict(v) for k, v in self.mapping.items()},
            "unmapped_columns": self.unmapped_columns,
            "missing_required": self.missing_required,
            "duplicate_targets": self.duplicate_targets,
        }

    def source_for(self, canonical_field: str) -> str | None:
        match = self.mapping.get(canonical_field)
        return match.source_column if match else None


def resolve_columns(
    headers: list[str], overrides: dict[str, str] | None = None
) -> MappingResult:
    """Map source headers onto canonical fields.

    `overrides` maps canonical_field -> source_column and always wins, which is
    how the Mapping screen's manual corrections are applied.
    """
    mapping: dict[str, ColumnMatch] = {}
    duplicates: dict[str, list[str]] = {}
    claimed: set[str] = set()

    for header in headers:
        hit = _LOOKUP.get(normalize_header(header))
        if not hit:
            continue
        field_name, kind = hit
        if field_name in mapping:
            # Two columns both claim one field. First wins; the rest are surfaced
            # so the user can pick the right one rather than us guessing.
            duplicates.setdefault(field_name, []).append(header)
            continue
        mapping[field_name] = ColumnMatch(field_name, header, kind)
        claimed.add(header)

    for field_name, source_column in (overrides or {}).items():
        if field_name not in BY_NAME:
            continue
        if source_column not in headers:
            continue
        previous = mapping.get(field_name)
        if previous:
            claimed.discard(previous.source_column)
        mapping[field_name] = ColumnMatch(field_name, source_column, "manual")
        claimed.add(source_column)
        duplicates.pop(field_name, None)

    unmapped = [h for h in headers if h not in claimed]
    missing = [f for f in REQUIRED_FIELDS if f not in mapping]

    return MappingResult(
        mapping=mapping,
        unmapped_columns=unmapped,
        missing_required=missing,
        duplicate_targets=duplicates,
    )
