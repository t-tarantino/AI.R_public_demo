"""Batch-import interchange formats (human- and machine-friendly JSON).

Two kinds share the same envelope (`schema_version`, `kind`):
`orders_batch` and `expenses_batch`. The exact, authoritative description of
every field and every check lives in `app/import_spec/RICHIE_IMPORT_SPEC.md`
(it is also what the Richie page hands to the chat as its prompt).

Design: a file is a FAITHFUL transcription of what is written on the registro.
All semantic mapping (COD -> composition, colour code -> id, location/party
-> id, unit price = line_total / qty) happens deterministically in the app.

Fields are intentionally permissive: bad VALUES are reported per row by the
service instead of failing the whole batch with a 422.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel


# ------------------------------- orders ------------------------------------
class OrderBatchNumber(BaseModel):
    digit: Optional[str] = None                # single digit "0".."9" as written
    color: Optional[str] = None               # colour CODE; omit for the silver/gold default
    quantity: Optional[int] = None            # how many of this digit (default 1)


class OrderBatchItem(BaseModel):
    # Composition code exactly as in the price list ("16", "05L", "P01"). A bare
    # number may arrive as a JSON int (16) or string ("16"); both are accepted.
    cod: Optional[int | str] = None
    name: Optional[str] = None                 # human cross-check (name <-> COD)
    qty: Optional[int] = None
    line_total: Optional[Decimal] = None       # EUR written for the whole line (gross)
    colors: list[str] = []                     # colour CODES as written, e.g. ["045","088"]
    # Explicit per-colour surcharge override (EUR), by colour code. Overrides the
    # automatic +10% an off-catalogue colour would otherwise add — e.g. {"101": 0}
    # when an off-catalogue colour was used but NOT surcharged on the registro.
    color_surcharges: dict[str, Decimal] = {}
    numbers: list[OrderBatchNumber] = []       # foil number digits for number compositions
    note: Optional[str] = None


class OrderBatchOrder(BaseModel):
    location: Optional[str] = None             # as written (aliases resolved by the app)
    date: Optional[str] = None                 # "dd/mm/yyyy" | "dd/mm" | "yyyy-mm-dd"
    customer: Optional[str] = None             # party code (sigla) or name; falls back to default_customer
    discount_percent: Optional[Decimal] = None  # this order only; overrides the batch value
    items: list[OrderBatchItem] = []
    stated_total: Optional[Decimal] = None     # gross (pre-discount) order total, for checksum
    comment: Optional[str] = None


class OrdersBatch(BaseModel):
    schema_version: int = 1
    kind: Literal["orders_batch"]
    default_customer: Optional[str] = None     # used by orders that omit "customer"
    discount_percent: Optional[Decimal] = None  # default for orders without their own
    orders: list[OrderBatchOrder]
    stated_gross_total: Optional[Decimal] = None
    stated_net_total: Optional[Decimal] = None


# ------------------------------ expenses -----------------------------------
class ExpenseBatchItem(BaseModel):
    product_code: Optional[str] = None         # product SKU code, if the line buys a catalogue product
    description: Optional[str] = None
    qty: Optional[int] = None
    line_total: Optional[Decimal] = None       # EUR written for the whole line
    category: Optional[str] = None             # expense category name; default "materials" if product_code given
    variant: Optional[str] = None              # digit "0".."9" for number balloons
    note: Optional[str] = None


class ExpenseBatchExpense(BaseModel):
    date: Optional[str] = None
    paid_by: Optional[str] = None              # party code (sigla) or name; falls back to default_paid_by
    paid_to: Optional[str] = None              # supplier/worker code (sigla) or name
    payment_method: Optional[str] = None
    items: list[ExpenseBatchItem] = []
    stated_total: Optional[Decimal] = None     # total written for the whole expense, checksum
    comment: Optional[str] = None


class ExpensesBatch(BaseModel):
    schema_version: int = 1
    kind: Literal["expenses_batch"]
    default_paid_by: Optional[str] = None
    expenses: list[ExpenseBatchExpense]
    stated_total: Optional[Decimal] = None


# ------------------------------ stock --------------------------------------
class StockBatchItem(BaseModel):
    item: Optional[str] = None                  # required_item (material) name as written
    color_code: Optional[str] = None            # colour CODE — required for coloured materials
    color_name: Optional[str] = None            # colour NAME — cross-checked against the code
    variant: Optional[str] = None               # digit "0".."9" for number balloons
    quantity: Optional[int] = None              # magnitude: counted (recount, may be 0) / lost / gifted
    note: Optional[str] = None


class StockBatchUpdate(BaseModel):
    type: Optional[str] = None                  # recount | loss | gift
    date: Optional[str] = None
    comment: Optional[str] = None
    items: list[StockBatchItem] = []


class StockBatch(BaseModel):
    schema_version: int = 1
    kind: Literal["stock_batch"]
    updates: list[StockBatchUpdate]


# ------------------------------- work --------------------------------------
class WorkBatchEntry(BaseModel):
    worker: Optional[str] = None                # party code (sigla) or name; must be a worker
    date: Optional[str] = None                  # the session day; falls back to default_date
    start: Optional[str] = None                 # "HH:MM"
    end: Optional[str] = None                   # "HH:MM"
    break_minutes: Optional[int] = None
    tasks: Optional[str] = None
    comment: Optional[str] = None


class WorkBatch(BaseModel):
    schema_version: int = 1
    kind: Literal["work_batch"]
    default_date: Optional[str] = None
    entries: list[WorkBatchEntry]


# ----------------------------- transfers -----------------------------------
class TransferBatchItem(BaseModel):
    from_party: Optional[str] = None            # payer; falls back to default_from
    to_party: Optional[str] = None              # payee
    date: Optional[str] = None
    amount: Optional[Decimal] = None
    payment_method: Optional[str] = None
    comment: Optional[str] = None


class TransfersBatch(BaseModel):
    schema_version: int = 1
    kind: Literal["transfers_batch"]
    default_from: Optional[str] = None
    transfers: list[TransferBatchItem]
    stated_total: Optional[Decimal] = None


# --- report returned by preview/commit --------------------------------------
class ImportOrderResult(BaseModel):
    index: int
    label: str                 # "Chic · 03/10/2026"
    status: str                # ok | doubt | error | duplicate
    created_order_id: Optional[int] = None
    created_expense_id: Optional[int] = None
    created_id: Optional[int] = None    # generic created-row id (stock / work / transfer)
    contents: str              # human preview of the resolved row
    computed_total: Optional[str] = None
    messages: list[str] = []   # errors / doubts explained


class ImportReport(BaseModel):
    kind: str
    committed: bool            # False = dry-run preview
    counts: dict[str, int]     # ok / doubt / error / duplicate
    computed_gross_total: str
    computed_net_total: str
    stated_gross_total: Optional[str] = None
    stated_net_total: Optional[str] = None
    checksum_ok: Optional[bool] = None
    messages: list[str] = []   # batch-wide notes
    orders: list[ImportOrderResult]
