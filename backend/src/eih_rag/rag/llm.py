"""Clients LLM configurables, sans cle exposee au navigateur."""

from __future__ import annotations

import re
import time
from typing import Protocol

import httpx


class LLMUnavailable(RuntimeError):
    pass


def _duration(value: str | None) -> str | None:
    """Convertit "1m26.4s" / "45.8s" / "585ms" (en-tetes Groq) en secondes."""
    if not value:
        return None
    match = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m(?!s))?(?:([\d.]+)s)?(?:([\d.]+)ms)?", value.strip())
    if not match:
        return None
    hours, minutes, seconds, millis = match.groups()
    return str(int(hours or 0) * 3600 + int(minutes or 0) * 60 + float(seconds or 0) + float(millis or 0) / 1000)


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    """Delai d'attente : en-tete retry-after, sinon message Groq "try again in 7.5s", sinon exponentiel."""
    header = response.headers.get("retry-after") or _duration(response.headers.get("x-ratelimit-reset-tokens"))
    if header:
        try:
            return min(float(header) + 0.5, 120.0)
        except ValueError:
            pass
    match = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", response.text)
    if match:
        return min(int(match.group(1) or 0) * 60 + float(match.group(2)) + 0.5, 120.0)
    return min(2.0 * 2**attempt, 60.0)


class AnswerGenerator(Protocol):
    def generate(self, system_prompt: str, user_prompt: str) -> str: ...


class OllamaGenerator:
    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        try:
            response = httpx.post(
                f"{self.base_url}/api/chat",
                json={"model": self.model, "stream": False, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]},
                timeout=60.0,
            )
            response.raise_for_status()
            answer = response.json().get("message", {}).get("content", "").strip()
        except (httpx.HTTPError, ValueError) as error:
            raise LLMUnavailable(f"Ollama ne repond pas : {error}") from error
        if not answer:
            raise LLMUnavailable("Ollama a retourne une reponse vide.")
        return answer


class OpenAICompatibleGenerator:
    def __init__(self, base_url: str, model: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key

    max_retries = 12

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        if not self.model or not self.api_key:
            raise LLMUnavailable("OPENAI_MODEL et OPENAI_API_KEY doivent etre renseignes.")
        payload = {"model": self.model, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}], "temperature": 0}
        try:
            for attempt in range(self.max_retries + 1):
                response = httpx.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                    timeout=90.0,
                )
                # Quotas des offres gratuites (Groq) : on attend le delai indique puis on reessaie.
                if response.status_code in (429, 500, 502, 503) and attempt < self.max_retries:
                    time.sleep(_retry_delay(response, attempt))
                    continue
                break
            response.raise_for_status()
            answer = response.json()["choices"][0]["message"]["content"].strip()
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
            raise LLMUnavailable(f"Le fournisseur OpenAI-compatible ne repond pas : {error}") from error
        if not answer:
            raise LLMUnavailable("Le fournisseur LLM a retourne une reponse vide.")
        return answer


def build_generator(provider: str, *, ollama_base_url: str, ollama_model: str, openai_base_url: str, openai_model: str, openai_api_key: str) -> AnswerGenerator:
    if provider == "ollama":
        return OllamaGenerator(ollama_base_url, ollama_model)
    if provider == "openai_compatible":
        return OpenAICompatibleGenerator(openai_base_url, openai_model, openai_api_key)
    raise ValueError("RAG_LLM_PROVIDER doit etre 'ollama' ou 'openai_compatible'.")
