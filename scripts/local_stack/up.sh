#!/usr/bin/env bash
# Disposable local stack: Postgres (real migration chain) + PostgREST behind
# /rest/v1. Every credential here is a local constant, never a production value.
set -euo pipefail
cd "$(dirname "$0")/../.."

NET=nashr-local
JWT_SECRET="local-only-jwt-secret-not-for-production-0000"
docker network inspect "$NET" >/dev/null 2>&1 || docker network create "$NET" >/dev/null
docker rm -f nashr-local-pg nashr-local-rest nashr-local-proxy >/dev/null 2>&1 || true

docker run -d --name nashr-local-pg --network "$NET" -p 55432:5432 \
  -e POSTGRES_PASSWORD=local-postgres postgres:16-alpine >/dev/null
until docker exec nashr-local-pg pg_isready -U postgres -q; do sleep 1; done
sleep 2

apply() { docker exec -i nashr-local-pg psql -q -v ON_ERROR_STOP=1 -U postgres -d postgres >/dev/null; }
apply < scripts/local_stack/bootstrap.sql
for migration in supabase/migrations/*.sql; do
  echo "migrate $(basename "$migration")"
  apply < "$migration"
done

docker run -d --name nashr-local-rest --network "$NET" \
  -e PGRST_DB_URI="postgres://authenticator:local-authenticator@nashr-local-pg:5432/postgres" \
  -e PGRST_DB_SCHEMAS=public -e PGRST_DB_ANON_ROLE=anon \
  -e PGRST_JWT_SECRET="$JWT_SECRET" --network-alias postgrest postgrest/postgrest:v12.2.3 >/dev/null
docker run -d --name nashr-local-proxy --network "$NET" -p 54321:8000 \
  -v "$(pwd -W 2>/dev/null || pwd)/scripts/local_stack/Caddyfile:/etc/caddy/Caddyfile:ro" \
  caddy:2-alpine >/dev/null
echo "stack up: postgres :55432, rest http://127.0.0.1:54321/rest/v1"
