#!/bin/bash
#
# Droplet MySQL backup -> S3 (run from cron on the droplet).
# Sources the deployed env (UCFP_DB_*) and uploads a gzipped mysqldump.
#
# The S3 destination is operator-specific: define UCFP_BACKUP_S3_BUCKET (and
# optionally UCFP_BACKUP_S3_PREFIX) in the deployed /opt/ucfp/ucfp.sh, which is
# sourced below, so the bucket name stays out of the repo.

set -e

. /opt/ucfp/ucfp.sh

S3_BUCKET="${UCFP_BACKUP_S3_BUCKET:?Set UCFP_BACKUP_S3_BUCKET in /opt/ucfp/ucfp.sh}"
S3_PREFIX="${UCFP_BACKUP_S3_PREFIX:-ucfp/mysql-backups}"

TODAY=$(date +%A)         # e.g., Monday, Tuesday
DAY=$(date +%d)           # e.g., 01, 15
MONTH=$(date +%Y-%m)

if [ "$DAY" = "01" ] || [ "$DAY" = "15" ]; then
    FILENAME="${MONTH}-${DAY}.sql.gz"
else
    FILENAME="${TODAY}.sql.gz"
fi


DUMPFILE="/tmp/${FILENAME}"

# Create dump
mysqldump -h "$UCFP_DB_HOST" \
          -u "$UCFP_DB_USER" \
          -p"$UCFP_DB_PASSWORD" \
          --no-tablespaces \
          --single-transaction \
          --quick \
          --skip-lock-tables \
          "$UCFP_DB_NAME" \
    | gzip > "$DUMPFILE"

# Upload to S3
aws s3 cp "$DUMPFILE" "s3://${S3_BUCKET}/${S3_PREFIX}/${FILENAME}"

# Cleanup
rm "$DUMPFILE"
