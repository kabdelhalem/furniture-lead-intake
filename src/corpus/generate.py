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
from .synth import synth_specs

ATTACHMENT_KINDS = {"pdf_text", "pdf_scanned", "xlsx", "dxf"}


def generate(out_dir: Path, synthetic: int = 90) -> dict:
    inbox = out_dir / "inbox"
    truth_dir = out_dir / "ground_truth"
    inbox.mkdir(parents=True, exist_ok=True)
    truth_dir.mkdir(parents=True, exist_ok=True)

    # 15 curated failure-mode leads (the scored eval backbone) + N procedurally
    # generated volume leads (demo realism; curated=False, excluded from scoring).
    specs = SPECS + synth_specs(synthetic)
    manifest: dict = {"leads": [], "coverage": coverage_report()}

    for spec in specs:
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
            "curated": spec.curated,
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
            "curated": spec.curated,
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
    ap.add_argument("--synthetic", default=90, type=int,
                    help="number of procedurally generated volume leads (default 90)")
    args = ap.parse_args()

    m = generate(args.out, synthetic=args.synthetic)

    n_art = sum(len(l["artifacts"]) for l in m["leads"])
    curated = [l for l in m["leads"] if l.get("curated", True)]
    n_fields = sum(l["n_truth_fields"] for l in curated)
    n_flags = sum(l["n_expected_flags"] for l in curated)

    print(f"{len(m['leads'])} leads ({len(curated)} curated + "
          f"{len(m['leads'])-len(curated)} synthetic) · {n_art} artifacts")
    print(f"scored backbone: {len(curated)} curated · {n_fields} labelled fields · "
          f"{n_flags} expected-uncertain fields")
    print(f"\nwrote -> {args.out.resolve()}\n")
    print("coverage:")
    for test, ids in m["coverage"].items():
        print(f"  {test:<32} {', '.join(ids)}")


if __name__ == "__main__":
    main()
