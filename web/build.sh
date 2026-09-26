#!/bin/sh
#
# Build the browser (WebAssembly) version of Zangband with Emscripten.
#
# Usage: web/build.sh            (from anywhere)
# Output: web/dist/  -- serve it with any static web server, e.g.
#         python3 -m http.server -d web/dist 8000
#
set -e

cd "$(dirname "$0")/.."

OUT=web/dist
OBJ=web/obj
mkdir -p "$OUT" "$OBJ/lua"

CC=${EMCC:-emcc}

# No HAVE_CONFIG_H: src/autoconf.h describes the native build machine.
CFLAGS="-O2 -DUSE_WEB -Wno-everything"

GAME="variable tables util cave object1 object2 monster1 monster2
	xtra1 xtra2 spells1 spells2 melee1 melee2 save files fields
	cmd1 cmd2 cmd3 cmd4 cmd5 cmd6 store birth load ui
	wizard1 wizard2 grid streams rooms generate dungeon init1 init2
	effects quest racial run script artifact mutation flavor spells3
	mspells1 mspells2 scores mind bldg obj_kind wild1 wild2 wild3
	avatar notes
	l-monst l-object l-player l-random l-ui l-misc l-spell l-field
	z-util z-virt z-form z-rand z-term maid-grf
	zborg1 zborg2 zborg3 zborg4 zborg5 zborg6 zborg7 zborg8 zborg9
	zbmagic1 zbmagic2 zbmagic3
	main-web"

LUA="lapi ldebug lmem lstrlib lvm tolua_lb lauxlib ldo lobject ltable
	lzio tolua_rg lbaselib lfunc lparser ltests tolua_bd tolua_tm lcode
	lgc lstate ltm tolua_eh tolua_tt ldblib llex lstring lundump tolua_gp"

OBJS=""

compile() {
	src=$1 obj=$2
	if [ ! -f "$obj" ] || [ "$src" -nt "$obj" ] || [ -n "$(find src -maxdepth 1 -name '*.h' -newer "$obj")" ]; then
		echo "CC $src"
		$CC $CFLAGS -c "$src" -o "$obj"
	fi
	OBJS="$OBJS $obj"
}

for f in $GAME; do compile "src/$f.c" "$OBJ/$f.o"; done
for f in $LUA; do compile "src/lua/$f.c" "$OBJ/lua/$f.o"; done

# Package the read-only game data.  Things the game generates or
# writes (compiled .raw data, scores, saves) are left out: the .raw
# files are rebuilt in the browser, since their layout depends on the
# machine that made them.
echo "LINK $OUT/zangband.js"
$CC $CFLAGS -o "$OUT/zangband.js" $OBJS \
	-sASYNCIFY -sASYNCIFY_STACK_SIZE=65536 \
	-sALLOW_MEMORY_GROWTH -sINITIAL_MEMORY=67108864 -sTOTAL_STACK=1048576 \
	-sFORCE_FILESYSTEM -lidbfs.js \
	-sEXPORTED_RUNTIME_METHODS=FS,UTF8ToString,addRunDependency,removeRunDependency \
	-sINVOKE_RUN=1 -sEXIT_RUNTIME=0 \
	--pre-js web/pre.js \
	--preload-file lib@/lib \
	--exclude-file '*lib/save/*' --exclude-file '*lib/apex/*' \
	--exclude-file '*.raw' --exclude-file '*makefile.zb' \
	--exclude-file '*lib/script/tk*' --exclude-file '*lib/xtra/*'


# Sound samples, and the file that says which to play for what.
mkdir -p "$OUT/sounds"
for src in lib/xtra/sound/sound.cfg lib/xtra/sound/*.mp3; do
	dst=$OUT/sounds/$(basename "$src")
	if [ ! -f "$dst" ] || [ "$src" -nt "$dst" ]; then cp "$src" "$dst"; fi
done

# Tile sheets for the menu: the game's BMPs, as PNGs with real
# transparency (the BMPs use pure black for "see through").
mkdir -p "$OUT/tiles"
for f in 8x8 16x16 32x32 nomad neon; do
	src=lib/xtra/graf/$f.bmp dst=$OUT/tiles/$f.png
	if [ ! -f "$dst" ] || [ "$src" -nt "$dst" ]; then
		echo "PNG $dst"
		python3 - "$src" "$dst" <<'PY'
import sys
import numpy as np
from PIL import Image
rgb = np.array(Image.open(sys.argv[1]).convert('RGB'))
alpha = np.where((rgb == 0).all(axis=2), 0, 255).astype(np.uint8)
Image.fromarray(np.dstack([rgb, alpha]), 'RGBA').save(sys.argv[2], optimize=True)
PY
	fi
done

# The page is never cached, and asks for everything else by this build's
# hash (see ZANGBAND_VERSION in web/pre.js), so browsers and proxies that
# cache the rest (Cloudflare keeps .js for hours) can't mix two builds.
version=$(cd "$OUT" && find . -type f ! -name index.html | sort | xargs cat | sha256sum | cut -c1-12)
sed "s|@VERSION@|$version|g" web/index.html > "$OUT/index.html"
grep -q "zangband.js?v=$version" "$OUT/index.html" || { echo "Could not version index.html" >&2; exit 1; }
echo "Version $version"

echo "Done.  Serve $OUT, e.g.: python3 -m http.server -d $OUT 8000"
