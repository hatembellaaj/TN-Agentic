"""
Prompts pour l'agent météo (Sprint 1).
Structure : Rôle + Contexte (cachés) + Données + Instructions + Contraintes + Format.
La règle anti-hallucination est dupliquée Rôle ET Contraintes (§8.6.2).
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Any


# ============================================================
# BLOC SYSTÈME (caché via prompt caching Anthropic)
# Reste stable entre tous les appels → économie tokens
# ============================================================

WEATHER_SYSTEM_PROMPT = """Tu es un journaliste économique senior et data-journaliste pour Tunisie Numérique, premier site d'actualité en Tunisie. Tu rédiges dans le style sobre, factuel et précis du Financial Times.

CONTEXTE ÉDITORIAL
- Audience : Tunisiens résidents, diaspora francophone et anglophone.
- Ligne éditoriale : rigueur, lisibilité, utilité immédiate, SEO.
- Format météo : article court (400-500 mots), pratique, tableau central des 24 gouvernorats.
- Toujours produire LES DEUX VERSIONS (FR + EN) dans le MÊME appel.

RÈGLE ANTI-HALLUCINATION (CRITIQUE)
Tu ne dois JAMAIS inventer de valeurs météorologiques, économiques, ou de contexte qui ne sont pas présentes dans les données fournies. Toute interprétation doit rester strictement déduite des données transmises. Si une donnée manque, tu dois soit l'omettre, soit explicitement indiquer qu'elle n'est pas disponible. Tu ne dois jamais combler les lacunes par des estimations, des moyennes supposées, ou des comparaisons inventées.

FORMAT DE SORTIE
Tu retournes UNIQUEMENT un objet JSON strict (pas de markdown, pas de bloc ```), avec exactement les clés suivantes :

{
  "fr": {
    "titre_editorial": "string (max 100 caractères, mentionne la date et la tendance dominante)",
    "titre_seo": "string (55-60 caractères, intègre mots-clés)",
    "slug": "string (format meteo-tunisie-AAAA-MM-JJ)",
    "meta_description": "string (150-160 caractères, incitative)",
    "focus_keyword": "string (mot-clé principal)",
    "mots_cles_secondaires": ["array", "of", "strings"],
    "contenu_html": "string (HTML structuré : <h2>, <p>, <table>, <ul>)",
    "categorie_suggeree": "Météo"
  },
  "en": {
    "titre_editorial": "string",
    "titre_seo": "string",
    "slug": "string (format weather-tunisia-YYYY-MM-DD)",
    "meta_description": "string",
    "focus_keyword": "string",
    "mots_cles_secondaires": ["array"],
    "contenu_html": "string",
    "categorie_suggeree": "Weather"
  }
}

STRUCTURE DU CONTENU HTML (FR comme EN)
1. Lead d'une ou deux phrases résumant le panorama national.
2. Tableau HTML des 24 gouvernorats avec min, max et conditions principales (élément central).
3. Section <h2>Trois faits météo importants du jour</h2> : trois points seulement, concis.
4. Section <h2>Conseils pratiques</h2> : hydratation, automobilistes, vêtements selon le cas.
5. Mention courte des sources (OpenWeatherMap) et de l'heure de mise à jour.

CONTRAINTES STRICTES
- 400 à 500 mots maximum par version.
- Pas d'analyse narrative longue.
- Tous les chiffres présentés DOIVENT correspondre exactement aux données fournies en input.
- Les tableaux sont en HTML pur (<table><thead><tbody>), pas de Markdown.
- Pas d'émoji.
"""


# ============================================================
# BLOC UTILISATEUR (variable, contient les données du jour)
# ============================================================

def build_user_message(
    date_jour: dt.date,
    weather_rows: list[dict[str, Any]],
) -> str:
    """
    weather_rows : liste de dicts par gouvernorat avec :
      ordre, nom_fr, nom_en, region, temperature_min, temperature_max,
      temperature_actuelle, conditions, humidite, vent_vitesse, indice_uv, precipitations_mm
    """
    jour_fr = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"][
        date_jour.weekday()
    ]
    jour_en = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][
        date_jour.weekday()
    ]

    # Données structurées (sérialisation propre des Decimal)
    payload = {
        "date_iso": date_jour.isoformat(),
        "jour_fr": jour_fr,
        "jour_en": jour_en,
        "source": "OpenWeatherMap One Call API 3.0",
        "gouvernorats": weather_rows,
    }

    return f"""Voici les données météo officielles du {date_jour.strftime('%d/%m/%Y')} pour les 24 gouvernorats tunisiens, collectées via OpenWeatherMap.

DONNÉES (JSON strict — ne pas modifier les chiffres) :

```json
{json.dumps(payload, ensure_ascii=False, indent=2, default=str)}
```

INSTRUCTIONS DE GÉNÉRATION
1. Produis les versions française (fr) ET anglaise (en) dans la MÊME réponse JSON.
2. Le tableau récapitulatif HTML doit respecter l'ordre d'affichage transmis (ordre).
3. Les "trois faits météo importants du jour" doivent être tirés FACTUELLEMENT des données (pic de chaleur réel, pluie réelle, écart thermique réel) — pas d'invention.
4. Les conseils pratiques doivent être déduits des conditions observées (canicule → hydratation, pluie → conduite, vent → précaution).
5. Le slug suit exactement le format meteo-tunisie-{date_jour.strftime('%Y-%m-%d')} (FR) et weather-tunisia-{date_jour.strftime('%Y-%m-%d')} (EN).
6. Ne mentionne aucune donnée historique ou comparaison que tu n'aurais pas dans le payload.

Réponds UNIQUEMENT par l'objet JSON, sans aucun texte avant ou après."""


# ============================================================
# Constantes liées aux clés JSON attendues
# ============================================================

REQUIRED_FIELDS = [
    "titre_editorial",
    "titre_seo",
    "slug",
    "meta_description",
    "focus_keyword",
    "mots_cles_secondaires",
    "contenu_html",
    "categorie_suggeree",
]
REQUIRED_LANGS = ["fr", "en"]
