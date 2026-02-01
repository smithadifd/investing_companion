#!/bin/bash
# =============================================================================
# Investing Companion - Database Backup Script
# =============================================================================
# Creates timestamped PostgreSQL backups with automatic rotation.
#
# Usage:
#   ./scripts/backup.sh                    # Manual backup
#   ./scripts/backup.sh /path/to/backups   # Custom backup directory
#
# Cron example (daily at 2 AM):
#   0 2 * * * /path/to/investing_companion/scripts/backup.sh >> /var/log/investing_backup.log 2>&1
#
# For Synology Task Scheduler:
#   - Create a User-defined script task
#   - Run as root or docker user
#   - Schedule as needed (recommended: daily)
# =============================================================================

set -e  # Exit on error

# Configuration
BACKUP_DIR="${1:-./backups}"
CONTAINER_NAME="investing_db"
RETENTION_DAYS=30
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="investing_companion_${DATE}.sql.gz"

# Load environment from .env.production if it exists
if [ -f .env.production ]; then
    export $(grep -v '^#' .env.production | xargs)
fi

# Use environment variables or defaults
DB_USER="${POSTGRES_USER:-investing_prod}"
DB_NAME="${POSTGRES_DB:-investing_companion}"

echo "========================================"
echo "Investing Companion Backup"
echo "Started: $(date)"
echo "========================================"

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

# Check if container is running
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "ERROR: Container ${CONTAINER_NAME} is not running"
    exit 1
fi

# Create backup
echo "Creating backup: ${BACKUP_FILE}"
docker exec "$CONTAINER_NAME" pg_dump -U "$DB_USER" "$DB_NAME" | gzip > "${BACKUP_DIR}/${BACKUP_FILE}"

# Verify backup
BACKUP_SIZE=$(ls -lh "${BACKUP_DIR}/${BACKUP_FILE}" | awk '{print $5}')
echo "Backup created: ${BACKUP_DIR}/${BACKUP_FILE} (${BACKUP_SIZE})"

# Test backup integrity
if ! gunzip -t "${BACKUP_DIR}/${BACKUP_FILE}" 2>/dev/null; then
    echo "ERROR: Backup file appears to be corrupt!"
    exit 1
fi
echo "Backup integrity verified"

# Cleanup old backups
echo "Cleaning up backups older than ${RETENTION_DAYS} days..."
DELETED_COUNT=$(find "$BACKUP_DIR" -name "investing_companion_*.sql.gz" -mtime +$RETENTION_DAYS -delete -print | wc -l)
echo "Deleted ${DELETED_COUNT} old backup(s)"

# Show remaining backups
BACKUP_COUNT=$(find "$BACKUP_DIR" -name "investing_companion_*.sql.gz" | wc -l)
TOTAL_SIZE=$(du -sh "$BACKUP_DIR" 2>/dev/null | cut -f1)
echo ""
echo "Backup Summary:"
echo "  - Total backups: ${BACKUP_COUNT}"
echo "  - Total size: ${TOTAL_SIZE}"
echo "  - Latest backup: ${BACKUP_FILE}"

echo ""
echo "Backup completed successfully at $(date)"
echo "========================================"
