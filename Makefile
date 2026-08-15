.PHONY: install corpus eval record test clean

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
