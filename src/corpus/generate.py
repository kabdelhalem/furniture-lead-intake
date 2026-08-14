"""
Generate the corpus.

    python -m src.corpus.generate --out ./corpus

Produces:
    corpus/inbox/          the messy artifacts the pipeline consumes
    corpus/ground_truth/   one JSON per lead, dotted-path -> expected value
    corpus/manifest.json   index + coverage report

Attachments render before their parent email so the .eml embeds real bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from .render import RENDERERS
from .specs import SPECS, coverage_report

ATTACHMENT_KINDS = {"pdf_text", "pdf_scanned", "xlsx", "dxf"}


def generate(out_dir: Path) -> dict:
    inbox = out_dir / "inbox"
    truth_dir = out_dir / "ground_truth"
    inbox.mkdir(parents=True, exist_ok=True)
    truth_dir.mkdir(parents=True, exist_ok=True)

    manifest: dict = {"leads": [], "coverage": coverage_report()}

    for spec in SPECS:
        # attachments first, emails last
        ordered = sorted(spec.artifacts, key=lambda a: a.kind == "email")
        written: list[dict] = []

        for art in ordered:
            path = inbox / art.name
            renderer = RENDERERS[art.kind]
            if art.kind == "email":
                renderer(art.payload, path, inbox)
            else:
                renderer(art.payload, path)

            written.append({
                "artifact_id": f"{spec.id}::{art.name}",
                "kind": art.kind,
                "filename": art.name,
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()[:16],
            })

        truth_payload = {
            "lead_id": spec.id,
            "label": spec.label,
            "tests": spec.tests,
            "notes": spec.notes,
            "channel": spec.channel,
            "expect_low_confidence": spec.expect_low_confidence,
            "fields": spec.truth,
        }
        (truth_dir / f"{spec.id}.json").write_text(
            json.dumps(truth_payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        manifest["leads"].append({
            "lead_id": spec.id,
            "label": spec.label,
            "channel": spec.channel,
            "tests": spec.tests,
            "artifacts": written,
            "n_truth_fields": len(spec.truth),
            "n_expected_flags": len(spec.expect_low_confidence),
        })

    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="./corpus", type=Path)
    args = ap.parse_args()

    m = generate(args.out)

    n_art = sum(len(l["artifacts"]) for l in m["leads"])
    n_fields = sum(l["n_truth_fields"] for l in m["leads"])
    n_flags = sum(l["n_expected_flags"] for l in m["leads"])

    print(f"{len(m['leads'])} leads · {n_art} artifacts · "
          f"{n_fields} labelled fields · {n_flags} expected-uncertain fields")
    print(f"\nwrote -> {args.out.resolve()}\n")
    print("coverage:")
    for test, ids in m["coverage"].items():
        print(f"  {test:<32} {', '.join(ids)}")


if __name__ == "__main__":
    main()
