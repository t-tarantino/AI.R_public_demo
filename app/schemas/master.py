"""Pydantic schemas for the master-data CRUD API.

Naming convention: <Entity>Read / <Entity>Create / <Entity>Update.
Update schemas have every field optional (PATCH semantics: only sent fields
change). Decimal fields accept "12.5" or 12.5 and are validated for range.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

Money = Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2)]
Qty = Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=2)]


class _Read(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- party -------------------------------------------------------------------
class PartyBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    code_nickname: str | None = Field(default=None, max_length=50)
    is_customer: bool = False
    is_supplier: bool = False
    is_worker: bool = False
    is_business: bool = False
    credit_hours: Decimal = Field(default=Decimal("0"), ge=0, max_digits=6, decimal_places=2)
    hidden_from_ranking: bool = False
    category: str | None = Field(default=None, max_length=100)
    phone: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=200)
    website: str | None = Field(default=None, max_length=300)
    comment: str | None = None


class PartyCreate(PartyBase):
    # Role validation applies only on create (reads must return data as-is).
    @model_validator(mode="after")
    def at_least_one_role(self):
        if not (self.is_customer or self.is_supplier or self.is_worker or self.is_business):
            raise ValueError("A party must have at least one role (customer/supplier/worker/business).")
        return self


class PartyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    code_nickname: str | None = None
    is_customer: bool | None = None
    is_supplier: bool | None = None
    is_worker: bool | None = None
    is_business: bool | None = None
    credit_hours: Decimal | None = Field(default=None, ge=0, max_digits=6, decimal_places=2)
    hidden_from_ranking: bool | None = None
    category: str | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    comment: str | None = None


class PartyRead(_Read, PartyBase):
    party_id: int


# --- location ----------------------------------------------------------------
class LocationBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    address: str | None = Field(default=None, max_length=400)
    phone: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=200)
    active: bool = True
    comment: str | None = None


class LocationCreate(LocationBase):
    pass


class LocationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    active: bool | None = None
    comment: str | None = None


class LocationRead(_Read, LocationBase):
    location_id: int


# --- color -------------------------------------------------------------------
class ColorBase(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=100)
    type: str | None = Field(default=None, max_length=50)
    active: bool = True
    in_catalog: bool = True
    swatch_hex: str | None = Field(default=None, max_length=7)
    comment: str | None = None


class ColorCreate(ColorBase):
    pass


class ColorUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=50)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    type: str | None = None
    active: bool | None = None
    in_catalog: bool | None = None
    swatch_hex: str | None = Field(default=None, max_length=7)
    comment: str | None = None


class ColorRead(_Read, ColorBase):
    color_id: int


# --- composition -------------------------------------------------------------
class CompositionBase(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    standard_price: Money
    estimated_working_time: int | None = Field(default=None, ge=0)
    active: bool = True
    comment: str | None = None


class CompositionCreate(CompositionBase):
    pass


class CompositionUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=50)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    standard_price: Money | None = None
    estimated_working_time: int | None = Field(default=None, ge=0)
    active: bool | None = None
    comment: str | None = None


class CompositionRead(_Read, CompositionBase):
    composition_id: int


# --- expense_category --------------------------------------------------------
class ExpenseCategoryBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ExpenseCategoryCreate(ExpenseCategoryBase):
    pass


class ExpenseCategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)


class ExpenseCategoryRead(_Read, ExpenseCategoryBase):
    expense_category_id: int


# --- required_item -----------------------------------------------------------
class RequiredItemBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    type: str | None = Field(default=None, max_length=100)
    dimension: str | None = Field(default=None, max_length=100)
    unit: str = Field(default="piece", min_length=1, max_length=30)
    used_color: bool = False
    is_number: bool = False
    minimum_safe_quantity: int | None = Field(default=None, ge=0)
    comment: str | None = None


class RequiredItemCreate(RequiredItemBase):
    pass


class RequiredItemUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    type: str | None = None
    dimension: str | None = None
    unit: str | None = Field(default=None, min_length=1, max_length=30)
    used_color: bool | None = None
    is_number: bool | None = None
    minimum_safe_quantity: int | None = Field(default=None, ge=0)
    comment: str | None = None


class RequiredItemRead(_Read, RequiredItemBase):
    required_item_id: int


# --- product -----------------------------------------------------------------
class ProductBase(BaseModel):
    required_item_id: int
    color_id: int | None = None
    variant: str | None = Field(default=None, max_length=20)  # digit for foil numbers, else empty
    product_code: str | None = Field(default=None, max_length=100)
    product_link: str | None = Field(default=None, max_length=500)
    is_first_choice: bool = False  # preferred SKU to reorder for its stock cell
    name: str = Field(min_length=1, max_length=200)
    package_quantity: int = Field(default=1, gt=0)  # pieces per purchased unit (pack size)
    default_price: Money | None = None  # usual cost per purchased unit; pre-fills & sanity-checks expenses
    active: bool = True
    comment: str | None = None


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    required_item_id: int | None = None
    color_id: int | None = None
    variant: str | None = None
    product_code: str | None = None
    product_link: str | None = None
    is_first_choice: bool | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    package_quantity: int | None = Field(default=None, gt=0)
    default_price: Money | None = None
    active: bool | None = None
    comment: str | None = None


class ProductRead(_Read, ProductBase):
    product_id: int


# --- stock_threshold ---------------------------------------------------------
class StockThresholdBase(BaseModel):
    required_item_id: int
    color_id: int | None = None
    variant: str | None = Field(default=None, max_length=20)
    minimum_quantity: int = Field(ge=0)
    comment: str | None = None


class StockThresholdCreate(StockThresholdBase):
    pass


class StockThresholdUpdate(BaseModel):
    required_item_id: int | None = None
    color_id: int | None = None
    variant: str | None = None
    minimum_quantity: int | None = Field(default=None, ge=0)
    comment: str | None = None


class StockThresholdRead(_Read, StockThresholdBase):
    stock_threshold_id: int


# --- BOM (composition requirements) ------------------------------------------
class BomLine(BaseModel):
    required_item_id: int
    quantity: Qty
    comment: str | None = None


class BomLineRead(_Read):
    requirement_id: int
    required_item_id: int
    quantity: Decimal
    comment: str | None = None