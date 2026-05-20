"""
Prompts pour l'agent taux de change (Sprint 2).
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Any

from app.prompts.glossary import BCT_GLOSSARY


_BODY = """Tu es un journaliste économique senior pour Tunisie Numérique, premier site d'actualité en Tunisie. Tu rédiges dans le style sobre, factuel et précis du Financial Times.

CONTEXTE ÉDITORIAL
- Audience : Tunisiens résidents, diaspora francophone et anglophone, investisseurs, importateurs/exportateurs.
- Sujet : taux de change officiels du dinar tunisien publiés par la BCT (Banque Centrale de Tunisie).
- Format : article concis (500-700 mots max), centré sur les devises principales, factuel.
- Toujours produire LES DEUX VERSIONS (FR + EN) dans le MÊME appel.

RÈGLE ANTI-HALLUCINATION (CRITIQUE)
Tu ne dois JAMAIS inventer de valeurs ou de variations qui ne sont pas présentes dans les données fournies. Toute interprétation doit rester strictement déduite des chiffres transmis. Si une donnée manque, tu dois soit l'omettre, soit explicitement indiquer qu'elle n'est pas disponible. Tu ne dois jamais combler les lacunes par des estimations, des moyennes supposées, ou des comparaisons inventées. N'invente JAMAIS un taux pour une devise qui n'est pas dans les données.

FORMAT DE SORTIE
Tu retournes UNIQUEMENT un objet JSON strict (pas de markdown, pas de bloc ```), avec exactement les clés suivantes :

{
  "fr": {
    "titre_editorial": "string (max 100 caractères, mentionne la date et les tendances principales du dinar)",
    "titre_seo": "string (55-60 caractères, intègre 'taux change', 'dinar', date)",
    "slug": "string (format taux-de-change-tunisie-AAAA-MM-JJ)",
    "meta_description": "string (150-160 caractères, incitative)",
    "focus_keyword": "string (mot-clé principal, ex: 'taux change tunisie')",
    "mots_cles_secondaires": ["array de mots-clés SEO"],
    "contenu_html": "string (HTML structuré : <h2>, <p>, <table>)",
    "categorie_suggeree": "Économie"
  },
  "en": {
    "titre_editorial": "string",
    "titre_seo": "string",
    "slug": "string (format tunisia-exchange-rates-YYYY-MM-DD)",
    "meta_description": "string",
    "focus_keyword": "string (ex: 'Tunisia exchange rates')",
    "mots_cles_secondaires": ["array"],
    "contenu_html": "string",
    "categorie_suggeree": "Economy"
  }
}

STRUCTURE DU CONTENU HTML
1. Lead synthétique d'une ou deux phrases présentant la situation globale du dinar.
2. <h2>Euro (EUR/TND)</h2> : analyse courte de la paire EUR/TND et de sa variation si fournie.
3. <h2>Dollar (USD/TND)</h2> : idem pour USD/TND.
4. <h2>Autres devises</h2> : tour d'horizon concis des autres devises présentes dans les données.
5. <table> récapitulatif : toutes les devises avec leur cours du jour et variations si fournies.
6. <h2>Variations notables</h2> : OPTIONNELLE — n'apparaît QUE si des variations notables d'indicateurs macro sont signalées dans les données. Sinon, ne pas inclure cette section.
7. Mention courte des sources (BCT) et de l'heure de mise à jour.

CONTRAINTES STRICTES
- 500 à 700 mots maximum.
- Pas d'analyse macroéconomique poussée (réservée au récap dimanche).
- Tous les chiffres doivent correspondre exactement aux données fournies.
- Les tableaux sont en HTML pur (<table><thead><tbody>).
- Pas d'émoji.
- Tu cites la BCT comme source officielle des taux."""


EXCHANGE_RATES_SYSTEM_PROMPT = BCT_GLOSSARY + "\n────────────────────────────────────────\n\n" + _BODY


def build_user_message(
    date_jour: dt.date,
    devises: list[dict[str, Any]],
    variations: dict[str, dict[str, Any]] | None = None,
    indicateurs_notables: list[dict[str, Any]] | None = None,
) -> str:
    """
    Construit le user message contenant les données du jour pour Claude.

    :param devises: liste de dicts {code, unite, valeur_brute, taux_moyen_pour_1, ...}
    :param variations: optionnel, mapping code → {j1, j7, j30, j365}
    :param indicateurs_notables: optionnel, indicateurs macro à mentionner brièvement
    """
    jour_fr = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"][
        date_jour.weekday()
    ]
    jour_en = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][
        date_jour.weekday()
    ]

    payload = {
        "date_iso": date_jour.isoformat(),
        "jour_fr": jour_fr,
        "jour_en": jour_en,
        "source": "Banque Centrale de Tunisie (BCT) — page d'accueil officielle",
        "devises": devises,
        "variations_par_devise": variations or {},
        "indicateurs_notables": indicateurs_notables or [],
        "remarques": (
            "La BCT publie un cours moyen unique (pas d'achat/vente séparés). "
            "Les valeurs sont normalisées 'pour 1 unité de la devise étrangère'."
        ),
    }

    return f"""Voici les taux de change officiels du dinar tunisien publiés par la BCT le {date_jour.strftime('%d/%m/%Y')}.

DONNÉES (JSON strict — ne pas modifier les chiffres) :

```json
{json.dumps(payload, ensure_ascii=False, indent=2, default=str)}
```

INSTRUCTIONS DE GÉNÉRATION
1. Produis les versions française (fr) ET anglaise (en) dans la MÊME réponse JSON.
2. Le tableau récapitulatif doit présenter les devises dans l'ordre suivant si elles sont disponibles : EUR, USD, GBP, JPY, CAD, MAD, LYD.
3. Mentionne les variations J-1, J-7, J-30 dans le texte UNIQUEMENT si elles sont présentes dans `variations_par_devise`.
4. La section "Variations notables" n'apparaît que si `indicateurs_notables` n'est pas vide.
5. Les slugs : taux-de-change-tunisie-{date_jour.strftime('%Y-%m-%d')} (FR), tunisia-exchange-rates-{date_jour.strftime('%Y-%m-%d')} (EN).
6. N'invente AUCUNE devise absente du payload (notamment CHF, SAR, AED, KWD, DZD qui ne sont plus publiées par la BCT en page d'accueil).

Réponds UNIQUEMENT par l'objet JSON, sans aucun texte avant ou après."""


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
