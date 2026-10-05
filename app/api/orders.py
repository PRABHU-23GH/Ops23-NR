"""Orders API router for Ops23-NR.

Provides clean REST endpoints for order transaction simulation.
No database is introduced yet in Phase 1; responses use structured in-memory datasets.
"""

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/orders", tags=["Orders"])


class OrderItem(BaseModel):
    """Order transaction record schema."""

    id: str = Field(description="Unique order identifier")
    user_id: str = Field(description="Customer/User identifier associated with order")
    amount: float = Field(description="Total monetary value of the order")
    currency: str = Field(default="USD", description="Currency code (e.g. USD)")
    status: str = Field(description="Order processing state (e.g. completed, pending)")
    items_count: int = Field(description="Number of line items in order")
    created_at: str = Field(description="Order placement timestamp (ISO 8601 UTC)")


class OrdersListResponse(BaseModel):
    """Orders collection response schema."""

    total: int = Field(description="Total count of returned orders")
    orders: list[OrderItem] = Field(description="List of order items")


# In-memory mock data (Phase 1 application foundation)
MOCK_ORDERS: list[OrderItem] = [
    OrderItem(
        id="ord-5001",
        user_id="usr-101",
        amount=249.99,
        currency="USD",
        status="completed",
        items_count=2,
        created_at="2026-10-04T09:20:00Z",
    ),
    OrderItem(
        id="ord-5002",
        user_id="usr-102",
        amount=1240.50,
        currency="USD",
        status="completed",
        items_count=5,
        created_at="2026-10-04T11:45:00Z",
    ),
    OrderItem(
        id="ord-5003",
        user_id="usr-103",
        amount=89.00,
        currency="USD",
        status="processing",
        items_count=1,
        created_at="2026-10-05T06:10:00Z",
    ),
]


@router.get(
    "",
    response_model=OrdersListResponse,
    status_code=status.HTTP_200_OK,
    summary="List Orders",
    description="Returns simulated orders dataset for monitoring transaction latency and APM metrics.",
)
async def get_orders() -> OrdersListResponse:
    """Retrieve simulated orders list."""
    return OrdersListResponse(total=len(MOCK_ORDERS), orders=MOCK_ORDERS)
