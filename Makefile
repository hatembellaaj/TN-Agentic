# ============================================================
# TN-Agentic — Makefile
# Commandes courantes pour le développement et l'exploitation
# ============================================================

.PHONY: help build up down restart logs ps init run-weather shell-core shell-scraper db-shell \
        migrate seed reset clean lint test status

help: ## Affiche cette aide
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ----------------------------------------------------------
# Cycle de vie Docker
# ----------------------------------------------------------
build: ## Construit les images Docker
	docker compose build

up: ## Démarre la stack
	docker compose up -d

down: ## Arrête la stack (préserve les volumes)
	docker compose down

restart: ## Redémarre tous les services
	docker compose restart

ps: ## Affiche l'état des conteneurs
	docker compose ps

logs: ## Suit les logs de tous les services
	docker compose logs -f --tail=100

logs-core: ## Suit les logs editorial-core
	docker compose logs -f --tail=200 editorial-core

logs-scraper: ## Suit les logs scraper-weather
	docker compose logs -f --tail=200 scraper-weather

# ----------------------------------------------------------
# Initialisation
# ----------------------------------------------------------
init: up migrate seed ## Démarre + applique migrations + seed des gouvernorats
	@echo "✓ Stack prête. Dashboard : http://localhost/dashboard/"

migrate: ## Applique les migrations Alembic
	docker compose exec editorial-core alembic upgrade head

seed: ## Insère les 24 gouvernorats
	docker compose exec editorial-core python -m app.seed

# ----------------------------------------------------------
# Exécution
# ----------------------------------------------------------
run-weather: ## Déclenche l'agent météo manuellement (synchrone)
	@PORT=$$(grep '^HOST_PORT=' .env | cut -d= -f2); \
	PORT=$${PORT:-18090}; \
	echo "→ POST http://localhost:$$PORT/api/agents/weather/run" ; \
	curl -s -X POST http://localhost:$$PORT/api/agents/weather/run \
	  -H 'Content-Type: application/json' -d '{}' | python3 -m json.tool

run-rates: ## Déclenche l'agent taux de change BCT manuellement (synchrone)
	@PORT=$$(grep '^HOST_PORT=' .env | cut -d= -f2); \
	PORT=$${PORT:-18090}; \
	echo "→ POST http://localhost:$$PORT/api/agents/exchange-rates/run" ; \
	curl -s -X POST http://localhost:$$PORT/api/agents/exchange-rates/run \
	  -H 'Content-Type: application/json' -d '{}' | python3 -m json.tool

preview-bct: ## Aperçu sans écriture base : voir ce que le parser BCT extrait
	@PORT=$$(grep '^HOST_PORT=' .env | cut -d= -f2); \
	PORT=$${PORT:-18090}; \
	curl -s http://localhost:$$PORT/scraper-bct/preview | python3 -m json.tool

# ----------------------------------------------------------
# Accès / debug
# ----------------------------------------------------------
shell-core: ## Shell bash dans editorial-core
	docker compose exec editorial-core bash

shell-scraper: ## Shell bash dans scraper-weather
	docker compose exec scraper-weather bash

db-shell: ## Console psql
	docker compose exec postgres psql -U $$(grep POSTGRES_USER .env | cut -d= -f2) -d $$(grep POSTGRES_DB .env | cut -d= -f2)

status: ## Récap rapide depuis la base
	@docker compose exec -T postgres psql -U $$(grep POSTGRES_USER .env | cut -d= -f2) -d $$(grep POSTGRES_DB .env | cut -d= -f2) -c "\
	  SELECT theme, langue, COUNT(*) AS nb FROM articles_generated GROUP BY theme, langue ORDER BY theme, langue;"
	@docker compose exec -T postgres psql -U $$(grep POSTGRES_USER .env | cut -d= -f2) -d $$(grep POSTGRES_DB .env | cut -d= -f2) -c "\
	  SELECT modele_utilise, COUNT(*) AS calls, SUM(cout_estime_usd) AS total_usd FROM claude_logs GROUP BY modele_utilise;"

# ----------------------------------------------------------
# Reset / nettoyage
# ----------------------------------------------------------
reset: ## ⚠ Détruit tous les volumes (DB, n8n) et reconstruit
	docker compose down -v
	$(MAKE) init

clean: ## Supprime les articles HTML générés
	rm -rf output/articles/2*

# ----------------------------------------------------------
# Qualité (à lancer en local hors Docker, optionnel)
# ----------------------------------------------------------
lint: ## Vérification syntaxique Python (local)
	python3 -m compileall -q editorial-core scraper-weather

test: ## Placeholder pour les tests à venir
	@echo "Tests à implémenter (pytest dans editorial-core/tests/ et scraper-weather/tests/)"
