"""Import all v2 models so that `Base.metadata` is fully populated.

Anything that needs the complete schema (Alembic autogenerate, table creation,
tests) can simply import this package.
"""
from app.db.base import Base
from app.db.models.bom import Product, RequiredItem, Requirement, StockThreshold
from app.db.models.expenses import Expense, ExpenseItem
from app.db.models.inventory import InventoryUpdate, InventoryUpdateItem
from app.db.models.master_data import (
    Color,
    Composition,
    ExpenseCategory,
    Location,
    Party,
)
from app.db.models.orders import (
    CustomerOrder,
    OrderItem,
    OrderItemColor,
    OrderItemNumber,
)
from app.db.models.reports import MonthlyReport, MonthlyReportFile
from app.db.models.system import AuditLog, User
from app.db.models.transfers import MoneyTransfer
from app.db.models.work import Work

__all__ = [
    "AuditLog",
    "Base",
    "Color",
    "Composition",
    "CustomerOrder",
    "Expense",
    "ExpenseCategory",
    "ExpenseItem",
    "InventoryUpdate",
    "InventoryUpdateItem",
    "Location",
    "MonthlyReport",
    "MonthlyReportFile",
    "MoneyTransfer",
    "OrderItem",
    "OrderItemColor",
    "OrderItemNumber",
    "Party",
    "Product",
    "RequiredItem",
    "Requirement",
    "StockThreshold",
    "User",
    "Work",
]