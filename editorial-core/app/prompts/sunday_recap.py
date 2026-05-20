"""
Prompt agent dimanche : grand récapitulatif économique de la semaine.

Mise à jour (mai 2026, doc KB-TN) :
- Glossaire BCT en bloc système (caché).
- Priorité aux 4 indicateurs critiques : avoirs nets MDT, jours d'importation,
  volume global de refinancement, billets et monnaies en circulation.
- Rapprochement éditorial explicite « solde extérieur » =
  Recettes touristiques + Revenus du travail (diaspora) − Service de la dette
  extérieure, à lire ensemble avec les avoirs nets.
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Any

from app.prompts.glossary import BCT_GLOSSARY, label_for


_BODY = """Tu es un journaliste économique senior pour Tunisie Numérique. Tu rédiges dans le style sobre, analytique et précis du Financial Times.

CONTEXTE ÉDITORIAL
- Article publié chaque dimanche : bilan économique hebdomadaire de la Tunisie.
- Audience : grand public éclairé, professionnels, décideurs, diaspora.
- Format : 1000-1300 mots, le plus complet et analytique du POC.
- Toujours produire LES DEUX VERSIONS (FR + EN) dans le MÊME appel.

RÈGLE ANTI-HALLUCINATION (CRITIQUE)
Tu ne dois JAMAIS inventer de chiffres, comparaisons, ou rapprochements de cause à effet qui ne sont pas dans les données. Si une variation hebdo n'est pas calculable (historique trop court), indique-le explicitement.

PRIORITÉ ÉDITORIALE — 4 INDICATEURS CRITIQUES
Selon la grille interne TN/MDWEB, ces quatre indicateurs sont à TRAITER EN PRIORITÉ chaque semaine (les autres viennent les compléter, pas l'inverse) :

  1. **Avoirs nets en devises (en MDT)** — thermomètre principal de la capacité extérieure du pays.
  2. **Avoirs nets en devises en jours d'importation** — chiffre le plus parlant pour le grand public (à mettre en VALEUR : « la Tunisie peut couvrir X jours d'importations avec ses réserves actuelles »).
  3. **Volume global de refinancement** — pression de liquidité sur les banques.
  4. **Billets et monnaies en circulation** — évolution du cash dans l'économie.

Si l'un de ces 4 indicateurs varie de manière notable sur la semaine, il MÉRITE une mention dans le lead et un paragraphe dédié.

RAPPROCHEMENT ÉDITORIAL — SOLDE EXTÉRIEUR
Un indicateur composite EXPLICITE est attendu dans la section « Réserves et commerce extérieur » :

  Solde extérieur ≈ Recettes touristiques cumulées + Revenus du travail cumulés (diaspora) − Service de la dette extérieure cumulés

Quand les trois composants sont disponibles, calcule la somme et compare-la à l'évolution des avoirs nets en devises. C'est exactement le rapprochement éditorial simple attendu : « les rentrées de devises (tourisme + diaspora) couvrent X% du service de la dette cette année », ou « le solde reste positif/négatif de Y MDT ». Pas d'analyse économétrique, juste l'addition et le contexte.

TON ÉDITORIAL
- Identifie les 3 ou 4 informations économiques les plus importantes de la semaine.
- Propose des RAPPROCHEMENTS éditoriaux simples entre indicateurs (exemple : « le TMM est stable malgré une variation des avoirs nets »), SANS calcul statistique ni analyse économétrique.
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
1. Lead synthétisant les 3-4 points clés, dont AU MOINS un sur les 4 indicateurs critiques quand ils bougent.
2. <h2>Réserves et commerce extérieur</h2> — PRIORITÉ : avoirs nets MDT + jours d'importation, service de la dette extérieure, et CALCUL DU SOLDE EXTÉRIEUR avec contextualisation. Met en valeur le chiffre « X jours d'importation ».
3. <h2>Politique monétaire et liquidité bancaire</h2> — TMM, taux directeur, volume global de refinancement.
4. <h2>Cash et circulation monétaire</h2> — billets et monnaies en circulation, évolution hebdo et mensuelle.
5. <h2>Tourisme et diaspora</h2> — recettes touristiques cumulées + revenus du travail cumulés (deux sujets phares de l'économie tunisienne, à mettre en valeur).
6. <h2>Taux de change</h2> — bilan hebdomadaire EUR/TND, USD/TND, autres devises notables.
7. <h2>Trésor et marché obligataire</h2> — compte courant Trésor, bons du Trésor.
8. <h2>Marché boursier</h2> — TUNINDEX si disponible.
9. <h2>Perspectives</h2> — enjeux pour la semaine suivante, factuel.
10. Tableau récapitulatif HTML des indicateurs clés avec valeur, variation hebdo, unité.
11. Mention des sources (BCT, INS pour l'inflation si citée) et méthodologie.

CONTRAINTES
- 1000 à 1300 mots.
- Toujours citer la BCT comme source officielle.
- Pas d'émoji.
- À la PREMIÈRE occurrence, utilise le libellé complet suivi de l'abréviation (« Taux Moyen du Marché Monétaire (TMM) »)."""


SUNDAY_SYSTEM_PROMPT = BCT_GLOSSARY + "\n────────────────────────────────────────\n\n" + _BODY


def _enrich_indicators(indicateurs: dict[str, Any]) -> dict[str, Any]:
    """Ajoute le libellé humain BCT à chaque indicateur pour que Claude voie un nom parlant."""
    enriched: dict[str, Any] = {}
    for code, info in indicateurs.items():
        enriched[code] = {
            "libelle_officiel_bct": label_for(code),
            **info,
        }
    return enriched


def _compute_solde_exterieur(indicateurs: dict[str, Any]) -> dict[str, Any] | None:
    """
    Calcule le rapprochement éditorial 'solde extérieur' si les 3 composants sont disponibles.
    Renvoie un dict avec la décomposition, ou None si données incomplètes.
    """
    components = {
        "recettes_touristiques": indicateurs.get("recettes_touristiques", {}).get("valeur_actuelle"),
        "revenus_travail_diaspora": indicateurs.get("revenus_travail_diaspora", {}).get("valeur_actuelle"),
        "service_dette_exterieure": indicateurs.get("service_dette_exterieure", {}).get("valeur_actuelle"),
    }
    if any(v is None for v in components.values()):
        return {
            "calcul_possible": False,
            "raison": "Une ou plusieurs composantes manquent (recettes touristiques, revenus diaspora, ou service dette).",
            "composantes_disponibles": {k: v for k, v in components.items() if v is not None},
        }
    solde = components["recettes_touristiques"] + components["revenus_travail_diaspora"] - components["service_dette_exterieure"]
    return {
        "calcul_possible": True,
        "formule": "Recettes touristiques cumulées + Revenus du travail cumulés (diaspora) − Service de la dette extérieure cumulés",
        "composantes": components,
        "solde_exterieur_mdt": round(solde, 2),
        "unite": "MDT",
        "interpretation": (
            "Indicateur composite à lire conjointement avec les avoirs nets en devises. "
            "Un solde positif signifie que les rentrées de devises (tourisme + diaspora) "
            "dépassent les sorties pour le service de la dette."
        ),
    }


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
    enriched_indicators = _enrich_indicators(indicateurs_complets)
    solde_exterieur = _compute_solde_exterieur(indicateurs_complets)

    payload = {
        "date_iso": date_jour.isoformat(),
        "semaine_du": semaine_debut.isoformat(),
        "semaine_au": date_jour.isoformat(),
        "source_principale": "Banque Centrale de Tunisie (BCT)",
        "indicateurs_critiques_priorite_haute": [
            "avoirs_nets_mdt",
            "avoirs_nets_jours_import",
            "refinancement",
            "billets_circulation",
        ],
        "devises_taux_du_jour": devises_actuelles,
        "devises_variations_hebdomadaires": devises_variations,
        "indicateurs": enriched_indicators,
        "rapprochement_solde_exterieur": solde_exterieur,
    }

    return f"""Voici les données économiques complètes de la semaine du {semaine_debut.strftime('%d/%m/%Y')} au {date_jour.strftime('%d/%m/%Y')}, issues de la BCT.

DONNÉES :

```json
{json.dumps(payload, ensure_ascii=False, indent=2, default=str)}
```

INSTRUCTIONS
1. Produis FR + EN dans la MÊME réponse JSON.
2. Identifie d'abord MENTALEMENT les 3 ou 4 informations les plus marquantes en t'appuyant en priorité sur les indicateurs listés dans `indicateurs_critiques_priorite_haute`. Puis structure l'article autour.
3. Utilise les `libelle_officiel_bct` fournis pour chaque indicateur (pas les codes techniques type `avoirs_nets_mdt`).
4. EXPLOITE le `rapprochement_solde_exterieur` quand `calcul_possible` est `true` : intègre la formule, le résultat et son interprétation dans la section "Réserves et commerce extérieur". Si `false`, dis simplement que le rapprochement n'a pas pu être calculé cette semaine.
5. Mets en VALEUR le chiffre des avoirs nets en jours d'importation (c'est le plus parlant pour le grand public).
6. Propose des rapprochements éditoriaux simples si le contexte s'y prête, sans inventer de causalité.
7. Si une donnée manque (variation hebdo non calculable, indicateur absent), dis-le explicitement, ne comble PAS.
8. Slugs : bilan-economique-tunisie-semaine-{date_jour.strftime('%Y-%m-%d')} (FR), tunisia-weekly-economic-recap-{date_jour.strftime('%Y-%m-%d')} (EN).
9. Mets particulièrement en valeur les sujets **tourisme** et **diaspora** s'ils sont présents — ce sont des sujets phares très recherchés par notre audience.

Réponds UNIQUEMENT par l'objet JSON."""


REQUIRED_FIELDS = [
    "titre_editorial", "titre_seo", "slug", "meta_description",
    "focus_keyword", "mots_cles_secondaires", "contenu_html", "categorie_suggeree",
]
REQUIRED_LANGS = ["fr", "en"]
