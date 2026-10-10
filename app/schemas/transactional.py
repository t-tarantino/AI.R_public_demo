"""Pydantic schemas for transactional (historical) entry.

Orders and expenses are entered as a header + nested lines in one request.
Snapshot fields (unit_price, unit_cost) are entered values, never recomputed.

NOTE: the date type is imported as `date_type` because several fields are named
`date`; annotating them with a same-named type breaks resolution.
"""
from datetime import date as date_type
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

Money = Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2)]
Percent = Annotated[Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)]

# Controlled vocabularies, mirrored from the DB CHECK constraints so a bad value
# fails fast as a clear 422 instead of a generic integrity error after a DB round-trip.
OrderState = Literal["draft", "confirmed", "completed", "cancelled"]
Gender = Literal["M", "F", "altro"]


class _Read(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ============================ CUSTOMER ORDER ================================
class OrderItemColorIn(BaseModel):
    color_id: int
    color_percentage: Optional[Percent] = None
    color_surcharge: Optional[Money] = None   # € added for this colour (off-catalog)
    comment: Optional[str] = None


class OrderItemNumberIn(BaseModel):
    required_item_id: int                       # number size (e.g. 'Palloncino numero 80')
    color_id: Optional[int] = None              # None -> silver (gold if the item's mix has gold)
    digit: str = Field(min_length=1, max_length=1, pattern=r"^[0-9]$")
    quantity: int = Field(default=1, gt=0)
    comment: Optional[str] = None


class OrderItemIn(BaseModel):
    composition_id: int
    quantity: int = Field(gt=0)
    unit_price: Money
    discount: Optional[Percent] = None
    comment: Optional[str] = None
    colors: list[OrderItemColorIn] = []
    numbers: list[OrderItemNumberIn] = []

    @model_validator(mode="after")
    def _colour_percentages_within_100(self) -> "OrderItemIn":
        provided = [c.color_percentage for c in self.colors if c.color_percentage is not None]
        if provided and sum(provided) > 100:
            raise ValueError("Colour percentages cannot sum to more than 100.")
        return self


class CustomerOrderCreate(BaseModel):
    location_id: int
    customer_party_id: Optional[int] = None
    state: OrderState = "draft"
    event_type: Optional[str] = None
    celebrated_age: Optional[int] = Field(default=None, ge=0)
    celebrant_gender: Optional[Gender] = None
    date: date_type
    total_price: Money
    comment: Optional[str] = None
    items: list[OrderItemIn] = []


class CustomerOrderHeaderUpdate(BaseModel):
    location_id: Optional[int] = None
    customer_party_id: Optional[int] = None
    state: Optional[OrderState] = None
    event_type: Optional[str] = None
    celebrated_age: Optional[int] = Field(default=None, ge=0)
    celebrant_gender: Optional[Gender] = None
    date: Optional[date_type] = None
    total_price: Optional[Money] = None
    comment: Optional[str] = None


class OrderItemColorRead(_Read):
    order_item_color_id: int
    color_id: int
    color_percentage: Optional[Decimal]
    color_surcharge: Optional[Decimal]
    comment: Optional[str]


class OrderItemNumberRead(_Read):
    order_item_number_id: int
    required_item_id: int
    color_id: int
    digit: str
    quantity: int
    comment: Optional[str]


class OrderItemRead(_Read):
    order_item_id: int
    composition_id: int
    quantity: int
    unit_price: Decimal
    discount: Optional[Decimal]
    comment: Optional[str]
    colors: list[OrderItemColorRead]
    numbers: list[OrderItemNumberRead]


class CustomerOrderRead(_Read):
    customer_order_id: int
    location_id: int
    customer_party_id: Optional[int]
    state: str
    event_type: Optional[str]
    celebrated_age: Optional[int]
    celebrant_gender: Optional[str]
    date: date_type
    total_price: Decimal
    comment: Optional[str]
    items: list[OrderItemRead]


# ================================ EXPENSE ==================================
class ExpenseItemIn(BaseModel):
    product_id: Optional[int] = None
    customer_order_id: Optional[int] = None
    expense_category_id: int
    description: Optional[str] = None
    variant: Optional[str] = None          # digit for number-balloon purchases
    quantity: int = Field(gt=0)
    unit_cost: Money
    comment: Optional[str] = None


class ExpenseCreate(BaseModel):
    paid_by_party_id: int
    paid_to_party_id: int
    date: date_type
    # Optional: if omitted, computed as sum(quantity * unit_cost) of the items.
    total_cost: Optional[Money] = None
    payment_method: Optional[str] = None
    comment: Optional[str] = None
    items: list[ExpenseItemIn] = []


class ExpenseHeaderUpdate(BaseModel):
    paid_by_party_id: Optional[int] = None
    paid_to_party_id: Optional[int] = None
    date: Optional[date_type] = None
    total_cost: Optional[Money] = None
    payment_method: Optional[str] = None
    comment: Optional[str] = None


class ExpenseItemRead(_Read):
    expense_item_id: int
    product_id: Optional[int]
    customer_order_id: Optional[int]
    expense_category_id: int
    description: Optional[str]
    variant: Optional[str]
    quantity: int
    unit_cost: Decimal
    comment: Optional[str]


class ExpenseRead(_Read):
    expense_id: int
    paid_by_party_id: int
    paid_to_party_id: int
    date: date_type
    total_cost: Decimal
    payment_method: Optional[str]
    comment: Optional[str]
    items: list[ExpenseItemRead]


# ================================= WORK ====================================
class WorkCreate(BaseModel):
    party_id: int
    order_ids: list[int] = []          # orders this session covers (M:N); [] = general work
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    break_minutes: Optional[int] = Field(default=None, ge=0)
    tasks_accomplished: Optional[str] = None
    comment: Optional[str] = None


class WorkBulkCreate(BaseModel):
    """One session logged for several workers at once → one Work row per worker."""
    party_ids: list[int] = Field(min_length=1)
    order_ids: list[int] = []
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    break_minutes: Optional[int] = Field(default=None, ge=0)
    tasks_accomplished: Optional[str] = None
    comment: Optional[str] = None


class WorkUpdate(BaseModel):
    party_id: Optional[int] = None
    order_ids: Optional[list[int]] = None   # None = leave links unchanged; [] clears them
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    break_minutes: Optional[int] = Field(default=None, ge=0)
    tasks_accomplished: Optional[str] = None
    comment: Optional[str] = None


class WorkRead(_Read):
    work_id: int
    party_id: int
    order_ids: list[int]
    start_at: Optional[datetime]
    end_at: Optional[datetime]
    break_minutes: Optional[int]
    tasks_accomplished: Optional[str]
    comment: Optional[str]


# =========================== INVENTORY UPDATE ==============================
class InventoryLineIn(BaseModel):
    required_item_id: int
    color_id: Optional[int] = None
    variant: Optional[str] = None
    quantity_change: int = Field(
        description="For manual updates this is a positive magnitude (a recount may be 0); "
                    "the endpoint derives the signed ledger delta.")
    expense_item_id: Optional[int] = None
    customer_order_id: Optional[int] = None
    comment: Optional[str] = None


class InventoryUpdateCreate(BaseModel):
    type: str
    date: date_type
    comment: Optional[str] = None
    items: list[InventoryLineIn] = []


class InventoryLineRead(_Read):
    inventory_update_item_id: int
    required_item_id: int
    color_id: Optional[int]
    variant: Optional[str]
    quantity_change: int
    expense_item_id: Optional[int]
    customer_order_id: Optional[int]
    comment: Optional[str]


class InventoryUpdateRead(_Read):
    inventory_update_id: int
    type: str
    date: date_type
    comment: Optional[str]
    items: list[InventoryLineRead]


# ============================= MONEY TRANSFER ===============================
class MoneyTransferCreate(BaseModel):
    from_party_id: int
    to_party_id: int
    date: date_type
    amount: Money
    payment_method: Optional[str] = None
    comment: Optional[str] = None


class MoneyTransferUpdate(BaseModel):
    from_party_id: Optional[int] = None
    to_party_id: Optional[int] = None
    date: Optional[date_type] = None
    amount: Optional[Money] = None
    payment_method: Optional[str] = None
    comment: Optional[str] = None


class MoneyTransferRead(_Read):
    money_transfer_id: int
    from_party_id: int
    to_party_id: int
    date: date_type
    amount: Decimal
    payment_method: Optional[str]
    comment: Optional[str]