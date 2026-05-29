#!/bin/sh
# entrypoint.sh — run alembic upgrade head with retry, then exec the main process.
#
# Environment variables:
#   ALEMBIC_RETRY_ATTEMPTS  max attempts before giving up (default: 20)
#   ALEMBIC_RETRY_SLEEP     seconds between attempts (default: 3)
#
# Skips migration when METADATA_STORE=memory or METADATA_STORE=file
# (no relational DB involved in those modes).
set -e

METADATA_STORE="${METADATA_STORE:-postgres}"

if [ "$METADATA_STORE" != "memory" ] && [ "$METADATA_STORE" != "file" ]; then
    MAX_ATTEMPTS="${ALEMBIC_RETRY_ATTEMPTS:-20}"
    SLEEP_SECONDS="${ALEMBIC_RETRY_SLEEP:-3}"
    attempt=1

    echo "Running alembic upgrade head (max ${MAX_ATTEMPTS} attempts, ${SLEEP_SECONDS}s sleep)..."
    until alembic upgrade head; do
        if [ "$attempt" -ge "$MAX_ATTEMPTS" ]; then
            echo "ERROR: alembic upgrade head failed after ${MAX_ATTEMPTS} attempts. Exiting."
            exit 1
        fi
        echo "Attempt ${attempt}/${MAX_ATTEMPTS} failed — DB not ready? Retrying in ${SLEEP_SECONDS}s..."
        attempt=$((attempt + 1))
        sleep "$SLEEP_SECONDS"
    done
    echo "alembic upgrade head completed."
fi

exec "$@"
