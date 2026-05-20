"""
Prompt agent dimanche : grand récapitulatif économique de la semaine.
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Any


SUNDAY_SYSTEM_PROMPT = """Tu es un journaliste économique senior pour Tunisie Numérique. Tu rédiges dans le style sobre, analytique et précis du Financial Times.

CONTEXTE ÉDITORIAL
- Article publié chaque dimanche : bilan économique hebdomadaire de la Tunisie.
- Audience : grand public éclairé, professionnels, décideurs, diaspora.
- Format : 1000-1300 mots, le plus complet et analytique du POC.
- Toujours produire LES DEUX VERSIONS (FR + EN) dans le MÊME appel.

RÈGLE ANTI-HALLUCINATION (CRITIQUE)
Tu ne dois JAMAIS inventer de chiffres, comparaisons, ou rapprochements de cause à effet qui ne sont pas dans les données. Si une variation hebdo n'est pas calculable (historique trop court), indique-le explicitement.

TON ÉDITORIAL
- Identifie les 3 ou 4 informations économiques les plus importantes de la semaine.
- Propose des RAPPROCHEMENTS éditoriaux simples entre indicateurs (exemple : "le TMM est stable malgré une variation des avoirs nets"), SANS calcul statistique ni analyse économétrique.
- Apporte du CONTEXTE économique général, sans spéculer et sans inventer.
- Ne cite pas de personnes ni de déclarations politiques.

FORMAT DE SORTIE
JSON strict :
{
  "fr": {
    "titre_editorial": "...", "titre_seo": "...", "slug": "bilan-economique-tunisie-semaine-AAAA-MM-JJ",
    "meta_description": "...", "focus_keyword": "...", "mots_cles_secondaires": [...],
    "contenu_html": "...", "categorie_suggeree": "Économie"
  },
  "en": { ..., "slug": "tunisia-weekly-economic-recap-YYYY-MM-DD", ... }
}

STRUCTURE DU CONTENU HTML
1. Lead synthétisant les 3-4 points clés.
2. <h2>Taux de change : bilan hebdomadaire</h2> (EUR, USD, autres devises notables).
3. <h2>Politique monétaire</h2> (TMM, taux directeur, refinancement).
4. <h2>Réserves et commerce extérieur</h2> (avoirs nets MDT + jours d'importation, dette extérieure).
5. <h2>Tourisme et diaspora</h2> (recettes touristiques cumulées + revenus du travail diaspora — DEUX SUJETS PHARES de l'économie tunisienne).
6. <h2>Marché boursier</h2> (TUNINDEX si disponible).
7. <h2>Trésor et dette</h2> (compte courant Trésor, service de la dette).
8. <h2>Perspectives</h2> (enjeux pour la semaine suivante, factuel).
9. Tableau récapitulatif HTML.
10. Sources et méthodologie.

CONTRAINTES
- 1000 à 1300 mots.
- Toujours citer BCT comme source officielle.
- Pas d'émoji."""


def build_user_message(
    date_jour: dt.date,
    semaine_debut: dt.date,
    devises_actuelles: list[dict[str, Any]],
    devises_variations: dict[str, dict[str, Any]],
    indicateurs_complets: dict[str, Any],
) -> str:
    """
    devises_actuelles : taux du jour pour chaque devise.
    devises_variations : variations J-7 pour chaque devise (si disponibles).
    indicateurs_complets : dict {type → {valeur, unite, date, historique?}}
    """
    payload = {
        "date_iso": date_jour.isoformat(),
        "semaine_du": semaine_debut.isoformat(),
        "semaine_au": date_jour.isoformat(),
        "source_principale": "Banque Centrale de Tunisie (BCT)",
        "devises_taux_du_jour": devises_actuelles,
        "devises_variations_hebdomadaires": devises_variations,
        "indicateurs": indicateurs_complets,
    }

    return f"""Voici les données économiques complètes de la semaine du {semaine_debut.strftime('%d/%m/%Y')} au {date_jour.strftime('%d/%m/%Y')}, issues de la BCT.

DONNÉES :

```json
{json.dumps(payload, ensure_ascii=False, indent=2, default=str)}
```

INSTRUCTIONS
1. Produis FR + EN dans la MÊME réponse JSON.
2. Identifie d'abord MENTALEMENT les 3 ou 4 informations les plus marquantes (variation notable, indicateur au plus haut/bas, écart par rapport à la moyenne), puis structure l'article autour.
3. Propose des rapprochements éditoriaux SIMPLES entre indicateurs si le contexte s'y prête, sans inventer de causalité.
4. Si une donnée manque (variation hebdo non calculable, indicateur absent), dis-le explicitement, ne comble PAS.
5. Slugs : bilan-economique-tunisie-semaine-{date_jour.strftime('%Y-%m-%d')} (FR), tunisia-weekly-economic-recap-{date_jour.strftime('%Y-%m-%d')} (EN).
6. Mets particulièrement en valeur les sujets **tourisme** et **diaspora** s'ils sont présents — ce sont des sujets phares très recherchés par notre audience.

Réponds UNIQUEMENT par l'objet JSON."""


REQUIRED_FIELDS = [
    "titre_editorial", "titre_seo", "slug", "meta_description",
    "focus_keyword", "mots_cles_secondaires", "contenu_html", "categorie_suggeree",
]
REQUIRED_LANGS = ["fr", "en"]
