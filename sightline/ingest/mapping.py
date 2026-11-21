"""Column mapping: the LLM proposes, deterministic code disposes.

1. A proposer (LLM, or a heuristic synonym matcher when offline) looks at a
   table's header, five sample rows and surrounding text, and proposes:
     - which source column feeds each canonical field,
     - how raw enum values map to canonical ones ("GND" -> "GROUND"),
     - the control totals the document states (line count, invoice total).
2. ``validate`` then checks, with no model involved:
     - every required field is mapped to a real, unique column,
     - every row parses to the declared type,
     - every enum value maps to an allowed value,
     - row count equals the stated line count,
     - the sum of the total column equals the stated invoice total (to the cent).
3. Only a mapping that passes every check produces trusted rows. Rejected
   mappings are logged with reasons (``runs/rejected_mappings.jsonl``).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from agents.llm import call_structured, detect_provider
from sightline.ingest.tables import RawTable

REJECTION_LOG = Path(__file__).resolve().parents[2] / "runs" / "rejected_mappings.jsonl"


@dataclass
class FieldSpec:
    name: str
    type: str  # str | int | decimal | date | enum
    required: bool = True
    description: str = ""
    synonyms: list[str] = field(default_factory=list)
    enum: list[str] = field(default_factory=list)
    enum_synonyms: dict[str, list[str]] = field(default_factory=dict)
    default: Any = None


@dataclass
class CanonicalSchema:
    name: str
    fields: list[FieldSpec]
    total_field: str  # field whose column sum must equal the stated total

    def get(self, name: str) -> FieldSpec:
        return next(f for f in self.fields if f.name == name)


@dataclass
class Mapping:
    columns: dict[str, str | None]
    value_maps: dict[str, dict[str, str]]
    control_totals: dict[str, Any]
    proposed_by: str


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str]
    rows: list[dict[str, Any]]  # typed canonical rows (only meaningful if ok)


# ---------------------------------------------------------------------------
# Proposers
# ---------------------------------------------------------------------------
def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def propose_heuristic(table: RawTable, schema: CanonicalSchema) -> Mapping:
    headers = {_norm(h): h for h in table.header}
    columns: dict[str, str | None] = {}
    used: set[str] = set()
    for f in schema.fields:
        hit = None
        for cand in [f.name, *f.synonyms]:
            h = headers.get(_norm(cand))
            if h and h not in used:
                hit = h
                break
        columns[f.name] = hit
        if hit:
            used.add(hit)
    value_maps: dict[str, dict[str, str]] = {}
    for f in schema.fields:
        if f.type != "enum" or not columns.get(f.name):
            continue
        idx = table.header.index(columns[f.name])
        vm = {}
        for raw in {r.values[idx] for r in table.rows if idx < len(r.values)}:
            for canon, syns in f.enum_synonyms.items():
                if _norm(raw) in {_norm(canon), *(_norm(s) for s in syns)}:
                    vm[raw] = canon
        value_maps[f.name] = vm
    return Mapping(columns, value_maps, extract_control_totals(table.context_text), "heuristic")


_MONEY = r"\$?\s*([0-9][0-9,]*\.[0-9]{2})"


def extract_control_totals(text: str) -> dict[str, Any]:
    """Pull stated control totals out of free text. Returns only numbers that
    literally appear in the text."""
    out: dict[str, Any] = {"line_count": None, "total_amount": None, "invoice_id": None, "invoice_date": None}
    m = re.search(r"(?:line count|shipment lines|lines)\s*[:=,]?\s*(\d+)", text, re.I)
    if m:
        out["line_count"] = int(m.group(1))
    m = re.search(r"(?:invoice total|amount due|total due|total)\s*[:=,]?\s*" + _MONEY, text, re.I)
    if m:
        out["total_amount"] = m.group(1).replace(",", "")
    m = re.search(r"invoice\s*(?:no\.?|number|#)\s*[:=,]?\s*([A-Z0-9][A-Z0-9-]{3,})", text, re.I)
    if m:
        out["invoice_id"] = m.group(1)
    m = re.search(r"invoice date\s*[:=,]?\s*(\d{4}-\d{2}-\d{2})", text, re.I)
    if m:
        out["invoice_date"] = m.group(1)
    return out


MAPPING_SCHEMA = {
    "type": "object",
    "properties": {
        "columns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string"},
                    "source_column": {"type": ["string", "null"]},
                },
                "required": ["field", "source_column"],
            },
        },
        "value_maps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string"},
                    "raw": {"type": "string"},
                    "canonical": {"type": "string"},
                },
                "required": ["field", "raw", "canonical"],
            },
        },
        "control_totals": {
            "type": "object",
            "properties": {
                "line_count": {"type": ["integer", "null"]},
                "total_amount": {"type": ["string", "null"]},
                "invoice_id": {"type": ["string", "null"]},
                "invoice_date": {"type": ["string", "null"]},
            },
            "required": ["line_count", "total_amount", "invoice_id", "invoice_date"],
        },
    },
    "required": ["columns", "value_maps", "control_totals"],
}

MAPPER_SYSTEM = (
    "You map columns of an uploaded table onto a fixed canonical schema. "
    "Use only the header names given; never invent a column. If no column "
    "fits a field, use null. For enum fields, map each distinct raw value "
    "you see to one allowed canonical value. Copy control totals (line "
    "count, invoice total, invoice id, invoice date) exactly as they appear "
    "in the surrounding text; use null if they are not stated. Do not "
    "compute anything. Deterministic code will verify every part of your "
    "answer against the full file before it is trusted."
)


def propose_llm(table: RawTable, schema: CanonicalSchema) -> Mapping:
    enum_values = {}
    for f in schema.fields:
        if f.type == "enum":
            # distinct raw values (bounded) so the model can build a value map
            try:
                idx = table.header.index(propose_heuristic(table, schema).columns.get(f.name) or "")
                enum_values[f.name] = sorted({r.values[idx] for r in table.rows})[:30]
            except ValueError:
                enum_values[f.name] = []
    payload = {
        "canonical_fields": [
            {"field": f.name, "type": f.type, "required": f.required, "description": f.description,
             **({"allowed": f.enum} if f.enum else {})}
            for f in schema.fields
        ],
        "source_file": table.source_file,
        "header": table.header,
        "sample_rows": table.sample(5),
        "distinct_enum_values_seen": enum_values,
        "surrounding_text": table.context_text[:3000],
    }
    res = call_structured(
        system=MAPPER_SYSTEM,
        user_content=json.dumps(payload, indent=1),
        tool_name="propose_mapping",
        tool_description="Propose a column mapping, enum value maps and stated control totals.",
        input_schema=MAPPING_SCHEMA,
        agent="mapper",
    )
    d = res.data
    columns = {c["field"]: c["source_column"] for c in d["columns"]}
    vmaps: dict[str, dict[str, str]] = {}
    for v in d["value_maps"]:
        vmaps.setdefault(v["field"], {})[v["raw"]] = v["canonical"]
    return Mapping(columns, vmaps, d["control_totals"], f"llm:{res.model}")


# ---------------------------------------------------------------------------
# Deterministic validation
# ---------------------------------------------------------------------------
def _parse(value: str, spec: FieldSpec, vmap: dict[str, str]) -> Any:
    v = value.strip()
    if v == "":
        if spec.required and spec.default is None:
            raise ValueError("empty")
        return spec.default
    if spec.type == "str":
        return v
    if spec.type == "int":
        return int(v.replace(",", ""))
    if spec.type == "decimal":
        try:
            return Decimal(v.replace(",", "").replace("$", ""))
        except InvalidOperation as e:
            raise ValueError(f"not a number: {v!r}") from e
    if spec.type == "date":
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d-%b-%Y"):
            try:
                return datetime.strptime(v, fmt).date()
            except ValueError:
                pass
        raise ValueError(f"not a date: {v!r}")
    if spec.type == "enum":
        canon = vmap.get(v, v)
        if canon not in spec.enum:
            raise ValueError(f"unmapped enum value {v!r}")
        return canon
    raise ValueError(f"unknown type {spec.type}")


def validate(table: RawTable, schema: CanonicalSchema, mapping: Mapping) -> ValidationResult:
    errors: list[str] = []
    # 1. structural checks
    for f in schema.fields:
        col = mapping.columns.get(f.name)
        if col is None:
            if f.required and f.default is None:
                errors.append(f"required field '{f.name}' is not mapped")
        elif col not in table.header:
            errors.append(f"field '{f.name}' mapped to non-existent column '{col}'")
    mapped = [c for c in mapping.columns.values() if c]
    dupes = {c for c in mapped if mapped.count(c) > 1}
    if dupes:
        errors.append(f"columns mapped to more than one field: {sorted(dupes)}")
    for fname, vmap in mapping.value_maps.items():
        spec = next((f for f in schema.fields if f.name == fname), None)
        bad = [v for v in vmap.values() if spec and spec.enum and v not in spec.enum]
        if bad:
            errors.append(f"value map for '{fname}' targets values outside the enum: {bad}")
    if errors:
        return ValidationResult(False, errors, [])

    # 2. row-level type checks
    idx = {f.name: table.header.index(c) for f in schema.fields if (c := mapping.columns.get(f.name))}
    rows: list[dict[str, Any]] = []
    for r in table.rows:
        row: dict[str, Any] = {"_file": table.source_file, "_location": r.location}
        for f in schema.fields:
            raw = r.values[idx[f.name]] if f.name in idx and idx[f.name] < len(r.values) else ""
            try:
                row[f.name] = _parse(raw, f, mapping.value_maps.get(f.name, {}))
            except ValueError as e:
                errors.append(f"{r.location}: field '{f.name}': {e}")
        rows.append(row)
    if errors:
        return ValidationResult(False, errors[:20] + ([f"... {len(errors) - 20} more"] if len(errors) > 20 else []), [])

    # 3. control totals: row count and money total must reconcile
    ct = mapping.control_totals or {}
    if ct.get("line_count") is None:
        errors.append("no stated line count found; cannot verify row count")
    elif int(ct["line_count"]) != len(rows):
        errors.append(f"row count {len(rows)} != stated line count {ct['line_count']}")
    if ct.get("total_amount") is None:
        errors.append("no stated total found; cannot verify totals")
    else:
        stated = Decimal(str(ct["total_amount"]).replace(",", ""))
        computed = sum((row[schema.total_field] or Decimal(0) for row in rows), Decimal(0))
        if abs(computed - stated) > Decimal("0.005"):
            errors.append(f"sum of '{schema.total_field}' {computed} != stated total {stated}")
    # anti-hallucination: stated numbers must literally appear in the source text
    for key in ("line_count", "total_amount", "invoice_id"):
        val = ct.get(key)
        if val is not None and str(val) not in table.context_text.replace(",", ""):
            errors.append(f"control total '{key}'={val} does not appear in the document text")
    return ValidationResult(not errors, errors, rows if not errors else [])


def log_rejection(table: RawTable, mapping: Mapping, errors: list[str], log_path: Path = REJECTION_LOG) -> dict:
    entry = {
        "at": datetime.now().isoformat(timespec="seconds"),
        "file": table.source_file,
        "proposed_by": mapping.proposed_by,
        "columns": mapping.columns,
        "errors": errors,
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a") as f:
        f.write(json.dumps(entry, default=str) + "\n")
    return entry


def ingest_table(table: RawTable, schema: CanonicalSchema, rejections: list[dict]) -> tuple[list[dict], Mapping]:
    """Try the LLM proposer (if a provider is configured), then the heuristic
    proposer. Return trusted rows from the first mapping that validates."""
    proposers = [propose_heuristic] if detect_provider() == "mock" else [propose_llm, propose_heuristic]
    last: Mapping | None = None
    for proposer in proposers:
        try:
            mapping = proposer(table, schema)
        except Exception as e:  # a proposer failing is itself a rejection
            rejections.append({"file": table.source_file, "proposed_by": proposer.__name__, "errors": [repr(e)]})
            continue
        last = mapping
        result = validate(table, schema, mapping)
        if result.ok:
            for row in result.rows:
                row["_invoice_id"] = mapping.control_totals.get("invoice_id")
                row["_invoice_date"] = mapping.control_totals.get("invoice_date")
            return result.rows, mapping
        rejections.append(log_rejection(table, mapping, result.errors))
    raise MappingRejected(table.source_file, rejections, last)


class MappingRejected(Exception):
    def __init__(self, file: str, rejections: list[dict], mapping: Mapping | None):
        super().__init__(f"No mapping for {file} passed validation: "
                         + "; ".join(e for r in rejections if r.get("file") == file for e in r["errors"][:3]))
        self.file = file
        self.rejections = rejections
        self.mapping = mapping


__all__ = ["FieldSpec", "CanonicalSchema", "Mapping", "validate", "ingest_table", "MappingRejected",
           "propose_heuristic", "propose_llm", "extract_control_totals", "date"]
