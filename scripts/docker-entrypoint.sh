#!/bin/sh
# Apply Generation Store migrations before starting the container process.
set -eu

python - <<'PY'
from sombreado.config import get_settings
from sombreado.store import GenerationStore

# DATABASE_URL is the Neon pooled Runtime Secret; migrate prefers
# DATABASE_URL_UNPOOLED (direct) when set — see ADR 0006.
GenerationStore(get_settings().database_url).migrate()
PY

exec "$@"
