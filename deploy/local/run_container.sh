#!/bin/bash

VERSION=$(cat VERSION | tr -d '[:space:]')
UCFP_HOME="${HOME}/.ucfp"
ENV_VAR_FILE="${UCFP_HOME}/env/local.env"
DATA_DIR="${UCFP_HOME}"
EXTERNAL_PORT=9666
BACKGROUND_FLAGS=""

usage() {
    echo "Usage: $0 [-env ENV_VAR_FILE] [-dir DATA_DIR] [-port EXTERNAL_PORT] [-bg]"
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -env)
            ENV_VAR_FILE="$2"
            shift 2
            ;;
        -dir)
            DATA_DIR="$2"
            shift 2
            ;;
        -port)
            EXTERNAL_PORT="$2"
            shift 2
            ;;
        -bg)
            BACKGROUND_FLAGS="-d --restart unless-stopped"
            shift 1
            ;;
        *)
            usage
            ;;
    esac
done

DATABASE_DATA_DIR="${DATA_DIR}/database"
MEDIA_DATA_DIR="${DATA_DIR}/media"

if [[ ! -f "$ENV_VAR_FILE" ]]; then
    echo "Error: Environment file '$ENV_VAR_FILE' does not exist."
    echo "Create it first: 'make env-build'"
    exit 1
fi

if [[ -d "$DATABASE_DATA_DIR" ]]; then
    if [[ ! -w "$DATABASE_DATA_DIR" ]]; then
        echo "Error: Directory '$DATABASE_DATA_DIR' exists but is not writable."
        exit 1
    fi
else
    echo "Creating directory '$DATABASE_DATA_DIR'..."
    mkdir -p "$DATABASE_DATA_DIR"
    chmod -R 775 "$DATABASE_DATA_DIR"
fi

if [[ -d "$MEDIA_DATA_DIR" ]]; then
    if [[ ! -w "$MEDIA_DATA_DIR" ]]; then
        echo "Error: Directory '$MEDIA_DATA_DIR' exists but is not writable."
        exit 1
    fi
else
    echo "Creating directory '$MEDIA_DATA_DIR'..."
    mkdir -p "$MEDIA_DATA_DIR"
    chmod -R 775 "$MEDIA_DATA_DIR"
fi

if ! docker image inspect "ucfp:${VERSION}" > /dev/null 2>&1; then
    echo "Error: Docker image 'ucfp' does not exist. Please build it first: 'make docker-build'"
    exit 1
fi

docker rm ucfp 2>/dev/null || true

docker run $BACKGROUND_FLAGS \
       --name ucfp \
       --env-file "$ENV_VAR_FILE" \
       -v "$DATABASE_DATA_DIR:/data/database" \
       -v "$MEDIA_DATA_DIR:/data/media" \
       -p "$EXTERNAL_PORT:8000" ucfp
