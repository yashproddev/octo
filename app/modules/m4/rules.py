"""Deterministic reconciliation rules and their explanations.

No model is involved anywhere in this file. Every verdict is a comparison
against a configured tolerance, and every explanation is a template filled with
the actual numbers — because a human has to sign off on these and must be able
to see precisely why the system said what it said.
"""

from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation

RULE_VERSION = "m4-v0.1"


@dataclass(frozen=True)
class Tolerances:
    qty_tolerance_abs: Decimal = Decimal("0")
    qty_tolerance_pct: Decimal = Decimal("0")
    price_tolerance_pct: Decimal = Decimal("0.5")
    tax_tolerance_abs: Decimal = Decimal("1.00")
    expected_tax_rate: Decimal = Decimal("0.18")
    auto_close_matched: bool = True

    @classmethod
    def from_dict(cls, raw: dict | None) -> "Tolerances":
        if not raw:
            return cls()
        values: dict = {}
        for key, default in cls().as_dict().items():
            if key not in raw or raw[key] is None:
                continue
            if key == "auto_close_matched":
                values[key] = bool(raw[key])
                continue
            try:
                values[key] = Decimal(str(raw[key]))
            except (InvalidOperation, ValueError):
                continue
        return cls(**values)

    def as_dict(self) -> dict:
        return {
            "qty_tolerance_abs": str(self.qty_tolerance_abs),
            "qty_tolerance_pct": str(self.qty_tolerance_pct),
            "price_tolerance_pct": str(self.price_tolerance_pct),
            "tax_tolerance_abs": str(self.tax_tolerance_abs),
            "expected_tax_rate": str(self.expected_tax_rate),
            "auto_close_matched": self.auto_close_matched,
        }


@dataclass
class Finding:
    rule_id: str
    label: str
    passed: bool
    severity: str = "info"          # info | review | hard
    expected: str | None = None
    actual: str | None = None
    variance: str | None = None
    variance_pct: str | None = None
    tolerance: str | None = None
    explanation: str = ""
    skipped: bool = False
    skip_reason: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class RuleOutcome:
    findings: list[Finding] = field(default_factory=list)

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)

    @property
    def hard_failures(self) -> list[Finding]:
        return [f for f in self.findings if not f.passed and not f.skipped and f.severity == "hard"]

    @property
    def review_flags(self) -> list[Finding]:
        return [f for f in self.findings if not f.passed and not f.skipped and f.severity == "review"]

    @property
    def skipped(self) -> list[Finding]:
        return [f for f in self.findings if f.skipped]


def _fmt(value: Decimal | None) -> str:
    if value is None:
        return "—"
    normalized = value.normalize()
    text = format(normalized, "f")
    return text


def _pct(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator == 0:
        return None
    return (abs(numerator) / abs(denominator) * Decimal("100")).quantize(Decimal("0.0001"))


def financial_exposure(
    po_qty: Decimal | None,
    grn_qty: Decimal | None,
    inv_qty: Decimal | None,
    po_price: Decimal | None,
    inv_price: Decimal | None,
    tax: Decimal | None,
    tol: Tolerances,
    is_duplicate: bool = False,
) -> Decimal | None:
    """What this line would overpay if the invoice were paid exactly as billed.

    A count of exceptions is an operational metric; this is the one finance
    actually acts on. The entitled amount is the quantity genuinely received
    (never more than was ordered) at the agreed price — anything billed above
    that, tax included, is money at risk.

    Returns None when the inputs are too incomplete to state a number honestly,
    which is different from returning zero.
    """
    if inv_qty is None or inv_price is None:
        return None

    billed_value = inv_qty * inv_price
    billed_tax = tax if tax is not None else billed_value * tol.expected_tax_rate

    # A duplicate line is wrong in its entirety: the whole amount is paid twice.
    if is_duplicate:
        return (billed_value + billed_tax).quantize(Decimal("0.01"))

    if po_price is None:
        return None

    # Cannot legitimately be billed for more than was received, nor more than ordered.
    candidates = [q for q in (grn_qty, po_qty) if q is not None]
    if not candidates:
        return None
    entitled_qty = min(candidates)

    entitled_value = entitled_qty * po_price
    entitled_tax = entitled_value * tol.expected_tax_rate

    return ((billed_value + billed_tax) - (entitled_value + entitled_tax)).quantize(
        Decimal("0.01")
    )


def compare_quantity(
    rule_id: str,
    label: str,
    left_label: str,
    left: Decimal | None,
    right_label: str,
    right: Decimal | None,
    tol: Tolerances,
) -> Finding:
    if left is None or right is None:
        return Finding(
            rule_id, label, passed=True, skipped=True,
            skip_reason=f"{left_label if left is None else right_label} was not supplied.",
            explanation=f"{label} could not be checked because a quantity is missing.",
        )

    diff = right - left
    pct = _pct(diff, left)
    allowed_abs = tol.qty_tolerance_abs
    allowed_pct = tol.qty_tolerance_pct
    within = abs(diff) <= allowed_abs or (pct is not None and pct <= allowed_pct)

    if diff == 0:
        explanation = f"{right_label} matches {left_label} exactly at {_fmt(left)}."
        severity, passed = "info", True
    elif within:
        explanation = (
            f"{right_label} is {_fmt(right)} against {left_label} {_fmt(left)}, a difference of "
            f"{_fmt(diff)} ({_fmt(pct) if pct is not None else '—'}%) — inside the allowed tolerance, "
            "but worth a look."
        )
        severity, passed = "review", False
    else:
        direction = "exceeds" if diff > 0 else "falls short of"
        explanation = (
            f"{right_label} {_fmt(right)} {direction} {left_label} {_fmt(left)} by {_fmt(abs(diff))} "
            f"({_fmt(pct) if pct is not None else '—'}%), outside the "
            f"{_fmt(allowed_abs)}-unit / {_fmt(allowed_pct)}% tolerance."
        )
        severity, passed = "hard", False

    return Finding(
        rule_id, label, passed=passed, severity=severity,
        expected=_fmt(left), actual=_fmt(right), variance=_fmt(diff),
        variance_pct=_fmt(pct) if pct is not None else None,
        tolerance=f"{_fmt(allowed_abs)} units / {_fmt(allowed_pct)}%",
        explanation=explanation,
    )


def compare_price(po_price: Decimal | None, invoice_price: Decimal | None, tol: Tolerances) -> Finding:
    label = "PO price vs invoice price"
    if po_price is None or invoice_price is None:
        return Finding(
            "R4", label, passed=True, skipped=True,
            skip_reason="A unit price was not supplied.",
            explanation="Price could not be checked because a unit price is missing.",
        )

    diff = invoice_price - po_price
    pct = _pct(diff, po_price)

    if diff == 0:
        return Finding(
            "R4", label, passed=True, severity="info",
            expected=_fmt(po_price), actual=_fmt(invoice_price), variance="0",
            tolerance=f"{_fmt(tol.price_tolerance_pct)}%",
            explanation=f"Invoice unit price matches the PO exactly at {_fmt(po_price)}.",
        )

    within = pct is not None and pct <= tol.price_tolerance_pct
    direction = "above" if diff > 0 else "below"
    if within:
        explanation = (
            f"Invoice unit price {_fmt(invoice_price)} is {_fmt(abs(diff))} {direction} the PO price "
            f"{_fmt(po_price)} ({_fmt(pct)}%) — inside the {_fmt(tol.price_tolerance_pct)}% tolerance."
        )
        severity = "review"
    else:
        explanation = (
            f"Invoice unit price {_fmt(invoice_price)} is {_fmt(abs(diff))} {direction} the PO price "
            f"{_fmt(po_price)} ({_fmt(pct) if pct is not None else '—'}%), outside the "
            f"{_fmt(tol.price_tolerance_pct)}% tolerance."
        )
        severity = "hard"

    return Finding(
        "R4", label, passed=False, severity=severity,
        expected=_fmt(po_price), actual=_fmt(invoice_price), variance=_fmt(diff),
        variance_pct=_fmt(pct) if pct is not None else None,
        tolerance=f"{_fmt(tol.price_tolerance_pct)}%",
        explanation=explanation,
    )


def check_tax(
    invoice_qty: Decimal | None,
    invoice_price: Decimal | None,
    tax: Decimal | None,
    tol: Tolerances,
) -> Finding:
    label = "Tax consistency"
    if tax is None:
        return Finding(
            "R5", label, passed=True, skipped=True,
            skip_reason="No tax column was supplied.",
            explanation="Tax was not checked because the file carries no tax amount.",
        )
    if invoice_qty is None or invoice_price is None:
        return Finding(
            "R5", label, passed=True, skipped=True,
            skip_reason="Invoice quantity or price missing.",
            explanation="Tax could not be checked without an invoice value to compute it from.",
        )

    line_value = invoice_qty * invoice_price
    expected = (line_value * tol.expected_tax_rate).quantize(Decimal("0.01"))
    diff = tax - expected
    rate_pct = (tol.expected_tax_rate * Decimal("100")).normalize()

    if abs(diff) <= tol.tax_tolerance_abs:
        return Finding(
            "R5", label, passed=True, severity="info",
            expected=_fmt(expected), actual=_fmt(tax), variance=_fmt(diff),
            tolerance=_fmt(tol.tax_tolerance_abs),
            explanation=(
                f"Tax of {_fmt(tax)} matches {_fmt(rate_pct)}% of the invoice value "
                f"{_fmt(line_value)} (expected {_fmt(expected)})."
            ),
        )

    return Finding(
        "R5", label, passed=False, severity="hard",
        expected=_fmt(expected), actual=_fmt(tax), variance=_fmt(diff),
        variance_pct=_fmt(_pct(diff, expected)) if expected else None,
        tolerance=_fmt(tol.tax_tolerance_abs),
        explanation=(
            f"Tax of {_fmt(tax)} differs from the expected {_fmt(expected)} "
            f"({_fmt(rate_pct)}% of invoice value {_fmt(line_value)}) by {_fmt(abs(diff))}, "
            f"outside the {_fmt(tol.tax_tolerance_abs)} tolerance."
        ),
    )
