#!/bin/sh
#
# release-win.sh - build zangband.exe and package it with lib/ into a zip
#
# Usage (from anywhere):
#
#   scripts/release-win.sh                              (64-bit)
#   CROSS=i686-w64-mingw32- scripts/release-win.sh      (32-bit)
#
# Output: dist/zangband-<version>-<arch>.zip
#
# Requires a MinGW-w64 cross compiler (see src/makefile.mgw) and zip.
#

set -e

TOP=$(cd "$(dirname "$0")/.." && pwd)
CROSS=${CROSS:-x86_64-w64-mingw32-}

case "$CROSS" in
	i686*) ARCH=win32 ;;
	*)     ARCH=win64 ;;
esac

# Version string, same rules as VERSION_STRING in src/defines.h
ver() { sed -n "s/^#define $1 //p" "$TOP/src/defines.h" | tr -d '"'; }
VERSION="$(ver VER_MAJOR).$(ver VER_MINOR).$(ver VER_PATCH)"
[ "$(ver VER_EXTRA)" != 0 ] && VERSION="${VERSION}pre$(ver VER_EXTRA)"
VERSION="${VERSION}$(ver VER_AFTER)"

NAME="zangband-$VERSION-$ARCH"

# Rebuild from scratch so a previous build for the other arch isn't reused
make -C "$TOP/src" -f makefile.mgw CROSS="$CROSS" clean
make -C "$TOP/src" -f makefile.mgw CROSS="$CROSS" -j"$(nproc)"

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
mkdir "$STAGE/$NAME"

cp "$TOP/src/zangband.exe" "$STAGE/$NAME/"
cp "$TOP/readme" "$STAGE/$NAME/readme.txt"
cp "$TOP/z_faq.txt" "$TOP/z_update.txt" "$STAGE/$NAME/"

# Copy lib/, leaving out build files, local player data, and compiled
# *.raw caches (they are platform-specific and rebuilt from lib/edit)
(cd "$TOP" && tar cf - \
	--exclude='makefile.zb' \
	--exclude='*.raw' \
	--exclude='lib/save/*' \
	--exclude='lib/bone/*' \
	--exclude='lib/user/*' \
	--exclude='lib/script/tk' \
	lib) | (cd "$STAGE/$NAME" && tar xf -)

mkdir -p "$TOP/dist"
rm -f "$TOP/dist/$NAME.zip"
(cd "$STAGE" && zip -qr9 "$TOP/dist/$NAME.zip" "$NAME")

echo "Created dist/$NAME.zip"
