"""
Turn arbitrary pasted/uploaded input into ingested artifacts.

The corpus is a fixed set, but the strongest demo is throwing a *new* lead at the
pipeline live — paste a messy email, drop a real PDF — and watching it extract.
This builds the `IngestedArtifact`s from raw input by reusing the same format
loaders the corpus uses, so a pasted email is parsed exactly like a corpus one.
The live model call happens in the API layer; this half is deterministic.
"""

from __future__ import annotations

import base64
import tempfile
from pathlib import Path

from .ingest import IngestedArtifact, ingest_file

_EXT_KIND = {
    ".eml": "email",
    ".txt": "transcript",
    ".pdf": "pdf_text",     # falls back to pdf_scanned below if it has no text layer
    ".xlsx": "xlsx",
    ".dxf": "dxf",
}


def kind_for(filename: str) -> str:
    """Guess the artifact kind from a filename. Defaults to email for the common
    paste-an-email case."""
    return _EXT_KIND.get(Path(filename).suffix.lower(), "email")


def build_artifacts(
    filename: str,
    kind: str | None = None,
    *,
    text: str | None = None,
    content_b64: str | None = None,
    artifact_id: str | None = None,
) -> list[IngestedArtifact]:
    """Ingest one raw input into artifacts.

    Provide `text` (a pasted email/transcript) or `content_b64` (an uploaded
    file's bytes). A PDF with no text layer is re-ingested as a scanned document
    so it takes the vision path, just like the corpus's scanned fax.
    """
    if content_b64 is not None:
        data = base64.b64decode(content_b64)
    elif text is not None:
        data = text.encode("utf-8")
    else:
        raise ValueError("provide either text or content_b64")

    kind = kind or kind_for(filename)
    aid = artifact_id or f"RAW::{filename}"
    tmp = Path(tempfile.mkdtemp()) / Path(filename).name
    tmp.write_bytes(data)

    art = ingest_file(tmp, kind, aid)
    if kind == "pdf_text" and not art.text.strip():
        # no extractable text -> it's a scan; re-ingest for the vision path
        art = ingest_file(tmp, "pdf_scanned", aid)
    return [art]
