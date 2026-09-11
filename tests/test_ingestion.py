import io
import uuid
from decimal import Decimal
from pathlib import Path

import pytest

from app.modules.m4.column_map import normalize_header, resolve_columns
from app.modules.m4.ingestion import IngestionRejected, ingest_csv
from app.modules.m4.validation import CsvFormatError, parse_date, parse_number, read_csv, validate_rows

SAMPLES = Path(__file__).resolve().parent.parent / "sample-data"
MAX = 4_500_000


def sample(name: str) -> bytes:
    return (SAMPLES / name).read_bytes()


class TestHeaderNormalization:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("PO_Number", "po number"),
            ("  PO No. ", "po no"),
            ("Ordered Qty.", "ordered qty"),
            ("INVOICE-UNIT-PRICE", "invoice unit price"),
            ("Material  Description", "material description"),
        ],
    )
    def test_variants_collapse_to_one_form(self, raw, expected):
        assert normalize_header(raw) == expected


class TestColumnResolution:
    def test_canonical_headers_match_exactly(self):
        result = resolve_columns(["po_number", "vendor", "item"])
        assert result.mapping["po_number"].match == "exact"

    def test_real_world_aliases_resolve(self):
        result = resolve_columns(
            ["PO No.", "Supplier Name", "Material Description", "Ordered Qty",
             "Received Qty", "Billed Qty", "PO Rate", "Invoice Rate"]
        )
        assert result.is_usable
        assert result.mapping["po_number"].source_column == "PO No."
        assert result.mapping["grn_quantity"].source_column == "Received Qty"
        assert result.mapping["invoice_unit_price"].source_column == "Invoice Rate"
        assert all(m.match == "alias" for m in result.mapping.values())

    def test_missing_required_columns_are_named(self):
        result = resolve_columns(["Purchase Order", "Supplier", "Description", "Ordered Qty"])
        assert not result.is_usable
        assert "grn_quantity" in result.missing_required
        assert "invoice_unit_price" in result.missing_required

    def test_unrecognised_columns_are_reported_not_dropped(self):
        result = resolve_columns(["po_number", "Cost Centre", "Plant Code"])
        assert "Cost Centre" in result.unmapped_columns
        assert "Plant Code" in result.unmapped_columns

    def test_two_columns_claiming_one_field_surface_as_duplicates(self):
        # "PO Qty" and "Ordered Qty" both mean po_quantity. We must not silently pick one.
        result = resolve_columns(["po_number", "PO Qty", "Ordered Qty"])
        assert result.mapping["po_quantity"].source_column == "PO Qty"
        assert "Ordered Qty" in result.duplicate_targets["po_quantity"]

    def test_manual_override_beats_automatic_match(self):
        headers = ["PO Qty", "Ordered Qty"]
        result = resolve_columns(headers, overrides={"po_quantity": "Ordered Qty"})
        assert result.mapping["po_quantity"].source_column == "Ordered Qty"
        assert result.mapping["po_quantity"].match == "manual"


class TestValueParsing:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("1,200", Decimal("1200")),
            ("₹450.00", Decimal("450.00")),
            ("  99.5  ", Decimal("99.5")),
            ("1200-", Decimal("-1200")),
            ("(1200)", Decimal("-1200")),
            ("", None),
            ("abc", None),
        ],
    )
    def test_numbers(self, raw, expected):
        assert parse_number(raw) == expected

    @pytest.mark.parametrize(
        "raw,iso",
        [
            ("2026-01-12", "2026-01-12"),
            ("12/01/2026", "2026-01-12"),   # day first, as Indian exports use
            ("12-01-2026", "2026-01-12"),
            ("12 Jan 2026", "2026-01-12"),
            ("not a date", None),
        ],
    )
    def test_dates(self, raw, iso):
        parsed = parse_date(raw)
        assert (parsed.isoformat() if parsed else None) == iso


class TestFileLevelValidation:
    def test_empty_file_is_explained(self):
        with pytest.raises(CsvFormatError) as exc:
            read_csv(b"")
        assert "empty" in exc.value.message.lower()
        assert exc.value.hint

    def test_header_only_file_is_explained(self):
        with pytest.raises(CsvFormatError) as exc:
            read_csv(b"po_number,vendor\n")
        assert "no data rows" in exc.value.message.lower()

    def test_excel_bom_does_not_corrupt_the_first_column(self):
        frame = read_csv("﻿po_number,vendor\nPO-1,Acme\n".encode())
        assert list(frame.columns)[0] == "po_number"


class TestRowValidation:
    def _rows(self, name: str):
        frame = read_csv(sample(name))
        mapping = resolve_columns(list(frame.columns))
        return validate_rows(frame, mapping), mapping

    def test_clean_file_produces_no_row_errors(self):
        rows, _ = self._rows("template.csv")
        assert all(r.is_valid for r in rows)

    def test_row_numbers_match_the_spreadsheet_the_user_sees(self):
        rows, _ = self._rows("template.csv")
        assert rows[0].row_number == 2  # row 1 is the header

    def test_every_dirty_row_is_kept_with_a_specific_message(self):
        rows, _ = self._rows("dirty-rows.csv")
        by_row = {r.row_number: r for r in rows}

        assert len(rows) == 5, "invalid rows must be retained, never dropped"

        assert by_row[2].is_valid  # "1,200" and "₹450.00" are parseable
        assert by_row[2].mapped["po_quantity"] == "1200"

        assert "not a number" in by_row[3].errors[0].message
        assert by_row[3].errors[0].source_column == "po_quantity"

        assert any("nothing to reconcile" in e.message for e in by_row[4].errors)
        assert any("negative" in e.message for e in by_row[5].errors)
        assert any("blank" in e.message.lower() for e in by_row[6].errors)


class TestIngestion:
    def test_valid_upload_stages_every_row(self, db):
        outcome = ingest_csv(
            db, content=sample("template.csv"), filename="template.csv",
            actor="tester", max_bytes=MAX,
        )
        assert outcome.run.status == "STAGED"
        assert outcome.run.row_count == 2
        assert outcome.run.valid_row_count == 2
        assert outcome.run.error_row_count == 0

    def test_aliased_headers_are_accepted_without_manual_work(self, db):
        outcome = ingest_csv(
            db, content=sample("messy-headers.csv"), filename="messy.csv",
            actor="tester", max_bytes=MAX,
        )
        assert outcome.run.status == "STAGED"
        assert outcome.mapping.mapping["po_number"].source_column == "PO No."

    def test_missing_columns_reject_with_an_actionable_message(self, db):
        with pytest.raises(IngestionRejected) as exc:
            ingest_csv(
                db, content=sample("invalid.csv"), filename="invalid.csv",
                actor="tester", max_bytes=MAX,
            )
        assert exc.value.mapping is not None
        assert "grn_quantity" in exc.value.mapping.missing_required
        # The partial mapping is still returned so the user can see what we did recognise.
        assert "po_number" in exc.value.mapping.mapping

    def test_rejected_upload_is_still_recorded_for_audit(self, db):
        from app.models import IngestionRun

        marker = f"invalid-{uuid.uuid4().hex[:8]}.csv"
        with pytest.raises(IngestionRejected):
            ingest_csv(
                db, content=sample("invalid.csv"), filename=marker,
                actor="tester", max_bytes=MAX,
            )
        # Scoped to a unique filename: the suite runs against the shared Neon
        # database, so a global query would pick up rows from other sessions.
        run = db.query(IngestionRun).filter_by(source_filename=marker).one()
        assert run.status == "FAILED_VALIDATION"

    def test_oversized_file_is_refused_before_parsing(self, db):
        with pytest.raises(IngestionRejected) as exc:
            ingest_csv(db, content=b"x" * 200, filename="big.csv", actor="t", max_bytes=100)
        assert "upload limit" in exc.value.message

    def test_dirty_file_stages_valid_and_invalid_rows_separately(self, db):
        outcome = ingest_csv(
            db, content=sample("dirty-rows.csv"), filename="dirty.csv",
            actor="tester", max_bytes=MAX,
        )
        assert outcome.run.row_count == 5
        assert outcome.run.error_row_count == 4
        assert outcome.run.valid_row_count == 1


class TestNumericBounds:
    """A value beyond Numeric(18,4) used to pass validation and then fail inside
    Postgres during normalization, surfacing as an opaque 500. It must be caught
    as an ordinary row error instead."""

    def test_oversized_number_is_a_row_error_not_a_crash(self, db):
        header = (
            "po_number,vendor,item,po_quantity,grn_quantity,invoice_quantity,"
            "po_unit_price,invoice_unit_price\n"
        )
        body = "PO-1,Acme,Bearing,999999999999999999,1,1,1,1\n"
        outcome = ingest_csv(
            db, content=(header + body).encode(), filename="huge.csv",
            actor="tester", max_bytes=MAX,
        )
        assert outcome.run.error_row_count == 1
        assert any("too large" in e.message for e in outcome.rows[0].errors)

    def test_largest_storable_value_is_still_accepted(self, db):
        header = (
            "po_number,vendor,item,po_quantity,grn_quantity,invoice_quantity,"
            "po_unit_price,invoice_unit_price\n"
        )
        body = "PO-1,Acme,Bearing,99999999999999.9999,1,1,1,1\n"
        outcome = ingest_csv(
            db, content=(header + body).encode(), filename="edge.csv",
            actor="tester", max_bytes=MAX,
        )
        assert outcome.run.error_row_count == 0


class TestBulkDecisions:
    def test_bulk_applies_one_decision_row_per_result(self, db):
        """Batching the clicks must not batch the audit trail — each line keeps
        its own decision with its own before/after status."""
        from app.models import DecisionLogEntry, ResultStatus
        from app.modules.m4.decisions import record_bulk
        from app.modules.m4.engine import reconcile
        from app.modules.m4.normalize import normalize_run

        header = (
            "po_number,vendor,item,po_quantity,grn_quantity,invoice_quantity,"
            "po_unit_price,invoice_unit_price,invoice_number,tax\n"
        )
        body = (
            "PO-1,Acme,Bearing,100,98,100,450,450,INV-1,8100\n"
            "PO-2,Acme,Seal,50,48,50,120,120,INV-2,1080\n"
        )
        outcome = ingest_csv(db, content=(header + body).encode(), filename="b.csv",
                             actor="t", max_bytes=MAX)
        normalize_run(db, outcome.run)
        recon = reconcile(db, outcome.run)
        open_results = [r for r in recon.results if r.current_status != ResultStatus.AUTO_CLOSED]
        assert len(open_results) == 2

        entries = record_bulk(db, results=open_results, action="APPROVE", actor="clerk")
        db.flush()

        assert len(entries) == 2
        for r in open_results:
            rows = db.query(DecisionLogEntry).filter_by(
                reconciliation_result_id=r.id, is_system=False
            ).all()
            assert len(rows) == 1
            assert rows[0].actor == "clerk"
            # The machine's verdict survives the batch, exactly as for a single decision.
            assert r.system_status == ResultStatus.MISMATCH
            assert r.current_status == ResultStatus.AUTO_CLOSED


class TestExcelUploads:
    """People export from Tally and SAP into Excel and upload the workbook as-is.
    Refusing it, or demanding a tidy sheet starting at A1, sends them back to do
    manual cleanup — which is the work this tool exists to remove."""

    def _clean_workbook(self) -> bytes:
        import pandas as pd
        buf = io.BytesIO()
        pd.read_csv(SAMPLES / "exceptions.csv").to_excel(buf, index=False)
        return buf.getvalue()

    def _messy_workbook(self) -> bytes:
        """A cover sheet, two title rows, a blank spacer, then aliased headers."""
        import openpyxl
        wb = openpyxl.Workbook()
        cover = wb.active
        cover.title = "Cover"
        cover["A1"] = "Vendor Reconciliation Export"

        ws = wb.create_sheet("Data")
        ws["A1"] = "ACME MANUFACTURING PVT LTD"
        ws["A2"] = "Purchase Register — Jan 2026"
        headers = ["PO No.", "Supplier Name", "Material Description", "Ordered Qty",
                   "Received Qty", "Billed Qty", "PO Rate", "Invoice Rate",
                   "Invoice No", "GST Amount", "Order Date"]
        for col, head in enumerate(headers, start=1):
            ws.cell(row=4, column=col, value=head)
        data = [
            ["PO-8001", "Acme Industrial Ltd", "Ball Bearing 6205",
             100, 100, 100, 450, 450, "INV-9001", 8100, "2026-01-12"],
            ["PO-8002", "Bharat Fasteners", "Hex Bolt M12",
             500, 495, 500, 12.5, 14, "INV-9002", 1260, "2026-01-14"],
        ]
        for r, row in enumerate(data, start=5):
            for c, value in enumerate(row, start=1):
                ws.cell(row=r, column=c, value=value)

        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def test_clean_xlsx_is_accepted(self, db):
        outcome = ingest_csv(db, content=self._clean_workbook(), filename="export.xlsx",
                             actor="tester", max_bytes=MAX)
        assert outcome.run.status == "STAGED"
        assert outcome.run.row_count == 11

    def test_header_below_title_rows_is_found(self, db):
        outcome = ingest_csv(db, content=self._messy_workbook(), filename="tally.xlsx",
                             actor="tester", max_bytes=MAX)
        assert outcome.run.status == "STAGED"
        assert outcome.run.row_count == 2
        assert outcome.mapping.mapping["po_number"].source_column == "PO No."

    def test_cover_sheet_is_skipped_for_the_sheet_with_data(self, db):
        outcome = ingest_csv(db, content=self._messy_workbook(), filename="tally.xlsx",
                             actor="tester", max_bytes=MAX)
        # The first sheet holds only a title; the reader must not settle for it.
        assert outcome.run.valid_row_count == 2

    def test_excel_numbers_do_not_arrive_as_floats(self, db):
        """Excel stores 100 as 100.0; a quantity rendered as "100.0" would read
        as dirty data to anyone checking the figures against their own sheet."""
        outcome = ingest_csv(db, content=self._messy_workbook(), filename="tally.xlsx",
                             actor="tester", max_bytes=MAX)
        assert outcome.rows[0].mapped["po_quantity"] == "100"

    def test_excel_dates_lose_their_midnight_component(self, db):
        outcome = ingest_csv(db, content=self._clean_workbook(), filename="export.xlsx",
                             actor="tester", max_bytes=MAX)
        assert outcome.rows[0].mapped["po_date"] == "2026-01-12"

    def test_unsupported_extension_names_what_is_accepted(self, db):
        from app.modules.m4.validation import ACCEPTED_SUFFIXES
        assert ".xlsx" in ACCEPTED_SUFFIXES and ".csv" in ACCEPTED_SUFFIXES
