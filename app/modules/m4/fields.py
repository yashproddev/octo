"""Canonical field definitions for an M4 reconciliation dataset.

One CSV row describes a single item across all three documents — what was
ordered, what arrived, and what was billed. The fan-out into separate PO / GRN /
invoice records happens during normalization; this module only describes the
shape the uploaded file must take.
"""

from dataclasses import dataclass, field
from typing import Literal

FieldKind = Literal["string", "number", "date"]


@dataclass(frozen=True)
class FieldSpec:
    name: str
    kind: FieldKind
    required: bool
    label: str
    description: str
    aliases: tuple[str, ...] = field(default_factory=tuple)


FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec(
        "po_number", "string", True, "PO Number",
        "Purchase order reference the line belongs to.",
        ("po no", "po number", "po num", "po", "purchase order", "purchase order number",
         "purchase order no", "po ref", "order number", "order no"),
    ),
    FieldSpec(
        "vendor", "string", True, "Vendor",
        "Supplier name as printed on the order.",
        ("vendor name", "supplier", "supplier name", "party", "party name",
         "vendor description", "seller"),
    ),
    FieldSpec(
        "item", "string", True, "Item",
        "Material or service description for this line.",
        ("item name", "item description", "material", "material description",
         "description", "product", "product name", "part", "part description"),
    ),
    FieldSpec(
        "po_quantity", "number", True, "PO Quantity",
        "Quantity ordered on the purchase order.",
        ("po qty", "po quantity", "ordered qty", "ordered quantity", "order qty",
         "order quantity", "qty ordered", "quantity ordered"),
    ),
    FieldSpec(
        "grn_quantity", "number", True, "GRN Quantity",
        "Quantity actually received against the order.",
        ("grn qty", "grn quantity", "received qty", "received quantity", "gr qty",
         "gr quantity", "qty received", "quantity received", "receipt qty", "grn"),
    ),
    FieldSpec(
        "invoice_quantity", "number", True, "Invoice Quantity",
        "Quantity billed on the vendor invoice.",
        ("invoice qty", "invoice quantity", "billed qty", "billed quantity",
         "qty invoiced", "quantity invoiced", "invoiced qty", "inv qty"),
    ),
    FieldSpec(
        "po_unit_price", "number", True, "PO Unit Price",
        "Agreed price per unit on the purchase order.",
        ("po price", "po rate", "po unit price", "po unit rate", "ordered rate",
         "ordered price", "unit price", "unit rate", "rate"),
    ),
    FieldSpec(
        "invoice_unit_price", "number", True, "Invoice Unit Price",
        "Price per unit charged on the vendor invoice.",
        ("invoice price", "invoice rate", "invoice unit price", "invoice unit rate",
         "billed price", "billed rate", "inv rate", "inv price"),
    ),
    FieldSpec(
        "invoice_number", "string", False, "Invoice Number",
        "Vendor invoice reference. Required for duplicate detection.",
        ("invoice no", "invoice number", "inv no", "inv number", "invoice ref",
         "bill number", "bill no", "bill ref"),
    ),
    FieldSpec(
        "tax", "number", False, "Tax",
        "Tax amount on this invoice line. Enables the tax consistency check.",
        ("tax amount", "tax value", "gst", "gst amount", "vat", "vat amount",
         "tax amt"),
    ),
    FieldSpec(
        "po_date", "date", False, "PO Date", "Date the purchase order was raised.",
        ("po dt", "po date", "order date", "purchase order date", "ordered on"),
    ),
    FieldSpec(
        "grn_date", "date", False, "GRN Date", "Date the goods were received.",
        ("grn dt", "grn date", "gr date", "receipt date", "received date",
         "received on"),
    ),
    FieldSpec(
        "invoice_date", "date", False, "Invoice Date", "Date on the vendor invoice.",
        ("inv date", "invoice dt", "bill date", "invoiced on"),
    ),
    FieldSpec(
        "vendor_code", "string", False, "Vendor Code",
        "Vendor master code, used in preference to the name when present.",
        ("supplier code", "vendor id", "supplier id", "vendor no", "vendor cd"),
    ),
    FieldSpec(
        "item_code", "string", False, "Item Code", "Material or SKU code.",
        ("material code", "material no", "item id", "item no", "sku", "sku code",
         "part number", "part no", "part code"),
    ),
    FieldSpec(
        "currency", "string", False, "Currency",
        "ISO currency code. Captured but never converted.",
        ("curr", "ccy", "currency code"),
    ),
)

BY_NAME: dict[str, FieldSpec] = {f.name: f for f in FIELDS}
REQUIRED_FIELDS: tuple[str, ...] = tuple(f.name for f in FIELDS if f.required)
OPTIONAL_FIELDS: tuple[str, ...] = tuple(f.name for f in FIELDS if not f.required)
