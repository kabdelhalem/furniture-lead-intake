.PHONY: install corpus eval record test clean serve build-web build serve-prod redeploy

# Virtualenv to build/run against (override with VENV=... if yours lives elsewhere).
VENV ?= .venv

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
# Override the port to avoid colliding with other services: make serve-prod PORT=8012
PORT ?= 8000
serve-prod:
	uvicorn --factory src.api:create_site_app --host 127.0.0.1 --port $(PORT)

# One-command deploy on the box: pull, rebuild what a change may have touched
# (deps, corpus, SPA), then restart the service and health-check it. Uses the
# venv explicitly so it works whether or not it's activated. Needs sudo for the
# restart, and the furniture-leads systemd unit from deploy/Step 2.
# Override the service/port if you named them differently: make redeploy SVC=... PORT=...
SVC ?= furniture-leads
redeploy:
	git pull --ff-only
	$(VENV)/bin/pip install -q -r requirements.txt
	$(VENV)/bin/python -m src.corpus.generate --out ./corpus
	cd web && npm ci && npm run build
	sudo systemctl restart $(SVC)
	@sleep 3 && curl -fsS localhost:8080/api/health && echo "  <- $(SVC) redeployed OK"
