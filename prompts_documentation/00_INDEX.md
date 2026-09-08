# Prompts TN-Agentic — Documentation

Ce dossier contient les prompts complets utilisés pour chaque agent éditorial.
Chaque fichier reprend fidèlement le code source situé dans
`editorial-core/app/prompts/`.

## Structure d'un prompt

Chaque agent utilise **deux blocs** :

1. **System prompt** (statique) — injecté dans le champ `system` de l'appel
   Claude. Contient :
   - Rôle éditorial (journaliste TN)
   - Ton et style attendus
   - Règle anti-hallucination
   - Structure HTML imposée
   - Contraintes de formatage
   - Schéma JSON de sortie attendu

2. **User message** (dynamique) — construit à chaque exécution avec les
   données réelles du jour, sérialisées en JSON dans le prompt.

Pour l'agent taux de change, samedi, dimanche et énergie, le **glossaire BCT**
est ajouté en préambule du system prompt. Ce glossaire est mis en cache par
Claude (prompt caching) pour économiser 90 % du coût des tokens partagés.

## Liste des fichiers

| Fichier | Agent | Fréquence | Longueur cible |
|---|---|---|---|
| `01_weather.md` | Météo 24 gouvernorats | Quotidien 5h | 450-600 mots |
| `02_exchange_rates.md` | Taux de change BCT | Quotidien 8h | 500-700 mots |
| `03_saturday_billets.md` | Billets et monnaies en circulation | Hebdo (samedi) | 600-800 mots |
| `04_sunday_recap.md` | Récap éco hebdomadaire | Hebdo (dimanche) | 1000-1300 mots |
| `05_energy_carburant.md` | Prix carburants comparés | Mensuel | 500-700 mots |
| `99_glossary_bct.md` | Glossaire BCT partagé | (préambule) | ~1500 mots |

## Format de sortie commun

Tous les agents renvoient **un objet JSON strict** avec deux clés `fr` et `en`,
chacune contenant :

```json
{
  "titre_editorial": "...",
  "titre_seo": "55-60 caractères",
  "slug": "format-lisible-AAAA-MM-JJ",
  "meta_description": "150-160 caractères",
  "focus_keyword": "...",
  "mots_cles_secondaires": ["array"],
  "contenu_html": "<p>...</p><h2>...</h2>",
  "categorie_suggeree": "Météo / Économie"
}
```

Ce schéma est validé automatiquement par le module
`app.hallucination_check` avant publication.
