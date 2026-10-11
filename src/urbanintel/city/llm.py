from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

import requests

DEFAULT_CLAUDE_MODEL = "claude-opus-5-5"
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
# Free-tier text models in order of preference; the reader moves down the list when one runs out of daily quota
GEMINI_PREFERRED = ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite",
                    "gemini-2.5-flash", "gemini-2.5-flash-lite"]
GEMINI_RPM = float(os.environ.get("URBANINTEL_GEMINI_RPM", "12"))
GEMINI_REST_S = 300
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


def env_key(*names: str) -> str | None:
    # A key saved with setx after this process started is still found, in the Windows user environment
    for n in names:
        if os.environ.get(n):
            return os.environ[n]
    if os.name == "nt":
        import winreg

        for root, path in ((winreg.HKEY_CURRENT_USER, "Environment"),
                           (winreg.HKEY_LOCAL_MACHINE,
                            "SYSTEM\\CurrentControlSet\\Control\\Session Manager\\Environment")):
            try:
                with winreg.OpenKey(root, path) as k:
                    for n in names:
                        try:
                            v, _ = winreg.QueryValueEx(k, n)
                        except FileNotFoundError:
                            continue
                        if v:
                            return str(v)
            except OSError:
                continue
    return None


def to_gemini_schema(schema: dict) -> dict:
    # Gemini's responseSchema is an OpenAPI 3.0 subset: upper-case types and no additionalProperties
    out: dict = {}
    for k, v in schema.items():
        if k == "additionalProperties":
            continue
        if k == "type":
            out["type"] = str(v).upper()
        elif k == "properties":
            out["properties"] = {n: to_gemini_schema(q) for n, q in v.items()}
            out["propertyOrdering"] = list(v)
        elif k == "items":
            out["items"] = to_gemini_schema(v)
        else:
            out[k] = v
    return out


class GeminiExtractor:
    name = "gemini"
    workers = 2

    def __init__(self, model: str | None = None):
        self.key = env_key("GEMINI_API_KEY", "GOOGLE_API_KEY")
        if not self.key:
            raise LLMUnavailable("no Gemini API key; create a free one at https://aistudio.google.com/apikey "
                                 "and save it as GEMINI_API_KEY")
        try:
            r = requests.get(f"{GEMINI_BASE}/models", params={"pageSize": 1000},
                             headers={"x-goog-api-key": self.key}, timeout=30)
        except requests.RequestException as exc:
            raise LLMUnavailable(f"Gemini API unreachable: {exc}") from exc
        if r.status_code != 200:
            raise LLMUnavailable(f"Gemini API key rejected (HTTP {r.status_code}): {r.text[:200]}")
        have = {m["name"].split("/", 1)[1] for m in r.json().get("models", [])
                if "generateContent" in m.get("supportedGenerationMethods", [])}
        pinned = model or os.environ.get("URBANINTEL_GEMINI_MODEL")
        self.models = [m for m in dict.fromkeys(([pinned] if pinned else []) + GEMINI_PREFERRED)
                       if m in have]
        if not self.models:
            raise LLMUnavailable(f"none of {GEMINI_PREFERRED} is available to this key")
        self.model = self.models[0]
        self.exhausted: set[str] = set()
        self.resting: dict[str, float] = {}
        self.no_thinking: set[str] = set()
        self.lock = threading.Lock()
        self.next_slot: dict[str, float] = {}
        self.payload_bytes = 0
        self.calls = 0

    def _wait(self, model: str) -> None:
        with self.lock:
            now = time.time()
            t = max(now, self.next_slot.get(model, 0.0))
            self.next_slot[model] = t + 60.0 / GEMINI_RPM
        if t > now:
            time.sleep(t - now)

    def body(self, model: str, system: str, user: str, schema: dict) -> dict:
        gen = {"responseMimeType": "application/json", "responseSchema": to_gemini_schema(schema)}
        if model.startswith("gemini-3"):
            # Gemini 3 is meant to run at its default temperature; low thinking keeps extraction fast
            if model not in self.no_thinking:
                gen["thinkingConfig"] = {"thinkingLevel": "low"}
        else:
            gen["temperature"] = 0
        return {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}], "generationConfig": gen}

    def _rest(self, model: str) -> None:
        # A busy or hanging model is set aside for a few minutes and the next free model is used
        with self.lock:
            self.resting[model] = time.time() + GEMINI_REST_S

    def _live(self) -> list[str]:
        now = time.time()
        usable = [m for m in self.models if m not in self.exhausted]
        ready = [m for m in usable if self.resting.get(m, 0) <= now]
        return ready or sorted(usable, key=lambda m: self.resting.get(m, 0))

    def extract(self, system: str, user: str, schema: dict) -> dict:
        last = None
        for _ in range(12):
            live = self._live()
            if not live:
                raise LLMUnavailable(f"every free Gemini model is out of quota today ({last})")
            model = self.model = live[0]
            if self.resting.get(model, 0) > time.time():
                time.sleep(min(30.0, self.resting[model] - time.time()))
            self._wait(model)
            try:
                r = requests.post(f"{GEMINI_BASE}/models/{model}:generateContent", timeout=(10, 60),
                                  json=self.body(model, system, user, schema),
                                  headers={"x-goog-api-key": self.key, "Content-Type": "application/json"})
            except requests.RequestException as exc:
                last = f"{type(exc).__name__} on {model}"
                self._rest(model)
                continue
            self.payload_bytes += len(r.request.body or b"") + len(r.content)
            if r.status_code == 429:
                last = f"429 on {model}"
                if re.search(r"per ?day|PerDay|daily", r.text, re.IGNORECASE):
                    self.exhausted.add(model)
                    continue
                m = re.search(r'"retryDelay":\s*"(\d+)', r.text)
                time.sleep(int(m.group(1)) + 1 if m else 20)
                continue
            if r.status_code in (500, 502, 503, 504):
                last = f"{r.status_code} on {model}"
                self._rest(model)
                continue
            if r.status_code == 400 and "thinking" in r.text.lower() and model not in self.no_thinking:
                self.no_thinking.add(model)
                continue
            if r.status_code != 200:
                raise RuntimeError(f"Gemini HTTP {r.status_code}: {r.text[:300]}")
            j = r.json()
            cands = j.get("candidates") or []
            if not cands:
                raise Declined(str(j.get("promptFeedback", {}).get("blockReason", "no candidate")))
            c = cands[0]
            if c.get("finishReason") in ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION"):
                raise Declined(c["finishReason"])
            text = "".join(q.get("text", "") for q in c.get("content", {}).get("parts", []) if not q.get("thought"))
            self.calls += 1
            return json.loads(text)
        raise RuntimeError(f"Gemini request failed repeatedly: {last}")


def claude_ready() -> bool:
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    return (Path.home() / ".config" / "anthropic").exists()


def make(backend: str = "auto", model: str | None = None):
    # auto uses only free readers: the Gemini API free tier, then a local Ollama model
    order = {"auto": ["gemini", "ollama"], "gemini": ["gemini"], "claude": ["claude"],
             "ollama": ["ollama"]}[backend]
    errors = []
    for b in order:
        try:
            if b == "gemini":
                return GeminiExtractor(model)
            if b == "claude":
                return ClaudeExtractor(model)
            return OllamaExtractor(model)
        except LLMUnavailable as exc:
            errors.append(f"{b}: {exc}")
    raise LLMUnavailable("; ".join(errors))
