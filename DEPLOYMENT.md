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

Toutes les URLs passent par le port `HOST_PORT` (défaut **18090**). Remplacer `<host>` par `localhost` en local, ou par l'IP/domaine du serveur en production.

| URL | Attendu |
| --- | --- |
| http://&lt;host&gt;:18090/dashboard/ | Dashboard, table vide au début |
| http://&lt;host&gt;:18090/api/docs | Swagger editorial-core |
| http://&lt;host&gt;:18090/scraper/docs | Swagger scraper-weather |
| http://&lt;host&gt;:18090/n8n/ | UI n8n (login admin / mdp .env) |
| http://&lt;host&gt;:18090/adminer/ | Adminer (server: postgres) |

### Si 18090 est déjà pris

Éditer `.env` :
```
HOST_PORT=18091   # ou tout autre port libre
PUBLIC_BASE_URL=http://localhost:18091
```
Puis `docker compose up -d` (pas besoin de rebuild).

Vérifier les ports déjà occupés sur le serveur :
```bash
docker ps --format "table {{.Names}}\t{{.Ports}}" | grep -oP '0\.0\.0\.0:\K[0-9]+' | sort -un
# ou
ss -tlnp | grep LISTEN
```

### Intégrer avec un reverse proxy externe (jwilder/nginx-proxy)

Si tu utilises déjà `jwilder/nginx-proxy` + `letsencrypt-nginx-proxy-companion` sur le serveur, tu peux **ne pas exposer de port** et router via VIRTUAL_HOST :

```yaml
# dans docker-compose.yml, service nginx :
nginx:
  # ports: []                                  # commenter la mapping
  expose:
    - "80"
  environment:
    VIRTUAL_HOST: agent.tunisienumerique.com
    LETSENCRYPT_HOST: agent.tunisienumerique.com
    LETSENCRYPT_EMAIL: tech@tunisienumerique.com
  networks:
    - tn-net
    - nginx-proxy   # rejoindre le réseau de jwilder/nginx-proxy

networks:
  tn-net:
  nginx-proxy:
    external: true
    name: <nom-du-réseau-de-nginx-proxy>   # docker network ls pour le trouver
```
Puis adapter `PUBLIC_BASE_URL=https://agent.tunisienumerique.com` dans `.env`.

## 6. Premier run manuel

Sans attendre 6h00, déclencher une exécution :

```bash
curl -X POST http://localhost:18090/api/agents/weather/run \
  -H 'Content-Type: application/json' -d '{}'
```

Ou via Swagger UI : http://&lt;host&gt;:18090/api/docs → `POST /api/agents/weather/run` → "Try it out".

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

## 10. Bascule vers WordPress (authentification JWT)

L'agent publie en brouillon (`status=draft`) via l'API REST WordPress avec authentification JWT.

### Pré-requis côté WordPress

1. Installer et activer le plugin **JWT Authentication for WP REST API** :
   https://wordpress.org/plugins/jwt-authentication-for-wp-rest-api/
2. Dans `wp-config.php`, ajouter (avant `/* That's all... */`) :
   ```php
   define('JWT_AUTH_SECRET_KEY', 'remplacer-par-une-chaine-aleatoire-longue');
   define('JWT_AUTH_CORS_ENABLE', true);
   ```
3. (Optionnel mais recommandé) Créer un utilisateur dédié à l'agent avec un rôle **Editor** et un mot de passe robuste.

### Configuration côté agent

Dans `.env` :

```
PUBLISHER_BACKEND=wordpress

# Site français
WP_FR_BASE_URL=https://www.tunisienumerique.com
WP_FR_USERNAME=root
WP_FR_PASSWORD=ton_mot_de_passe

# Site anglais (vide = on publie sur le même WP que FR)
WP_EN_BASE_URL=
WP_EN_USERNAME=
WP_EN_PASSWORD=
```

Puis :

```bash
docker compose restart editorial-core
```

### Vérifier la configuration sans publier

```bash
# Test connexion JWT (n'écrit rien sur WP, juste valide les identifiants)
curl -s -X POST 'http://localhost:18090/api/admin/wordpress-test?langue=fr' | python3 -m json.tool

# Statut du publisher actuel
curl -s http://localhost:18090/api/admin/publisher-status | python3 -m json.tool
```

Attendu en cas de succès :
```json
{
  "ok": true,
  "base_url": "https://www.tunisienumerique.com",
  "username": "root",
  "token_preview": "eyJ0eXAiOiJKV1QiLCJhbGciO…",
  "token_full_length": 256
}
```

Erreurs courantes :
| Symptôme | Cause | Action |
| --- | --- | --- |
| `http_status: 404` | Plugin JWT pas installé/activé | Installer + activer le plugin sur WP |
| `http_status: 403` ou `[jwt_auth] incorrect_password` | Identifiants invalides | Vérifier user/password dans `.env` |
| `[jwt_auth] secret_key_not_defined` | `JWT_AUTH_SECRET_KEY` manquant | Ajouter dans `wp-config.php` |
| Connexion refusée / timeout | URL incorrecte ou firewall | Vérifier `WP_FR_BASE_URL` et accès réseau |

### Cycle JWT

- Le token est demandé une fois puis mis en cache en mémoire (~6 jours).
- À l'expiration ou sur un 401, l'agent ré-authentifie automatiquement.
- Pas de rotation manuelle nécessaire pendant le POC.

### Comportement après bascule

À partir du moment où `PUBLISHER_BACKEND=wordpress` est actif :
- Les articles générés sont posés comme **brouillons** sur WordPress (pas de publication directe).
- La notification Telegram envoie des liens directs vers l'écran d'édition WP de chaque brouillon (`/wp-admin/post.php?post=ID&action=edit`).
- Le dashboard local affiche aussi le `wordpress_post_id` et le lien WP pour chaque article.
- Le journaliste valide manuellement chaque brouillon depuis WP avant publication finale.

### Retour à FilePublisher si besoin

```
PUBLISHER_BACKEND=file
```
puis `docker compose restart editorial-core`. Aucune migration ni code à toucher — c'est juste un swap d'adaptateur côté Publisher.

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
