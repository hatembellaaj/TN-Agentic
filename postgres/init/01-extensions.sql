-- Extensions PostgreSQL utiles pour le projet
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- Fuseau horaire par défaut (informatif, la TZ effective est dans postgresql.conf)
SET timezone = 'UTC';
