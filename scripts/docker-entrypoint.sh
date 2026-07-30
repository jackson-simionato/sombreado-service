#!/bin/sh
# Apply Generation Store migrations before starting the container process.
set -eu

python - <<'PY'
from sombreado.config import get_settings
from sombreado.store import GenerationStore

GenerationStore(get_settings().sqlite_database_path).migrate()
PY

exec "$@"
