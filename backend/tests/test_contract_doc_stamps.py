"""The version stamps in the published contract docs must match the code constants."""

import re
from pathlib import Path

from app.schemas.context_pack import ADVISOR_ACTIONS_VERSION, SCHEMA_VERSION

# backend/tests/<this file> -> repo root is three parents up; independent of cwd.
DOCS_DIR = Path(__file__).resolve().parents[2] / "docs" / "api"


def _read(name: str) -> str:
    path = DOCS_DIR / name
    assert path.is_file(), f"contract doc missing: {path}"
    return path.read_text(encoding="utf-8")


def test_handoff_schema_h1_matches_schema_version():
    first_line = _read("handoff-schema.md").splitlines()[0]
    match = re.fullmatch(r"# .*\(v(\d+\.\d+)\)\s*", first_line)
    assert match, f"no (vX.Y) stamp in handoff-schema.md H1: {first_line!r}"
    assert match.group(1) == SCHEMA_VERSION


def test_advisor_actions_stamp_matches_actions_version():
    # advisor-actions.md carries its stamp in the header block under the H1, not in the H1.
    text = _read("advisor-actions.md")
    assert text.splitlines()[0].startswith("# "), "advisor-actions.md must open with an H1"
    header = "\n".join(text.splitlines()[:6])
    match = re.search(r"\*\*`advisor_actions_version`:\s*(\d+\.\d+)\*\*", header)
    assert match, "no advisor_actions_version stamp in advisor-actions.md header"
    assert match.group(1) == ADVISOR_ACTIONS_VERSION
