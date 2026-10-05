"""Users API router for Ops23-NR.

Provides clean REST endpoints for user management simulation.
No database is introduced yet in Phase 1; responses use structured in-memory datasets.
"""

from datetime import datetime, timezone
from fastapi import APIRouter, status
from pydantic import BaseModel, EmailStr, Field

router = APIRouter(prefix="/api/users", tags=["Users"])


class UserItem(BaseModel):
    """User record schema."""

    id: str = Field(description="Unique user identifier")
    name: str = Field(description="Full name of the user")
    email: str = Field(description="User primary email address")
    role: str = Field(description="Role designation within the organization")
    status: str = Field(description="Account status (e.g., active, suspended)")
    created_at: str = Field(description="Account creation timestamp (ISO 8601 UTC)")


class UsersListResponse(BaseModel):
    """Users collection response schema."""

    total: int = Field(description="Total count of returned users")
    users: list[UserItem] = Field(description="List of user items")


# In-memory mock data (Phase 1 application foundation)
MOCK_USERS: list[UserItem] = [
    UserItem(
        id="usr-101",
        name="Sarah Connor",
        email="sarah.connor@example.com",
        role="Site Reliability Engineer",
        status="active",
        created_at="2026-01-15T08:30:00Z",
    ),
    UserItem(
        id="usr-102",
        name="Alex Murphy",
        email="alex.murphy@example.com",
        role="Cloud Architect",
        status="active",
        created_at="2026-02-20T10:15:00Z",
    ),
    UserItem(
        id="usr-103",
        name="Ellen Ripley",
        email="ellen.ripley@example.com",
        role="DevOps Lead",
        status="active",
        created_at="2026-03-05T14:45:00Z",
    ),
]


@router.get(
    "",
    response_model=UsersListResponse,
    status_code=status.HTTP_200_OK,
    summary="List Users",
    description="Returns simulated users dataset for testing application endpoints and observability traces.",
)
async def get_users() -> UsersListResponse:
    """Retrieve simulated users list."""
    return UsersListResponse(total=len(MOCK_USERS), users=MOCK_USERS)
