#!/bin/bash
#
# Generate the resized brand images for the Landfall app from the full-size
# GIMP exports in this directory. Edit the base images in GIMP, export the four
# PNG bases listed below, then run this script to (re)produce every derived
# size and the favicon set under src/ucfp/static/.
#
# Base images (exported from GIMP at full size, in this directory):
#   ucfp-icon.png            square app icon        (e.g. 800x800)
#   ucfp-icon-inverse.png    square inverse icon    (e.g. 800x800), for dark surfaces
#   ucfp-logo.png            wordmark lockup        (wide aspect, ~3.5:1)
#   ucfp-logo-w-tagline.png  wordmark + tagline     (wide aspect, ~3.5:1)
#
# Note on logo naming: logos are named by HEIGHT only (app-logo-h<H>.png).
# Height is the dimension that drives layout/responsiveness; width follows from
# the artwork's aspect (~3.5:1 here). `-resize x<H>` sets the exact height and
# lets width scale, so the names stay truthful and a caller picks a rung by
# height without caring about the width. Icons remain square (app-icon-NxN).
#
# Usage:
#   ./generate-images.sh        # regenerate any dest whose base is newer
#   ./generate-images.sh -n     # dry-run (show actions, change nothing)
#
set -e

SOURCE="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
DEST="$SOURCE/../../src/ucfp/static"

ICON_BASE="$SOURCE/ucfp-icon.png"
ICON_INVERSE_BASE="$SOURCE/ucfp-icon-inverse.png"
LOGO_BASE="$SOURCE/ucfp-logo.png"
LOGO_TAGLINE_BASE="$SOURCE/ucfp-logo-w-tagline.png"

DRY_RUN=false
if [[ "$1" == "-n" || "$1" == "--dry-run" ]]; then
    DRY_RUN=true
    echo "=== DRY RUN (no files will be modified) ==="
    echo
fi

# Regenerate dest when it is missing or older than its source base.
resize() {
    local src="$1" geometry="$2" dest="$3"
    if [[ ! -f "$src" ]]; then echo "  MISSING base: $src" >&2; exit 1; fi
    if [[ ! -f "$dest" || "$src" -nt "$dest" ]]; then
        echo "  resize $geometry -> ${dest##*/}"
        if [[ "$DRY_RUN" == false ]]; then
            convert -auto-orient -background none "$src" -resize "$geometry" "$dest"
        fi
    fi
}

copy() {
    local src="$1" dest="$2"
    if [[ ! -f "$dest" || "$src" -nt "$dest" ]]; then
        echo "  copy -> ${dest##*/}"
        if [[ "$DRY_RUN" == false ]]; then cp "$src" "$dest"; fi
    fi
}

# Rebuild the multi-resolution favicon.ico straight from the square icon base.
# ImageMagick's icon:auto-resize packs all listed sizes into one .ico, which is
# far easier than assembling the layers by hand in GIMP.
ico() {
    local src="$1" dest="$2"
    if [[ ! -f "$dest" || "$src" -nt "$dest" ]]; then
        echo "  ico 64,48,32,16 -> ${dest##*/}"
        if [[ "$DRY_RUN" == false ]]; then
            convert -auto-orient -background none "$src" \
                -define icon:auto-resize=64,48,32,16 "$dest"
        fi
    fi
}

echo "=== App icons (from ${ICON_BASE##*/}) ==="
for size in 512 196 180 152 128 120 96 32 16; do
    resize "$ICON_BASE" "${size}x${size}" "$DEST/img/app-icon-${size}x${size}.png"
done

echo "=== Inverse icon (from ${ICON_INVERSE_BASE##*/}) ==="
resize "$ICON_INVERSE_BASE" "196x196" "$DEST/img/app-icon-inverse-196x196.png"

echo "=== Wordmark logos (from ${LOGO_BASE##*/}) ==="
resize "$LOGO_BASE" "x300" "$DEST/img/app-logo-h300.png"
resize "$LOGO_BASE" "x200" "$DEST/img/app-logo-h200.png"
resize "$LOGO_BASE" "x64"  "$DEST/img/app-logo-h64.png"

echo "=== Wordmark + tagline (from ${LOGO_TAGLINE_BASE##*/}) ==="
resize "$LOGO_TAGLINE_BASE" "x200" "$DEST/img/app-logo-w-tagline-h200.png"

echo "=== Favicons ==="
copy "$DEST/img/app-icon-32x32.png" "$DEST/favicon.png"
ico  "$ICON_BASE"                   "$DEST/favicon.ico"

echo
echo "Done."
