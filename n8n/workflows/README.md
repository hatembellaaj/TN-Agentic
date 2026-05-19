# Workflows n8n

## Import des workflows

Les workflows JSON de ce dossier ne sont pas chargés automatiquement par n8n (le projet n8n nécessite un import manuel ou via l'API). Pour les activer :

### Via l'UI n8n

1. Aller sur `http://localhost/n8n/` (login admin / `N8N_BASIC_AUTH_PASSWORD`).
2. Menu **Workflows** → **Import from File** → sélectionner `agent-meteo.json`.
3. Cliquer **Activate** en haut à droite pour activer le déclenchement cron.

### Via l'API n8n

```bash
docker compose exec n8n n8n import:workflow --input=/workflows/agent-meteo.json
docker compose exec n8n n8n update:workflow --id=<workflow-id> --active=true
```

## Workflows fournis (Sprint 1)

| Fichier | Déclenchement | Action |
| --- | --- | --- |
| `agent-meteo.json` | Cron `0 6 * * *` Africa/Tunis | POST `http://editorial-core:8000/api/agents/weather/run` |

## Sprints suivants

- Sprint 2 : `agent-taux-change.json` — cron `45 9 * * 1-5`
- Sprint 3 : `agent-samedi.json`, `agent-dimanche.json` — cron `0 10 * * 6` et `0 10 * * 0`
- Scraper indicateurs BCT : `scraper-indicateurs.json` — cron `0 10 * * 1-5`
