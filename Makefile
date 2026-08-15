.PHONY: install corpus eval record test clean serve build-web build serve-prod

# Install dependencies into the active environment.
install:
	pip install -r requirements.txt

# Regenerate the synthetic corpus from src/corpus/specs.py.
corpus:
	python -m src.corpus.generate --out ./corpus

# Score the pipeline against ground truth, replaying model calls from cache.
# Runs offline with no API key once the cache has been recorded.
eval: corpus
	python -m src.run_corpus --corpus ./corpus

# Record model responses live (needs ANTHROPIC_API_KEY), then score.
# Run this once; commit cache/llm/ so `make eval` stays green offline.
record: corpus
	LLM_MODE=record python -m src.run_corpus --corpus ./corpus --record

# Run the test suite.
test:
	python -m pytest -q

clean:
	rm -rf corpus .pytest_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

# Run the API dev server (factory form; seed via POST /seed once up).
serve:
	uvicorn --factory src.api:create_app --reload

# Build the React SPA into web/dist (needs Node).
build-web:
	cd web && npm ci && npm run build

# One-shot production build: deps + corpus + SPA. Run once on the box.
build: install corpus build-web

# Single-origin production server: API under /api, the built SPA at /.
# Seeds the corpus on startup (replays the committed cache — no API key needed).
# Bind localhost; put a reverse proxy (Caddy / Cloudflare Tunnel) in front for TLS.
serve-prod:
	uvicorn --factory src.api:create_site_app --host 127.0.0.1 --port 8000
