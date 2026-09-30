"""Advisor contract docs, served from the running app.

The two markdown contracts (``handoff-schema.md`` and ``advisor-actions.md``)
live in ``docs/api/``. Each carries a version stamp that must equal the
matching constant the context pack emits; serving them from the deployed
process means a client always gets the docs for the version it is talking to.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings
from app.schemas.context_pack import ADVISOR_ACTIONS_VERSION, SCHEMA_VERSION

HANDOFF_SCHEMA_DOC = "handoff-schema.md"
ADVISOR_ACTIONS_DOC = "advisor-actions.md"

# handoff-schema.md: the H1 ends in "(vMAJOR.MINOR)".
_HANDOFF_STAMP = re.compile(r"^#\s.*\(v(\d+\.\d+)\)\s*$", re.MULTILINE)
# advisor-actions.md: "**`advisor_actions_version`: MAJOR.MINOR**".
_ACTIONS_STAMP = re.compile(r"\*\*`advisor_actions_version`:\s*(\d+\.\d+)\*\*")


class ContractDocsUnavailable(Exception):
    """A contract doc could not be read from the configured directory."""


@dataclass(frozen=True)
class ContractDoc:
    filename: str
    stamp: str | None
    expected_stamp: str
    content: str

    @property
    def stamp_matches(self) -> bool:
        return self.stamp == self.expected_stamp


def parse_handoff_schema_stamp(text: str) -> str | None:
    match = _HANDOFF_STAMP.search(text)
    return match.group(1) if match else None


def parse_advisor_actions_stamp(text: str) -> str | None:
    match = _ACTIONS_STAMP.search(text)
    return match.group(1) if match else None


def contract_docs_dir() -> Path:
    configured = settings.CONTRACT_DOCS_DIR.strip()
    if configured:
        return Path(configured)
    # backend/app/services/contract_docs.py -> repo root is parents[3].
    return Path(__file__).resolve().parents[3] / "docs" / "api"


def _read(directory: Path, filename: str, expected: str, parse) -> ContractDoc:
    try:
        content = (directory / filename).read_text(encoding="utf-8")
    except OSError as exc:
        raise ContractDocsUnavailable(
            f"Contract doc {filename} is not available on this deployment"
        ) from exc
    return ContractDoc(
        filename=filename,
        stamp=parse(content),
        expected_stamp=expected,
        content=content,
    )


def load_contract_docs() -> tuple[ContractDoc, ContractDoc]:
    """Return (handoff-schema, advisor-actions); raise if either is unreadable."""
    directory = contract_docs_dir()
    return (
        _read(directory, HANDOFF_SCHEMA_DOC, SCHEMA_VERSION, parse_handoff_schema_stamp),
        _read(
            directory, ADVISOR_ACTIONS_DOC, ADVISOR_ACTIONS_VERSION, parse_advisor_actions_stamp
        ),
    )
