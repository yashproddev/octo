"""The brief requires every result type to be reachable and every exception to
carry a clear explanation. These tests drive real CSV content through the whole
pipeline and assert on the verdict *and* the wording the reviewer will read.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from app.models import ResultStatus
from app.modules.m4.engine import reconcile
from app.modules.m4.ingestion import ingest_csv
from app.modules.m4.normalize import normalize_run

SAMPLES = Path(__file__).resolve().parent.parent / "sample-data"
MAX = 4_500_000

HEADER = (
    "po_number,vendor,item,po_quantity,grn_quantity,invoice_quantity,"
    "po_unit_price,invoice_unit_price,invoice_number,tax\n"
)


def run_csv(db, body: str, tolerances: dict | None = None):
    outcome = ingest_csv(
        db, content=(HEADER + body).encode(), filename="t.csv", actor="tester", max_bytes=MAX
    )
    normalize_run(db, outcome.run)
    recon = reconcile(db, outcome.run, tolerances=tolerances)
    return recon, sorted(recon.results, key=lambda r: r.snapshot["row_number"])


class TestResultTypes:
    def test_clean_line_matches_and_auto_closes(self, db):
        _, results = run_csv(db, "PO-1,Acme,Bearing,100,100,100,450,450,INV-1,8100\n")
        r = results[0]
        assert r.system_status == ResultStatus.MATCHED
        assert r.current_status == ResultStatus.AUTO_CLOSED
        # Auto-closure is recorded as a system decision, not a silent state change.
        assert [d.action for d in r.decisions] == ["AUTO_CLOSE"]
        assert r.decisions[0].is_system is True

    def test_quantity_mismatch(self, db):
        _, results = run_csv(db, "PO-1,Acme,Bearing,100,98,100,450,450,INV-1,8100\n")
        r = results[0]
        assert r.system_status == ResultStatus.MISMATCH
        assert "98" in r.explanation and "100" in r.explanation

    def test_price_mismatch_states_both_figures_and_the_tolerance(self, db):
        _, results = run_csv(db, "PO-1,Acme,Bearing,100,100,100,450,475,INV-1,8550\n")
        r = results[0]
        assert r.system_status == ResultStatus.MISMATCH
        price = next(f for f in r.findings if f["rule_id"] == "R4")
        assert price["expected"] == "450" and price["actual"] == "475"
        assert "outside" in price["explanation"]

    def test_tax_mismatch(self, db):
        # 100 x 450 at 18% should be 8100; the file claims 9500.
        _, results = run_csv(db, "PO-1,Acme,Bearing,100,100,100,450,450,INV-1,9500\n")
        r = results[0]
        assert r.system_status == ResultStatus.MISMATCH
        tax = next(f for f in r.findings if f["rule_id"] == "R5")
        assert Decimal(tax["expected"]) == Decimal("8100")
        assert Decimal(tax["actual"]) == Decimal("9500")

    def test_duplicate_invoice_line(self, db):
        _, results = run_csv(
            db,
            "PO-1,Acme,Bearing,100,100,100,450,450,INV-1,8100\n"
            "PO-1,Acme,Bearing,100,100,100,450,450,INV-1,8100\n",
        )
        assert results[0].system_status == ResultStatus.AUTO_CLOSED or \
               results[0].system_status == ResultStatus.MATCHED
        assert results[1].system_status == ResultStatus.DUPLICATE
        assert "already billed" in results[1].explanation

    def test_multi_line_invoice_is_not_treated_as_duplicate(self, db):
        """Same invoice number, different items — a normal multi-line invoice.
        Flagging this would raise a false exception on most real files."""
        _, results = run_csv(
            db,
            "PO-1,Acme,Bearing,100,100,100,450,450,INV-1,8100\n"
            "PO-1,Acme,Oil Seal,50,50,50,120,120,INV-1,1080\n",
        )
        assert all(r.system_status != ResultStatus.DUPLICATE for r in results)

    def test_missing_po_is_incomplete(self, db):
        _, results = run_csv(db, ",Acme,Bearing,100,100,100,450,450,INV-1,8100\n")
        r = results[0]
        assert r.system_status == ResultStatus.INCOMPLETE
        assert "purchase order" in r.explanation.lower()

    def test_unparseable_quantity_is_incomplete(self, db):
        _, results = run_csv(db, "PO-1,Acme,Bearing,abc,100,100,450,450,INV-1,8100\n")
        assert results[0].system_status == ResultStatus.INCOMPLETE

    def test_within_tolerance_variance_goes_to_review_not_matched(self, db):
        # 0.4% price variance, inside the 0.5% default tolerance.
        _, results = run_csv(db, "PO-1,Acme,Bearing,100,100,100,1000,1004,INV-1,18072\n")
        r = results[0]
        assert r.system_status == ResultStatus.REVIEW
        assert r.current_status == ResultStatus.REVIEW  # tolerated, but not auto-closed

    def test_missing_optional_tax_downgrades_to_review_not_matched(self, db):
        """A skipped check must not read as a clean match — the reviewer needs to
        know something could not be verified."""
        _, results = run_csv(db, "PO-1,Acme,Bearing,100,100,100,450,450,INV-1,\n")
        r = results[0]
        assert r.system_status == ResultStatus.REVIEW
        tax = next(f for f in r.findings if f["rule_id"] == "R5")
        assert tax["skipped"] is True


class TestTolerances:
    def test_widening_price_tolerance_changes_the_verdict(self, db):
        body = "PO-1,Acme,Bearing,100,100,100,1000,1030,INV-1,18540\n"
        _, strict = run_csv(db, body)
        assert strict[0].system_status == ResultStatus.MISMATCH

        _, loose = run_csv(db, body, tolerances={"price_tolerance_pct": "5"})
        assert loose[0].system_status == ResultStatus.REVIEW

    def test_tolerances_are_frozen_onto_the_run(self, db):
        recon, _ = run_csv(
            db, "PO-1,Acme,Bearing,100,100,100,450,450,INV-1,8100\n",
            tolerances={"price_tolerance_pct": "2.5"},
        )
        assert recon.tolerances["price_tolerance_pct"] == "2.5"
        assert recon.rule_version == "m4-v0.1"


class TestExplanations:
    def test_every_exception_has_a_non_empty_explanation(self, db):
        _, results = run_csv(
            db,
            "PO-1,Acme,Bearing,100,98,100,450,450,INV-1,8100\n"
            "PO-2,Acme,Seal,50,50,50,120,140,INV-2,1260\n"
            ",Acme,Belt,10,10,10,320,320,INV-3,576\n"
            "PO-4,Acme,Oil,20,20,20,310,310,INV-4,9999\n",
        )
        for r in results:
            assert r.explanation and r.explanation.strip()
            assert r.explanation != "No explanation available."

    def test_findings_cover_every_rule(self, db):
        _, results = run_csv(db, "PO-1,Acme,Bearing,100,100,100,450,450,INV-1,8100\n")
        rule_ids = {f["rule_id"] for f in results[0].findings}
        assert rule_ids == {"R1", "R2", "R3", "R4", "R5", "R6", "R7"}


class TestRunIndependence:
    def test_the_same_file_can_be_uploaded_twice_without_collision(self, db):
        body = "PO-1,Acme,Bearing,100,100,100,450,450,INV-1,8100\n"
        first, r1 = run_csv(db, body)
        second, r2 = run_csv(db, body)

        assert first.id != second.id
        assert r1[0].id != r2[0].id
        assert r1[0].system_status == r2[0].system_status

    def test_sample_exceptions_file_produces_a_spread_of_statuses(self, db):
        content = (SAMPLES / "exceptions.csv").read_bytes()
        outcome = ingest_csv(db, content=content, filename="exceptions.csv",
                             actor="tester", max_bytes=MAX)
        normalize_run(db, outcome.run)
        recon = reconcile(db, outcome.run)

        statuses = set(recon.status_counts)
        assert ResultStatus.AUTO_CLOSED in statuses
        assert ResultStatus.MISMATCH in statuses
        assert ResultStatus.DUPLICATE in statuses
        assert ResultStatus.INCOMPLETE in statuses
