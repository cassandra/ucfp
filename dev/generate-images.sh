#!/bin/bash
#
# Generate the served branding images from a small set of high-resolution base
# images.
#
# The design/base assets are NOT kept in this repository -- only the scaled,
# served copies are. This script lives in dev/ because it encodes where those
# served copies go; you keep the base images in a separate design directory.
#
# Workflow:
#   1. Edit the base images (GIMP, etc.) at high resolution and export them as
#      the PNGs listed under "base images" below.
#   2. cd into the directory that holds those base images.
#   3. Run this script by its full path; it scales each base to every size the
#      repository serves and writes them into the repo in place.
#
# Usage (run from the directory containing the base images):
#   /path/to/repo/dev/generate-images.sh        # generate (skips up-to-date files)
#   /path/to/repo/dev/generate-images.sh -n      # dry run (show what would happen)
#
# Note: the brand color also lives outside these rasters (CSS palette,
# manifest.json theme color, antinode-loading.svg, email template). Those are
# separate manual edits -- see the "Brand color outside CSS" row of README.md.
#
set -e

command -v convert >/dev/null 2>&1 || {
    echo "ERROR: ImageMagick 'convert' not found on PATH."; exit 1; }

# --- Locate the repo (this script lives in <repo>/dev/) and the source dir ----
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
SOURCE="$PWD"                       # base images are read from the current dir

STATIC="$REPO_ROOT/src/ucfp/static"
IMG="$STATIC/img"
DOCS="$REPO_ROOT/docs/assets"

# --- Base images you maintain (high-res masters; kept outside this repo) ------
# Square icons want a square master; logos want the listed wide aspect ratio so
# the scaled output lands on the exact pixel sizes (no distortion).
ICON_BASE="$SOURCE/ucfp-icon.png"                   # square, >= 512px   (e.g. 1024x1024)
ICON_INVERSE_BASE="$SOURCE/ucfp-icon-inverse.png"   # square, >= 196px   (light-on-dark)
LOGO_BASE="$SOURCE/ucfp-logo.png"                   # wide, ~2.33:1      (e.g. 1400x600)
LOGO_TAGLINE_BASE="$SOURCE/ucfp-logo-w-tagline.png" # wide, ~2.05:1      (e.g. 900x438)

# --- Args ---------------------------------------------------------------------
DRY_RUN=false
if [[ "$1" == "-n" || "$1" == "--dry-run" ]]; then
    DRY_RUN=true
    echo "=== DRY RUN (no files will be written) ==="
    echo
fi

# --- Validate the base images are present in the current directory ------------
missing=0
for base in "$ICON_BASE" "$ICON_INVERSE_BASE" "$LOGO_BASE" "$LOGO_TAGLINE_BASE"; do
    if [[ ! -f "$base" ]]; then
        echo "MISSING base image: $(basename "$base")"
        missing=1
    fi
done
if [[ "$missing" == 1 ]]; then
    echo
    echo "Looked in: $SOURCE"
    echo "Run this script from the directory that holds the base images above."
    exit 1
fi

# Soft sanity check: warn (do not fail) if a base is smaller than its largest
# output and would have to be upscaled.
warn_min_width() {  # base min-width
    local w
    w=$(identify -format "%w" "$1" 2>/dev/null | head -1)
    if [[ -n "$w" && "$w" -lt "$2" ]]; then
        echo "  WARNING: $(basename "$1") is ${w}px wide; >= $2px recommended (will upscale)."
    fi
}
warn_min_width "$ICON_BASE" 512
warn_min_width "$ICON_INVERSE_BASE" 196
warn_min_width "$LOGO_BASE" 700
warn_min_width "$LOGO_TAGLINE_BASE" 450

# --- Helpers (only act when the source is newer than the destination) ---------
resize() {  # src WxH dest
    local src="$1" size="$2" dest="$3"
    if [[ ! -f "$dest" || "$src" -nt "$dest" ]]; then
        echo "  resize ${size} -> ${dest#"$REPO_ROOT"/}"
        if [[ "$DRY_RUN" == false ]]; then
            convert "$src" -resize "$size" -strip "$dest"
        fi
    fi
}

mkdir -p "$IMG" "$DOCS"

# --- App icons (square) -------------------------------------------------------
echo "App icons (from $(basename "$ICON_BASE")):"
for size in 16 32 96 120 128 152 180 196 512; do
    resize "$ICON_BASE" "${size}x${size}" "$IMG/app-icon-${size}x${size}.png"
done

# --- Inverse icon (light-on-dark; used in modal headers) ----------------------
echo "Inverse icon (from $(basename "$ICON_INVERSE_BASE")):"
resize "$ICON_INVERSE_BASE" "196x196" "$IMG/app-icon-inverse-196x196.png"

# --- Logos (wide) -------------------------------------------------------------
echo "Logos (from $(basename "$LOGO_BASE")):"
resize "$LOGO_BASE" "467x200" "$IMG/app-logo-467x200.png"   # landing page
resize "$LOGO_BASE" "149x64"  "$IMG/app-logo-149x64.png"    # email template
resize "$LOGO_BASE" "700x300" "$IMG/app-logo-700x300.png"   # currently unreferenced; kept for parity

# --- Logo with tagline (wide) -------------------------------------------------
echo "Logo with tagline (from $(basename "$LOGO_TAGLINE_BASE")):"
resize "$LOGO_TAGLINE_BASE" "450x219" "$IMG/app-logo-w-tagline-450x219.png"  # interstitial page
resize "$LOGO_TAGLINE_BASE" "197x96"  "$DOCS/logo.png"                       # README/doc badge

# --- Favicons -----------------------------------------------------------------
echo "Favicons (from $(basename "$ICON_BASE")):"
resize "$ICON_BASE" "32x32" "$STATIC/favicon.png"
if [[ ! -f "$STATIC/favicon.ico" || "$ICON_BASE" -nt "$STATIC/favicon.ico" ]]; then
    echo "  ico    -> ${STATIC#"$REPO_ROOT"/}/favicon.ico"
    if [[ "$DRY_RUN" == false ]]; then
        convert "$ICON_BASE" -define icon:auto-resize=16,32,48,64,128 "$STATIC/favicon.ico"
    fi
fi

echo
echo "Done."
