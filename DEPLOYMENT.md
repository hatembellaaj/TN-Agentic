# Guide de déploiement — Sprint 1

Ce document décrit la mise en route locale **et** le déploiement sur le VPS OVH.

## 1. Pré-requis

- Docker 24+ et Docker Compose v2 (`docker compose version`)
- Une clé OpenWeatherMap (gratuite jusqu'à 1000 req/jour) : https://openweathermap.org/api
- Une clé Anthropic Claude : https://console.anthropic.com/
- Un bot Telegram créé via @BotFather, et le `chat_id` du journaliste validateur
- Au moins 2 Go de RAM libre

## 2. Configuration

```bash
cp .env.example .env
```

Éditer `.env` et renseigner au minimum :

- `POSTGRES_PASSWORD` (générer un mot de passe robuste)
- `OPENWEATHERMAP_API_KEY`
- `ANTHROPIC_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID` (déjà rempli avec 29991777, le numéro du cahier des charges)
- `N8N_BASIC_AUTH_PASSWORD`

Le `DATABASE_URL` doit utiliser le même mot de passe que `POSTGRES_PASSWORD`.

## 3. Démarrage

```bash
docker compose build
docker compose up -d
docker compose ps     # vérifier que tous les services sont "running"
```

## 4. Initialisation de la base

Une seule fois après le premier `up` :

```bash
# Migrations Alembic
docker compose exec editorial-core alembic upgrade head

# Seed des 24 gouvernorats
docker compose exec editorial-core python -m app.seed
```

## 5. Vérification

| URL | Attendu |
| --- | --- |
| http://localhost/dashboard/ | Dashboard, table vide au début |
| http://localhost/api/docs | Swagger editorial-core |
| http://localhost/scraper/docs | Swagger scraper-weather |
| http://localhost/n8n/ | UI n8n (login admin / mdp .env) |
| http://localhost/adminer/ | Adminer (server: postgres) |

## 6. Premier run manuel

Sans attendre 6h00, déclencher une exécution :

```bash
curl -X POST http://localhost/api/agents/weather/run -H 'Content-Type: application/json' -d '{}'
```

Ou via Swagger UI : http://localhost/api/docs → `POST /api/agents/weather/run` → "Try it out".

Le pipeline complet (collecte 24 gouvernorats → Claude → fichiers HTML → Telegram) prend ~30 à 90 secondes.

## 7. Vérification du résultat

1. **Dashboard** : http://localhost/dashboard/ doit lister 2 articles (fr + en).
2. **Article détaillé** : cliquer sur "Détail →" pour voir le rendu HTML, les méta Yoast, et les coûts Claude.
3. **Fichiers générés** : `ls -l ./output/articles/$(date +%Y)/$(date +%m)/$(date +%d)/`
4. **Aperçu navigateur** : http://localhost/articles/AAAA/MM/JJ/meteo-fr.html
5. **Telegram** : un message doit arriver au `TELEGRAM_CHAT_ID` avec les liens vers le dashboard.

## 8. Activation du cron n8n

1. UI n8n → **Workflows** → **Import from File** → `n8n/workflows/agent-meteo.json`
2. Activer le workflow en haut à droite.
3. Le cron tournera désormais tous les jours à 6h00 (timezone Africa/Tunis).

## 9. Déploiement sur VPS OVH (production)

Sur le VPS Ubuntu 22.04 :

```bash
# Installation Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker

# Récupération du projet
git clone <repo> /opt/tn-agentic && cd /opt/tn-agentic

# Configuration
cp .env.example .env && nano .env   # remplir avec valeurs de prod

# Démarrage
docker compose up -d
docker compose exec editorial-core alembic upgrade head
docker compose exec editorial-core python -m app.seed
```

### Activer HTTPS avec Let's Encrypt

Une fois le DNS pointant vers le VPS :

```bash
sudo apt install -y certbot
sudo certbot certonly --webroot -w /opt/tn-agentic/output --domain agent.tunisienumerique.com
```

Puis adapter `nginx/conf.d/default.conf` pour ajouter un bloc `server { listen 443 ssl; ... }` et monter les certificats dans le service `nginx` du `docker-compose.yml`.

### Sécurité minimale

- Firewall UFW : autoriser uniquement 22, 80, 443
- SSH par clé uniquement (désactiver mot de passe dans `/etc/ssh/sshd_config`)
- Fail2ban sur SSH
- `unattended-upgrades` activé

### Backups PostgreSQL

Cron host (recommandé) :

```cron
0 3 * * * docker compose -f /opt/tn-agentic/docker-compose.yml exec -T postgres pg_dump -U tn_agent tn_agentic | gzip > /var/backups/tn-agentic/$(date +\%Y\%m\%d).sql.gz
```

## 10. Bascule vers WordPress (quand l'API sera dispo)

1. Sur les WP FR et EN, créer un user `tn_agent_ia` (rôle Editor).
2. Générer un Application Password pour chacun (Users → Profile → Application Passwords).
3. Renseigner dans `.env` :
   - `PUBLISHER_BACKEND=wordpress`
   - `WP_FR_BASE_URL`, `WP_FR_USERNAME`, `WP_FR_APP_PASSWORD`
   - idem pour EN
4. `docker compose restart editorial-core`

Aucune autre modification de code n'est nécessaire — le pattern Publisher abstrait s'occupe du swap.

## 11. Commandes utiles

```bash
# Logs en live
docker compose logs -f editorial-core
docker compose logs -f scraper-weather

# Shell dans un container
docker compose exec editorial-core bash

# Statut d'une exécution dans la base
docker compose exec postgres psql -U tn_agent -d tn_agentic \
  -c "SELECT execution_id, agent_step, status, message FROM execution_logs ORDER BY timestamp DESC LIMIT 20;"

# Coûts Claude cumulés
docker compose exec postgres psql -U tn_agent -d tn_agentic \
  -c "SELECT modele_utilise, SUM(cout_estime_usd) AS total_usd, COUNT(*) AS calls FROM claude_logs GROUP BY modele_utilise;"

# Reset complet (⚠️ supprime les données)
docker compose down -v
```

## 12. Troubleshooting

| Symptôme | Cause probable | Solution |
| --- | --- | --- |
| `editorial-core` redémarre en boucle | DB pas prête / migrations non appliquées | `docker compose exec editorial-core alembic upgrade head` |
| Dashboard vide après run | Seed gouvernorats pas exécuté | `docker compose exec editorial-core python -m app.seed` |
| 401 OpenWeatherMap | Clé API invalide ou en attente d'activation | Une nouvelle clé OWM met ~10 min à s'activer |
| 400 Telegram MarkdownV2 | Caractères mal échappés | Vérifier les logs `editorial-core` |
| Halluc. "suspected" sur tous les articles | Le pool autorisé est trop strict | Ajuster `TEMPERATURE_TOLERANCE` dans `app/hallucination_check.py` |
