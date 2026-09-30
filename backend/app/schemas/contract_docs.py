"""Response schema for the contract-docs export."""

from pydantic import BaseModel


class ContractDocResponse(BaseModel):
    filename: str
    stamp: str | None  # version parsed from the doc itself; null if unparseable
    expected_stamp: str  # the code constant this doc's stamp must equal
    stamp_matches: bool
    content: str  # full markdown


class ContractDocsResponse(BaseModel):
    schema_version: str
    advisor_actions_version: str
    handoff_schema: ContractDocResponse
    advisor_actions: ContractDocResponse
