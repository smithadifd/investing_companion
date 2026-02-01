#!/bin/bash
# =============================================================================
# Investing Companion - Database Restore Script
# =============================================================================
# Restores a PostgreSQL backup to the database.
#
# Usage:
#   ./scripts/restore.sh /path/to/backup.sql.gz
#
# WARNINGS:
#   - This will DROP all existing data in the database!
#   - Make sure the application is stopped or in maintenance mode
#   - Always create a fresh backup before restoring
# =============================================================================

set -e  # Exit on error

# Configuration
CONTAINER_NAME="investing_db"
BACKUP_FILE="$1"

# Load environment from .env.production if it exists
if [ -f .env.production ]; then
    export $(grep -v '^#' .env.production | xargs)
fi

# Use environment variables or defaults
DB_USER="${POSTGRES_USER:-investing_prod}"
DB_NAME="${POSTGRES_DB:-investing_companion}"

echo "========================================"
echo "Investing Companion Restore"
echo "Started: $(date)"
echo "========================================"

# Validate input
if [ -z "$BACKUP_FILE" ]; then
    echo "ERROR: Please provide a backup file path"
    echo "Usage: $0 /path/to/backup.sql.gz"
    exit 1
fi

if [ ! -f "$BACKUP_FILE" ]; then
    echo "ERROR: Backup file not found: ${BACKUP_FILE}"
    exit 1
fi

# Check if container is running
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "ERROR: Container ${CONTAINER_NAME} is not running"
    exit 1
fi

# Verify backup integrity
echo "Verifying backup integrity..."
if ! gunzip -t "$BACKUP_FILE" 2>/dev/null; then
    echo "ERROR: Backup file appears to be corrupt!"
    exit 1
fi
echo "Backup file verified"

# Confirm restore
echo ""
echo "WARNING: This will restore the database from:"
echo "  ${BACKUP_FILE}"
echo ""
echo "This will DROP all existing data in database '${DB_NAME}'!"
echo ""
read -p "Type 'RESTORE' to confirm: " CONFIRM

if [ "$CONFIRM" != "RESTORE" ]; then
    echo "Restore cancelled"
    exit 0
fi

# Stop dependent services
echo ""
echo "Recommendation: Stop the API and Celery services before restoring:"
echo "  docker compose -f docker-compose.prod.yml stop api celery_worker celery_beat"
echo ""
read -p "Press Enter to continue with restore..."

# Perform restore
echo "Restoring database from backup..."

# Drop and recreate database
docker exec "$CONTAINER_NAME" psql -U "$DB_USER" -d postgres -c "DROP DATABASE IF EXISTS ${DB_NAME};"
docker exec "$CONTAINER_NAME" psql -U "$DB_USER" -d postgres -c "CREATE DATABASE ${DB_NAME};"

# Restore data
gunzip -c "$BACKUP_FILE" | docker exec -i "$CONTAINER_NAME" psql -U "$DB_USER" -d "$DB_NAME"

echo ""
echo "========================================"
echo "Restore completed successfully at $(date)"
echo "========================================"
echo ""
echo "Next steps:"
echo "  1. Restart the application services"
echo "  2. Verify the data is correct"
echo "  3. Check the application health endpoint"
