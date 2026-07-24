"""Account schemas - brokerage accounts a trade can belong to."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AccountBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    broker: str | None = Field(None, max_length=100)
    account_type: str | None = Field(
        None, max_length=50, description="roth / taxable / 401k / hsa / ..."
    )
    risk_profile: str | None = Field(
        None, max_length=50, description="aggressive / moderate / conservative / ..."
    )
    display_order: int = 0


class AccountCreate(AccountBase):
    pass


class AccountUpdate(BaseModel):
    """Explicit null clears a nullable field (model_fields_set semantics)."""

    name: str | None = Field(None, min_length=1, max_length=100)
    broker: str | None = Field(None, max_length=100)
    account_type: str | None = Field(None, max_length=50)
    risk_profile: str | None = Field(None, max_length=50)
    display_order: int | None = None


class AccountResponse(AccountBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class AccountRef(BaseModel):
    """Compact account context embedded in a position or trade response."""

    id: int
    name: str
    account_type: str | None = None

    model_config = ConfigDict(from_attributes=True)
