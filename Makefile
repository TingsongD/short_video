PY := .venv/bin/python

.PHONY: setup test test-live e2e-dry secrets-check

setup:
	uv venv .venv
	uv pip install -p .venv pytest jsonschema python-dotenv==1.2.3 \
		fastapi==0.141.1 starlette==1.6.0 httpx==0.28.1 httpx2==2.13.0 \
		anyio==4.14.2 Pillow==12.3.0 uvicorn==0.53.0

test:
	$(PY) -m pytest tests -q

# Live tests hit real APIs and may spend money. Never run by default.
# Requires: MPT_LIVE=1 and filled config/secrets.toml
test-live:
	MPT_LIVE=1 $(PY) -m pytest tests/live -q

e2e-dry:
	$(PY) -m pytest tests -q -k e2e_dry

secrets-check:
	@! git grep -I -n -E "(AIza[0-9A-Za-z_-]{20,}|sk-[0-9A-Za-z]{20,})" -- . ':(exclude)docs' \
		&& echo "OK: no API-key-shaped strings in tracked files"
