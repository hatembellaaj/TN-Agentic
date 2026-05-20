# TN-Agentic — Agent Journaliste IA TN (POC)

Système d'agent journaliste IA pour Tunisie Numérique. Phase POC — Sprint 1 (agent météo bout en bout).

## Architecture

Sept conteneurs Docker orchestrés via `docker-compose` :

| Service | Rôle | Image / Stack |
| --- | --- | --- |
| `nginx` | Reverse proxy SSL + serveur des articles HTML statiques | nginx:alpine |
| `postgres` | Base de données métier | postgres:15 |
| `n8n` | Orchestrateur de workflows (cron 6h00) | n8nio/n8n |
| `scraper-weather` | Collecte OpenWeatherMap pour les 24 gouvernorats | Python 3.11 + httpx + FastAPI |
| `editorial-core` | Génération Claude + Publisher + Telegram + Dashboard | Python 3.11 + FastAPI + Jinja2 + HTMX |
| `adminer` | UI debug PostgreSQL (optionnel, derrière basic auth) | adminer:latest |
| `backup-runner` | Backup quotidien `pg_dump` → OVH Object Storage | alpine + rclone |

## Prérequis

- Docker 24+ et Docker Compose v2
- Un VPS Ubuntu 22.04 LTS (ou environnement local pour test)
- Une clé API OpenWeatherMap (gratuite jusqu'à 1000 req/jour)
- Une clé API Anthropic (Claude)
- Un bot Telegram (créé via @BotFather) et le `chat_id` du journaliste validateur

## Démarrage rapide (local)

```bash
# 1. Cloner et configurer
cp .env.example .env
# Editer .env avec les vraies clés API

# 2. Démarrer la stack
docker compose up -d

# 3. Appliquer les migrations Alembic et le seed des gouvernorats
docker compose exec editorial-core alembic upgrade head
docker compose exec editorial-core python -m app.seed

# 4. Vérifier (HOST_PORT par défaut = 18090, configurable dans .env)
# Dashboard               : http://<host>:18090/dashboard/
# Swagger editorial-core  : http://<host>:18090/api/docs
# Swagger scraper-weather : http://<host>:18090/scraper/docs
# n8n                     : http://<host>:18090/n8n/
# Adminer                 : http://<host>:18090/adminer/
```

**Note sur les ports.** Seul nginx est exposé vers l'extérieur (port hôte `HOST_PORT`, défaut 18090). Tous les autres services (postgres, scraper-weather, editorial-core, n8n, adminer) restent **internes** au réseau Docker `tn-net` et n'entrent en conflit avec aucune autre stack du serveur.

## Déclencher une exécution manuelle

Sans attendre 6h00 :

```bash
curl -X POST http://localhost/api/agents/weather/run
```

Ou via Swagger UI : http://localhost/api/docs → `POST /agents/weather/run` → "Try it out".

## Publication

Pendant que l'API WordPress n'est pas disponible, les articles générés sortent en fichiers HTML dans `./output/articles/AAAA/MM/JJ/` avec leur sidecar JSON (méta Yoast). Ces fichiers sont servis en lecture par Nginx sur `/articles/`.

Le pattern `Publisher` est abstrait : pour basculer vers WordPress quand l'API sera dispo, il suffit de positionner `PUBLISHER_BACKEND=wordpress` dans `.env` et de fournir les credentials WP.

## Structure du dépôt

```
TN-Agentic/
├── docker-compose.yml
├── .env.example
├── nginx/                  Configuration Nginx
├── postgres/init/          Scripts d'init PostgreSQL
├── n8n/workflows/          Workflows n8n exportés en JSON
├── scraper-weather/        Service de collecte météo
├── editorial-core/         Cœur éditorial (Claude + Publisher + Dashboard)
└── output/articles/        Sortie FilePublisher (HTML + sidecar JSON)
```

## Sprint 1 — Livrables

- [x] Infrastructure Docker Compose opérationnelle
- [x] Schéma PostgreSQL complet + seed des 24 gouvernorats
- [x] Scraper OpenWeatherMap pour les 24 gouvernorats
- [x] Génération Claude bilingue FR + EN dans un seul appel
- [x] Vérification anti-hallucination post-génération
- [x] FilePublisher (sortie HTML + sidecar JSON Yoast)
- [x] Notification Telegram avec liens dashboard
- [x] Dashboard de validation et traçabilité
- [x] Swagger / OpenAPI auto-généré
- [x] Workflow n8n agent météo (cron 6h00)

## Roadmap

- **Sprint 2** : Ajouter `scraper-bct` (Playwright) pour les taux de change quotidiens
- **Sprint 3** : Agents hebdomadaires (samedi billets, dimanche récap éco)
- **MVP** : Activer `WordPressPublisher`, langue arabe, optimisation SEO avancée

## Licence

Propriété de Tunisie Numérique / MDWEB.
