"""File, column and row-level validation for an uploaded reconciliation CSV.

The guiding rule: when a file is rejected, the user must be told exactly what is
wrong and what the file should have looked like — never just "invalid CSV".
"""

import io
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import pandas as pd

from app.modules.m4.column_map import MappingResult
from app.modules.m4.fields import BY_NAME

# Strips currency symbols, thousands separators and stray spaces before parsing.
_NUMERIC_NOISE = re.compile(r"[,\s₹$€£]")
# Trailing negative, as some ERP exports emit "1200-" rather than "-1200".
_TRAILING_MINUS = re.compile(r"^(\d+(?:\.\d+)?)-$")

# Canonical quantity/money columns are Numeric(18,4): fourteen digits before the
# decimal point. A larger value parses happily in Python and only fails when
# Postgres rejects it during normalization, which surfaces as an opaque 500
# instead of a row error. Bound it here so it is reported like any other bad cell.
MAX_NUMERIC = Decimal("99999999999999.9999")

_DATE_FORMATS = (
    "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y",
    "%Y/%m/%d", "%d %b %Y", "%d %B %Y", "%b %d %Y", "%d-%b-%Y", "%d-%b-%y",
    # Excel hands back real datetimes, which stringify with a midnight component.
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M:%S",
)

EXCEL_SUFFIXES = (".xlsx", ".xlsm", ".xls")
ACCEPTED_SUFFIXES = (".csv", *EXCEL_SUFFIXES)


class CsvFormatError(Exception):
    """The file could not be read as a CSV at all."""

    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message)
        self.message = message
        self.hint = hint


@dataclass
class RowError:
    row_number: int
    field: str | None
    source_column: str | None
    value: str | None
    message: str


@dataclass
class ParsedRow:
    row_number: int
    raw: dict
    mapped: dict
    errors: list[RowError]

    @property
    def is_valid(self) -> bool:
        return not self.errors


def read_excel(content: bytes, filename: str) -> pd.DataFrame:
    """Read a workbook, choosing the sheet and header row that actually contain data.

    Real exports rarely start cleanly at A1 — a report title, a company name or a
    blank spacer row usually sits above the headings, and a workbook often carries
    several sheets. Rejecting those would push the user back into Excel to tidy up
    by hand, which is the work this tool is supposed to remove.
    """
    engine = "xlrd" if filename.lower().endswith(".xls") else "openpyxl"
    try:
        book = pd.read_excel(io.BytesIO(content), sheet_name=None, header=None,
                             dtype=object, engine=engine)
    except ImportError as exc:
        raise CsvFormatError(
            "This workbook format could not be opened.",
            "Save the file as .xlsx or CSV and upload it again.",
        ) from exc
    except Exception as exc:
        raise CsvFormatError(
            f"The workbook could not be read: {exc}",
            "Check the file is not password protected, then re-save it as .xlsx or CSV.",
        ) from exc

    if not book:
        raise CsvFormatError(
            "The workbook contains no sheets.",
            "Add a sheet with a header row and at least one data row.",
        )

    best: tuple[int, pd.DataFrame] | None = None
    for raw in book.values():
        if raw.empty:
            continue
        candidate = _promote_header(raw)
        if candidate is None:
            continue
        score, frame = candidate
        if best is None or score > best[0]:
            best = (score, frame)

    if best is None:
        raise CsvFormatError(
            "No sheet in this workbook has a usable header row.",
            "The heading row must name the columns — see the expected format below.",
        )

    return best[1]


def _promote_header(raw: pd.DataFrame) -> tuple[int, pd.DataFrame] | None:
    """Find the row that is the real header and rebuild the frame beneath it."""
    from app.modules.m4.column_map import resolve_columns

    limit = min(len(raw), 12)
    best: tuple[int, pd.DataFrame] | None = None

    for index in range(limit):
        header = [
            "" if pd.isna(v) else str(v).strip()
            for v in raw.iloc[index].tolist()
        ]
        if not any(header):
            continue

        matched = len(resolve_columns([h for h in header if h]).mapping)
        if matched == 0:
            continue

        body = raw.iloc[index + 1:].copy()
        if body.empty:
            continue
        body.columns = [h or f"column_{i + 1}" for i, h in enumerate(header)]
        body = body.dropna(how="all")
        if body.empty:
            continue

        if best is None or matched > best[0]:
            best = (matched, body.reset_index(drop=True))

    return best


def read_tabular(content: bytes, filename: str) -> pd.DataFrame:
    """Read whatever the user actually uploaded — CSV or Excel."""
    frame = (
        read_excel(content, filename)
        if filename.lower().endswith(EXCEL_SUFFIXES)
        else read_csv(content, filename)
    )
    # Downstream validation is written against text cells, so Excel's native
    # numbers, dates and booleans are flattened to strings here rather than
    # being special-cased in every rule.
    for column in frame.columns:
        frame[column] = frame[column].map(_stringify)
    return frame


def _stringify(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, str):
        return value.strip()
    if pd.isna(value):
        return ""
    if isinstance(value, (pd.Timestamp,)):
        # Midnight means Excel stored a plain date; keep it that way.
        return value.date().isoformat() if value.time().isoformat() == "00:00:00" else str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def read_csv(content: bytes, filename: str = "upload.csv") -> pd.DataFrame:
    if not content.strip():
        raise CsvFormatError(
            "The uploaded file is empty.",
            "Export your data again and confirm the file has a header row and at least one data row.",
        )

    last_error: Exception | None = None
    # utf-8-sig first: Excel on Windows prepends a BOM that would otherwise become
    # part of the first column name and break header matching.
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            frame = pd.read_csv(
                io.BytesIO(content),
                dtype=str,
                keep_default_na=False,
                na_values=[],
                encoding=encoding,
                skip_blank_lines=True,
            )
            break
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
        except pd.errors.EmptyDataError as exc:
            raise CsvFormatError(
                "The file contains no readable rows.",
                "Check that the first line is a header row of column names.",
            ) from exc
        except pd.errors.ParserError as exc:
            raise CsvFormatError(
                f"The file could not be parsed as CSV: {exc}",
                "Rows probably have differing numbers of columns. Re-export as a plain CSV.",
            ) from exc
    else:
        raise CsvFormatError(
            "The file's text encoding could not be determined.",
            "Save the file as CSV UTF-8 and upload it again.",
        ) from last_error

    frame.columns = [str(c).strip() for c in frame.columns]

    if frame.empty:
        raise CsvFormatError(
            "The file has a header row but no data rows.",
            "Add at least one line of data below the header.",
        )

    blank = [i for i, c in enumerate(frame.columns) if not c or c.startswith("Unnamed:")]
    if len(blank) == len(frame.columns):
        raise CsvFormatError(
            "No column names were found in the first row.",
            "The first row must contain column headings, not data.",
        )

    return frame


def parse_number(value: str) -> Decimal | None:
    text = _NUMERIC_NOISE.sub("", str(value).strip())
    if not text:
        return None
    if (m := _TRAILING_MINUS.match(text)):
        text = f"-{m.group(1)}"
    if text.startswith("(") and text.endswith(")"):  # (1200) = negative
        text = f"-{text[1:-1]}"
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def parse_date(value: str) -> date | None:
    text = str(value).strip()
    if not text:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def validate_rows(frame: pd.DataFrame, mapping: MappingResult) -> list[ParsedRow]:
    """Coerce every row into canonical types, collecting per-cell failures.

    Invalid rows are kept, not dropped. A row that cannot be parsed still has to
    surface later as an INCOMPLETE result rather than silently disappearing
    between the file the user uploaded and the numbers they are shown.
    """
    rows: list[ParsedRow] = []
    records = frame.to_dict(orient="records")

    for index, record in enumerate(records):
        # +2 so the number matches what the user sees in a spreadsheet:
        # row 1 is the header, data starts at row 2.
        row_number = index + 2
        mapped: dict = {}
        errors: list[RowError] = []

        for field_name, match in mapping.mapping.items():
            spec = BY_NAME[field_name]
            raw_value = str(record.get(match.source_column, "") or "").strip()

            if not raw_value:
                mapped[field_name] = None
                if spec.required:
                    errors.append(RowError(
                        row_number, field_name, match.source_column, None,
                        f"{spec.label} is blank. This column is required.",
                    ))
                continue

            if spec.kind == "number":
                number = parse_number(raw_value)
                if number is None:
                    errors.append(RowError(
                        row_number, field_name, match.source_column, raw_value,
                        f"{spec.label} is \"{raw_value}\", which is not a number.",
                    ))
                    mapped[field_name] = None
                elif number < 0:
                    errors.append(RowError(
                        row_number, field_name, match.source_column, raw_value,
                        f"{spec.label} is negative ({number}). Quantities and prices must be zero or above.",
                    ))
                    mapped[field_name] = str(number)
                elif abs(number) > MAX_NUMERIC:
                    errors.append(RowError(
                        row_number, field_name, match.source_column, raw_value,
                        f"{spec.label} is {raw_value}, which is too large to store. "
                        f"The maximum is {MAX_NUMERIC:,.4f}.",
                    ))
                    mapped[field_name] = None
                else:
                    mapped[field_name] = str(number)

            elif spec.kind == "date":
                parsed = parse_date(raw_value)
                if parsed is None:
                    errors.append(RowError(
                        row_number, field_name, match.source_column, raw_value,
                        f"{spec.label} is \"{raw_value}\", which is not a recognised date. "
                        "Use DD/MM/YYYY or YYYY-MM-DD.",
                    ))
                    mapped[field_name] = None
                else:
                    mapped[field_name] = parsed.isoformat()

            else:
                mapped[field_name] = raw_value

        # Quantity of zero on the order itself means there is nothing to reconcile.
        po_qty = mapped.get("po_quantity")
        if po_qty is not None and Decimal(po_qty) == 0:
            errors.append(RowError(
                row_number, "po_quantity", mapping.source_for("po_quantity"), po_qty,
                "PO Quantity is zero, so there is nothing to reconcile on this line.",
            ))

        rows.append(ParsedRow(
            row_number=row_number,
            raw={str(k): ("" if v is None else str(v)) for k, v in record.items()},
            mapped=mapped,
            errors=errors,
        ))

    return rows


def errors_to_json(errors: list[RowError]) -> list[dict]:
    return [asdict(e) for e in errors]
