"""AccountLink schemas - the Schwab-hash -> IC-account mapping (§1/§4)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AccountLinkCreate(BaseModel):
    """Body for linking a broker hash to an account.

    ``account_id`` is taken from the URL path, not here. ``confirm`` is the one
    explicit confirmation gate from §4: linking a hash to an account that
    already holds trades treats all of them as this account's reconciliation
    baseline, so it must be an intentional step.
    """

    account_hash: str = Field(..., min_length=1, max_length=128)
    source: str = Field("schwab_api", max_length=50)
    confirm: bool = Field(
        False,
        description=(
            "Required (true) when the target account already has trades - "
            "acknowledges they become this account's reconciliation baseline."
        ),
    )


class AccountLinkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_hash: str
    source: str
    account_id: int | None
    status: str
    created_at: datetime
    updated_at: datetime
