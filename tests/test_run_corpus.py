"""
Tests for the corpus runner.

The model responses aren't cached in the test environment, so these verify the
plumbing and the graceful-degradation contract: ingestion feeds the pipeline
correctly, and an empty cache yields a clean "nothing to score" outcome (every
lead reported uncached) rather than a crash.
"""

from __future__ import annotations

import pathlib

import pytest

from src.llm import LLM, LLMMode
from src.run_corpus import ingest_lead, main, run_corpus

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def corpus_dir(tmp_path_factory) -> pathlib.Path:
    # Curated-only (15 leads) so counts are deterministic regardless of whether
    # the synthetic volume leads have been recorded. Renders cache-compatibly.
    d = tmp_path_factory.mktemp("corpus")
    from src.corpus.generate import generate
    generate(d, synthetic=0)
    return d


def test_ingest_lead_loads_all_artifacts_email_first(corpus_dir):
    import json
    manifest = json.loads((corpus_dir / "manifest.json").read_text())
    l014 = next(l for l in manifest["leads"] if l["lead_id"] == "L014")  # email + pdf + xlsx
    artifacts = ingest_lead(l014, corpus_dir / "inbox")
    assert len(artifacts) == len(l014["artifacts"])
    assert artifacts[0].kind == "email"                    # email sorted first
    assert {a.kind for a in artifacts} == {"email", "pdf_text", "xlsx"}


def test_empty_cache_degrades_gracefully(corpus_dir, tmp_path):
    # A replay-mode LLM pointed at an empty cache: every lead is uncached, and
    # the run reports that instead of raising.
    factory = lambda: LLM(mode=LLMMode.REPLAY, cache_dir=tmp_path)
    predicted, uncached, totals = run_corpus(corpus_dir, llm_factory=factory)
    assert predicted == {}
    assert set(uncached) == {f"L{n:03d}" for n in range(1, 16)}
    assert totals.model_calls == 0


def test_main_prints_record_guidance_when_no_cache(corpus_dir, tmp_path, capsys, monkeypatch):
    # Force the default LLM to use an empty cache dir.
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_MODE", "replay")
    rc = main(["--corpus", str(corpus_dir)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Record them once" in out
