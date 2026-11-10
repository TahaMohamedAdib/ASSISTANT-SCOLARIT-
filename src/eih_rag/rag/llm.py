"""Clients LLM configurables, sans cle exposee au navigateur."""

from __future__ import annotations

import re
import time
from typing import Protocol

import httpx


class LLMUnavailable(RuntimeError):
    pass


class LLMQuotaExceeded(LLMUnavailable):
    """Quota du fournisseur atteint (ex. jetons par jour de l'offre gratuite Groq)."""

    def __init__(self, retry_after: float | None) -> None:
        wait = f" ; nouvel essai possible dans {round(retry_after / 60) or 1} min" if retry_after else ""
        super().__init__(f"Quota du modele de langage atteint{wait}.")
        self.retry_after = retry_after


def _raw_retry_after(response: httpx.Response) -> float | None:
    try:
        return float(response.headers.get("retry-after") or "")
    except ValueError:
        return None


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


def strip_thinking(text: str) -> str:
    """Retire les blocs de raisonnement <think>...</think> de certains modeles."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


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


    def stream(self, system_prompt: str, user_prompt: str):
        """Flux de jetons (NDJSON Ollama)."""
        import json

        try:
            with httpx.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json={"model": self.model, "stream": True, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]},
                timeout=120.0,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if line.strip():
                        token = json.loads(line).get("message", {}).get("content", "")
                        if token:
                            yield token
        except (httpx.HTTPError, ValueError) as error:
            raise LLMUnavailable(f"Ollama ne repond pas : {error}") from error


class OpenAICompatibleGenerator:
    """Client OpenAI-compatible (Groq).

    ``max_wait`` borne le temps total passe a attendre la fin d'un quota (429) :
    ``None`` = patience illimitee (banc d'evaluation hors ligne) ; dans l'application,
    un etudiant ne doit pas attendre plusieurs minutes : on echoue vite avec
    ``LLMQuotaExceeded`` et un message clair.
    """

    def __init__(self, base_url: str, model: str, api_key: str, max_wait: float | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.max_wait = max_wait

    def _wait_or_raise(self, response: httpx.Response, attempt: int, waited: float) -> float:
        """Attend avant un nouvel essai ; leve LLMQuotaExceeded si le budget d'attente serait depasse."""
        delay = _retry_delay(response, attempt)
        if response.status_code == 429 and self.max_wait is not None and waited + delay > self.max_wait:
            raise LLMQuotaExceeded(_raw_retry_after(response) or delay)
        time.sleep(delay)
        return waited + delay

    max_retries = 12

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        if not self.model or not self.api_key:
            raise LLMUnavailable("OPENAI_MODEL et OPENAI_API_KEY doivent etre renseignes.")
        payload = {"model": self.model, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}], "temperature": 0}
        waited = 0.0
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
                    waited = self._wait_or_raise(response, attempt, waited)
                    continue
                break
            response.raise_for_status()
            answer = response.json()["choices"][0]["message"]["content"].strip()
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
            raise LLMUnavailable(f"Le fournisseur OpenAI-compatible ne repond pas : {error}") from error
        if not answer:
            raise LLMUnavailable("Le fournisseur LLM a retourne une reponse vide.")
        return answer


def _openai_stream(self, system_prompt: str, user_prompt: str, model: str | None = None):
    """Flux de jetons Server-Sent Events (API OpenAI-compatible : Groq).

    Les quotas (429) sont geres avant le premier jeton ; ensuite le flux est
    transmis tel quel.
    """
    import json

    if not self.api_key:
        raise LLMUnavailable("OPENAI_MODEL et OPENAI_API_KEY doivent etre renseignes.")
    payload = {
        "model": model or self.model, "stream": True, "temperature": 0,
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
    }
    waited = 0.0
    try:
        for attempt in range(self.max_retries + 1):
            with httpx.stream("POST", f"{self.base_url}/chat/completions", headers={"Authorization": f"Bearer {self.api_key}"}, json=payload, timeout=120.0) as response:
                if response.status_code in (429, 500, 502, 503) and attempt < self.max_retries:
                    response.read()
                    waited = self._wait_or_raise(response, attempt, waited)
                    continue
                if response.status_code >= 400:
                    response.read()
                    response.raise_for_status()
                for line in response.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        return
                    choices = json.loads(data).get("choices") or [{}]
                    token = (choices[0].get("delta") or {}).get("content")
                    if token:
                        yield token
                return
    except (httpx.HTTPError, ValueError) as error:
        raise LLMUnavailable(f"Le fournisseur OpenAI-compatible ne repond pas : {error}") from error


OpenAICompatibleGenerator.stream = _openai_stream


def build_generator(
    provider: str, *, ollama_base_url: str, ollama_model: str, openai_base_url: str, openai_model: str, openai_api_key: str,
    max_wait: float | None = None,
) -> AnswerGenerator:
    if provider == "ollama":
        return OllamaGenerator(ollama_base_url, ollama_model)
    if provider == "openai_compatible":
        return OpenAICompatibleGenerator(openai_base_url, openai_model, openai_api_key, max_wait=max_wait)
    raise ValueError("RAG_LLM_PROVIDER doit etre 'ollama' ou 'openai_compatible'.")
