"""
Vérification anti-hallucination niveau "validation post-génération" (§8.6.2).
Compare les chiffres présents dans le HTML généré au pool de valeurs autorisées
issues des données source. Tout chiffre orphelin déclenche une alerte.
"""
from __future__ import annotations

import re
from typing import Any

# Capture les nombres : 23, 23.5, -1.2, 100,5 (séparateur français), 1 500
NUMBER_REGEX = re.compile(
    r"(?<![\w.])-?\d{1,3}(?:[ \s]?\d{3})*(?:[.,]\d+)?(?![\w])"
)

# Tolérance d'écart absolu pour les températures (arrondis OWM)
TEMPERATURE_TOLERANCE = 0.5


def _normalize(num_str: str) -> float | None:
    """Normalise '23,5' → 23.5, '1 500' → 1500.0."""
    cleaned = num_str.replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _extract_numbers(text: str) -> list[float]:
    """Extrait tous les nombres présents dans un texte (HTML ou non)."""
    found = []
    for match in NUMBER_REGEX.findall(text):
        val = _normalize(match)
        if val is not None:
            found.append(val)
    return found


def _build_allowed_pool(weather_rows: list[dict[str, Any]]) -> set[float]:
    """
    Construit l'ensemble des valeurs autorisées dans l'article : températures min/max,
    humidités, vitesses de vent, pressions, UV, précipitations, ordre d'affichage.
    """
    allowed: set[float] = set()
    for row in weather_rows:
        for key in (
            "temperature_min",
            "temperature_max",
            "temperature_actuelle",
            "humidite",
            "vent_vitesse",
            "vent_direction",
            "pression",
            "indice_uv",
            "precipitations_mm",
            "ordre",
        ):
            val = row.get(key)
            if val is None:
                continue
            try:
                allowed.add(float(val))
            except (TypeError, ValueError):
                continue
    return allowed


def _is_allowed(value: float, allowed_pool: set[float]) -> bool:
    """Vrai si la valeur (avec tolérance température) est dans le pool autorisé."""
    if value in allowed_pool:
        return True
    # Tolérance arrondi : ±0.5 sur les températures + 0.1 général
    for ref in allowed_pool:
        if abs(value - ref) <= TEMPERATURE_TOLERANCE:
            return True
    return False


def check_hallucinations(
    contenu_html: str, weather_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    """
    Renvoie un rapport :
        {"status": "passed" | "suspected", "orphan_numbers": [...], ...}

    "passed"   : tous les chiffres trouvent une source plausible.
    "suspected": au moins un chiffre ne correspond à aucune donnée → révision manuelle.
    """
    allowed_pool = _build_allowed_pool(weather_rows)
    found = _extract_numbers(contenu_html)

    orphans = []
    # On ignore les "petits nombres structurels" (1..30, ce sont aussi des dates ou
    # des numéros de section). On vérifie surtout les valeurs > 30 ou les décimales.
    for value in found:
        # Ignore les entiers de 0 à 31 (numéros de jour, ordre d'affichage déjà whitelistés)
        if value.is_integer() and 0 <= value <= 31 and value in allowed_pool:
            continue
        if not _is_allowed(value, allowed_pool):
            orphans.append(value)

    return {
        "status": "passed" if not orphans else "suspected",
        "orphan_numbers": sorted(set(orphans)),
        "total_numbers_in_article": len(found),
        "allowed_pool_size": len(allowed_pool),
    }
