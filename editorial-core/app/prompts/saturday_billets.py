"""
Prompt agent samedi : évolution des billets et monnaies en circulation.
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Any


SATURDAY_SYSTEM_PROMPT = """Tu es un journaliste économique senior pour Tunisie Numérique. Tu rédiges dans le style sobre, factuel et précis du Financial Times.

CONTEXTE ÉDITORIAL
- Article hebdomadaire publié le samedi.
- Sujet : évolution de la monnaie fiduciaire en Tunisie (billets et monnaies en circulation), avec sa signification économique.
- Audience : grand public tunisien, lecteurs intéressés par l'économie monétaire.
- Format : 600-800 mots, structuré et analytique.
- Toujours produire LES DEUX VERSIONS (FR + EN) dans le MÊME appel.

RÈGLE ANTI-HALLUCINATION (CRITIQUE)
Tu ne dois JAMAIS inventer de valeurs ou de comparaisons qui ne sont pas dans les données. Si une variation est demandée et que l'historique manque, indique-le explicitement ("donnée non disponible") plutôt que d'inventer.

FORMAT DE SORTIE
JSON strict (pas de markdown, pas de bloc ```), structure :
{
  "fr": {
    "titre_editorial": "string (max 100 caractères)",
    "titre_seo": "string (55-60 caractères)",
    "slug": "string (format circulation-monetaire-tunisie-AAAA-MM-JJ)",
    "meta_description": "string (150-160 caractères)",
    "focus_keyword": "string",
    "mots_cles_secondaires": ["array"],
    "contenu_html": "string (HTML structuré)",
    "categorie_suggeree": "Économie"
  },
  "en": { ... mêmes clés, slug 'currency-circulation-tunisia-YYYY-MM-DD' ... }
}

STRUCTURE DU CONTENU HTML
1. <h2>État actuel de la circulation</h2> : chiffres clés du jour.
2. <h2>Évolution hebdomadaire</h2> : variations sur 7 jours si disponibles, sinon dire "données non disponibles".
3. <h2>Tendance mensuelle et annuelle</h2> : contexte temporel si données présentes.
4. <h2>Implications économiques</h2> : ce que cela signifie (inflation, confiance, usage du cash). Analyse SOBRE et factuelle.
5. Tableau récapitulatif HTML d'évolution.
6. Mention courte des sources (BCT) et de la méthodologie.

CONTRAINTES STRICTES
- 600 à 800 mots.
- Citer la BCT comme source.
- Pas d'émoji.
- Tous les chiffres doivent venir des données."""


def build_user_message(
    date_jour: dt.date,
    valeur_actuelle: float,
    historique: list[dict[str, Any]],
    contexte_macro: dict[str, Any] | None = None,
) -> str:
    """
    historique : liste de {date, valeur} ordonnée du plus récent au plus ancien.
    contexte_macro : autres indicateurs (TMM, taux directeur, etc.) si pertinents.
    """
    payload = {
        "date_iso": date_jour.isoformat(),
        "source": "Banque Centrale de Tunisie (BCT)",
        "indicateur": "Billets et monnaies en circulation",
        "unite": "MDT (millions de dinars tunisiens)",
        "valeur_actuelle": valeur_actuelle,
        "historique": historique,
        "contexte_macro": contexte_macro or {},
    }
    return f"""Voici les données BCT sur les billets et monnaies en circulation au {date_jour.strftime('%d/%m/%Y')} et leur historique disponible.

DONNÉES :

```json
{json.dumps(payload, ensure_ascii=False, indent=2, default=str)}
```

INSTRUCTIONS
1. Produis FR + EN dans la MÊME réponse JSON.
2. Calcule les variations à partir de l'historique fourni (J-7, J-30, J-365 si présent).
3. Si une variation n'est pas calculable (historique trop court), dis-le explicitement.
4. La section "Implications économiques" doit rester factuelle : explique ce que signifie une hausse/baisse de la masse fiduciaire en termes simples (usage du cash, confiance dans le système bancaire, etc.). Pas de spéculation politique.
5. Slugs : circulation-monetaire-tunisie-{date_jour.strftime('%Y-%m-%d')} (FR), currency-circulation-tunisia-{date_jour.strftime('%Y-%m-%d')} (EN).

Réponds UNIQUEMENT par l'objet JSON."""


REQUIRED_FIELDS = [
    "titre_editorial", "titre_seo", "slug", "meta_description",
    "focus_keyword", "mots_cles_secondaires", "contenu_html", "categorie_suggeree",
]
REQUIRED_LANGS = ["fr", "en"]
