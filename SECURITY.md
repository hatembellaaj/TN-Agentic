# Sécurité — authentification TN-Agentic

## Ce qui est protégé

| Surface | Avant | Maintenant |
| --- | --- | --- |
| `/dashboard/*` | ouvert | session obligatoire (redirection vers `/dashboard/login`) |
| `/dashboard/backfill` | ouvert | rôle **admin** |
| `/api/docs`, `/api/redoc`, `/api/openapi.json` | ouvert | utilisateur connecté (ou jeton / clé API pour le JSON) |
| `/api/agents/*` | ouvert | JWT, session ou clé de service (n8n) |
| `/api/history/*` | ouvert | JWT, session ou clé de service |
| `/api/admin/*` | ouvert | rôle **admin** uniquement |
| `/scraper/`, `/scraper-bct/`, `/scraper-energy/` | exposés via nginx | **retirés de nginx**, réseau Docker interne uniquement |
| `/health` | ouvert | ouvert (n'expose plus le backend de publication) |

Non modifié dans ce lot (à traiter) : `/adminer/` (à protéger ou retirer en prod), `autoindex` sur `/articles/`, HTTPS.

## Modes d'authentification

| Qui | Comment | Durée |
| --- | --- | --- |
| Humain sur le dashboard | formulaire `/dashboard/login` → cookie `tn_session` (JWT, `HttpOnly`, `SameSite=Strict`) | `SESSION_EXPIRE_MINUTES` (8 h) |
| Humain dans Swagger | ouvert depuis le dashboard : la session est réutilisée. Sinon bouton **Authorize** → schéma *JWT* (login / mot de passe) | `ACCESS_TOKEN_EXPIRE_MINUTES` (1 h) |
| Client API / script | `POST /api/auth/token` (form `username`, `password`) → `Authorization: Bearer <jwt>` | 1 h |
| n8n, cron | en-tête `X-API-Key: <N8N_SERVICE_API_KEY>` | permanent (rotation manuelle) |

Rôles : `admin` (tout, dont gestion des comptes), `editor` (dashboard, agents, historique), `service` (agents + historique, pas d'admin).

Protections incluses : mots de passe bcrypt (12 caractères min.), anti brute-force (5 échecs / 15 min par IP + login), révocation de tous les jetons d'un compte (`token_version`) au changement de mot de passe, à la désactivation ou via `POST /api/auth/logout-all`, contrôle d'origine (CSRF) sur les requêtes POST authentifiées par cookie, pas de redirection ouverte après login, en-têtes `X-Frame-Options`, `nosniff`, `Cache-Control: no-store`.

## Mise en service

```bash
# 1. Générer les secrets et les coller dans .env
make gen-secrets
#    JWT_SECRET_KEY=...        (obligatoire, sinon editorial-core refuse de démarrer)
#    N8N_SERVICE_API_KEY=...

# 2. Reconstruire et migrer (crée la table users)
docker compose up -d --build editorial-core n8n nginx
make migrate

# 3. Créer le premier admin
make create-admin LOGIN=hatem
#    (ou INITIAL_ADMIN_USERNAME / INITIAL_ADMIN_PASSWORD dans .env, puis les vider)

# 4. Réimporter les workflows n8n (ils envoient désormais X-API-Key)
docker compose exec n8n n8n import:workflow --separate --input=/workflows/
```

Comptes supplémentaires : `make create-editor LOGIN=journaliste1`, `make users`, ou via Swagger `POST /api/auth/users` (admin).

## Exemples d'appel

```bash
# Obtenir un jeton
TOKEN=$(curl -s -X POST http://<host>:18090/api/auth/token \
  -d 'username=hatem' -d 'password=********' | jq -r .access_token)

# Appeler l'API
curl -H "Authorization: Bearer $TOKEN" "http://<host>:18090/api/history/exchange-rates?devise=EUR"

# Appel machine (n8n / cron)
curl -X POST -H "X-API-Key: $N8N_SERVICE_API_KEY" http://<host>:18090/api/agents/weather/run
```

## Passage en HTTPS

Dès qu'un certificat est en place : `COOKIE_SECURE=true` dans `.env`, et remettre `N8N_SECURE_COOKIE` à `true` dans `docker-compose.yml`.
