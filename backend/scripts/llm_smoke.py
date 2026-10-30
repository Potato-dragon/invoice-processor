"""One tiny real LLM call to check the request shape is accepted.

Run:  docker compose exec -e LLM_FAKE=false api python scripts/llm_smoke.py
Prints the HTTP status and the parsed JSON. Never prints the API key.
"""
import os
import sys

from app.extraction.llm import GeminiHTTPClient
from app.contracts import PipelineError

key = os.getenv("GEMINI_API_KEY", "")
if not key:
    sys.exit("GEMINI_API_KEY is not set")

prompt = 'Reply with ONLY this JSON: {"invoice_number": {"value": "A-1", "evidence": "Invoice A-1", "page": 1}}'
for model in (os.getenv("LLM_PRIMARY_MODEL"), os.getenv("LLM_FALLBACK_MODEL")):
    try:
        print(model, "->", GeminiHTTPClient(key).complete(model, prompt))
    except PipelineError as exc:
        print(model, "-> FAILED", exc.code.value, exc.message[:300])
