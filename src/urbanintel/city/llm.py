from __future__ import annotations

import json
import os
from pathlib import Path

import requests

DEFAULT_CLAUDE_MODEL = "claude-opus-5-5"
# Local models in order of preference; very small models ignore the JSON schema and are refused
OLLAMA_PREFERRED = ["qwen2.5:14b", "qwen3.5:9b", "llama3.1:8b", "qwen2.5:7b", "mistral:7b", "gemma2:9b"]
OLLAMA_TOO_SMALL = ("0.5b", "0.6b", "0.8b", "1b", "1.5b", "1.7b", "2b")
OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
if not OLLAMA_URL.startswith("http"):
    OLLAMA_URL = f"http://{OLLAMA_URL}"


class LLMUnavailable(RuntimeError):
    pass


class Declined(RuntimeError):
    pass


class ClaudeExtractor:
    name = "claude"
    workers = 6

    def __init__(self, model: str | None = None):
        try:
            import anthropic
        except ImportError as exc:
            raise LLMUnavailable("the anthropic package is not installed (pip install anthropic)") from exc
        self.anthropic = anthropic
        self.client = anthropic.Anthropic(max_retries=4)
        self.model = model or os.environ.get("URBANINTEL_LLM_MODEL", DEFAULT_CLAUDE_MODEL)
        self.payload_bytes = 0

    def extract(self, system: str, user: str, schema: dict) -> dict:
        kwargs = dict(model=self.model, max_tokens=8000, system=system,
                      messages=[{"role": "user", "content": user}],
                      output_config={"effort": "low",
                                     "format": {"type": "json_schema", "schema": schema}})
        # Server-side fallback re-runs a declined request on Anthropic's recommended model
        if not self.model.startswith("claude-haiku"):
            kwargs.update(betas=["server-side-fallback-2026-07-01"], fallbacks="default")
            resp = self.client.beta.messages.create(**kwargs)
        else:
            resp = self.client.messages.create(**kwargs)
        if resp.stop_reason == "refusal":
            raise Declined(getattr(resp.stop_details, "category", None) or "refused")
        text = next((b.text for b in resp.content if b.type == "text"), "")
        self.payload_bytes += len(system) + len(user) + len(text) + 600
        return json.loads(text)


class OllamaExtractor:
    name = "ollama"
    # One request at a time lets Ollama reuse the cached system prompt between articles
    workers = 1

    def __init__(self, model: str | None = None):
        self.payload_bytes = 0
        try:
            tags = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5).json()
        except requests.RequestException as exc:
            raise LLMUnavailable(f"Ollama is not running at {OLLAMA_URL}") from exc
        names = [m["name"] for m in tags.get("models", [])]
        want = model or os.environ.get("URBANINTEL_OLLAMA_MODEL")
        if want is None:
            want = next((n for n in OLLAMA_PREFERRED if n in names), None)
        if want is None or want not in names:
            raise LLMUnavailable(f"no suitable Ollama model pulled (have: {sorted(names)}); "
                                 f"pull one of {OLLAMA_PREFERRED[:4]}")
        if any(want.endswith(sz) for sz in OLLAMA_TOO_SMALL):
            raise LLMUnavailable(f"{want} is too small to follow the extraction schema")
        self.model = want

    def extract(self, system: str, user: str, schema: dict) -> dict:
        r = requests.post(f"{OLLAMA_URL}/api/chat", timeout=600, json={
            "model": self.model, "stream": False, "format": schema, "think": False,
            "options": {"temperature": 0, "seed": 0},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
        r.raise_for_status()
        return json.loads(r.json()["message"]["content"])


def claude_ready() -> bool:
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    return (Path.home() / ".config" / "anthropic").exists()


def make(backend: str = "auto", model: str | None = None):
    order = {"auto": ["claude", "ollama"], "claude": ["claude"], "ollama": ["ollama"]}[backend]
    errors = []
    for b in order:
        try:
            if b == "claude":
                if backend == "auto" and not claude_ready():
                    raise LLMUnavailable("no Anthropic credentials found (set ANTHROPIC_API_KEY)")
                return ClaudeExtractor(model)
            return OllamaExtractor(model)
        except LLMUnavailable as exc:
            errors.append(f"{b}: {exc}")
    raise LLMUnavailable("; ".join(errors))
