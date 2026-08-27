#!/bin/bash
#
# Droplet MySQL backup -> S3 (run from cron on the droplet).
# Sources the deployed env (UCFP_DB_*) for DB credentials and uploads a gzipped
# mysqldump. The S3 destination is app-specific and non-secret, so it is set in the
# Config block below rather than pulled from the env.

set -e

. /opt/ucfp/ucfp.sh

# Config -- app-specific, not secret.
S3_BUCKET='pomdp'
S3_PREFIX='landfall/mysql-backups'

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
