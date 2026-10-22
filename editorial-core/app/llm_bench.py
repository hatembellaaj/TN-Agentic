"""
Mesure la vitesse du LLM local (llama-server) sur un prompt de taille réelle.

Usage : make llm-test   (ou python -m app.llm_bench dans editorial-core)
"""
from __future__ import annotations

import time

import httpx

from app.config import settings
from app.prompts.weather import WEATHER_SYSTEM_PROMPT

# Volumes moyens observés avec Claude pour l'agent météo (table claude_logs)
WEATHER_INPUT_TOKENS = 4900
WEATHER_OUTPUT_TOKENS = 6000


def main() -> None:
    user = "Données de test pour Tunis, Sfax, Sousse et Bizerte. " * 200
    started = time.monotonic()
    resp = httpx.post(
        f"{settings.LOCAL_LLM_BASE_URL}/v1/chat/completions",
        json={
            "model": settings.LOCAL_LLM_MODEL,
            "messages": [
                {"role": "system", "content": WEATHER_SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            "max_tokens": 64,
        },
        timeout=1800,
    )
    resp.raise_for_status()
    t = resp.json()["timings"]
    pp, tg = t["prompt_per_second"], t["predicted_per_second"]
    print(
        f"total {time.monotonic() - started:.0f}s | "
        f"prompt {t['prompt_n']} tokens en {t['prompt_ms'] / 1000:.0f}s ({pp:.1f} t/s) | "
        f"sortie {t['predicted_n']} tokens ({tg:.1f} t/s)"
    )
    estimate = WEATHER_INPUT_TOKENS / pp + WEATHER_OUTPUT_TOKENS / tg
    print(f"Estimation article météo : ~{estimate / 60:.0f} min")


if __name__ == "__main__":
    main()
