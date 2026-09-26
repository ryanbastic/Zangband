/*
 * JavaScript side of the browser port (see src/main-web.c).
 *
 * Included into zangband.js with --pre-js.  Provides the "Zangband"
 * object that the C code calls to draw, and to fetch keypresses.
 */

/*
 * The build's version, set by index.html (see web/build.sh).  Tiles and
 * sounds are fetched with it too, like zangband.wasm and zangband.data.
 */
var ZANGBAND_VERSION = (typeof Module !== 'undefined' && Module.zangbandVersion &&
	Module.zangbandVersion.charAt(0) !== '@') ? Module.zangbandVersion : '';

function zangbandUrl(path) {
	return ZANGBAND_VERSION ? path + '?v=' + ZANGBAND_VERSION : path;
}

var Zangband = (function () {
	'use strict';

	var COLS = 80, ROWS = 24;

	var canvas = null, ctx = null;
	var cellW = 10, cellH = 18, baseline = 14, dpr = 1;
	var font = '';
	var FONT_FAMILY = '"DejaVu Sans Mono", "Menlo", "Consolas", "Liberation Mono", monospace';

	/* Shadow copy of the screen, so we can redraw on resize */
	var chars = new Uint8Array(COLS * ROWS).fill(32);
	var attrs = new Uint8Array(COLS * ROWS);
	var tiled = new Uint8Array(COLS * ROWS);	/* drawn as a tile? */
	var tattrs = new Uint8Array(COLS * ROWS);	/* terrain under the tile */
	var tchars = new Uint8Array(COLS * ROWS);
	var bigx = new Int16Array(COLS * ROWS).fill(-1);	/* see cellX() */

	/*
	 * Tilesets, by the game's GRAPHICS_* number.  The sheets are the
	 * game's lib/xtra/graf BMPs, converted to PNG with real transparency
	 * by web/build.sh.
	 */
	var TILESETS = [
		{ mode: 0, name: 'Text (no tiles)' },
		{ mode: 2, name: "Adam Bolt's tiles (16x16)", file: '16x16.png', w: 16, h: 16 },
		{ mode: 3, name: "David Gervais' tiles (32x32)", file: '32x32.png', w: 32, h: 32 },
		{ mode: 6, name: "Nomad's tiles (16x16)", file: 'nomad.png', w: 16, h: 16 },
		{ mode: 7, name: 'Neon tiles (16x16)', file: 'neon.png', w: 16, h: 16 },
		{ mode: 1, name: 'Original tiles (8x8)', file: '8x8.png', w: 8, h: 8 }
	];
	var STORE_KEY = 'zangband-tileset';

	var graphics = 0;	/* what the game is drawing with */
	var wanted = 0;		/* what the menu asks for */
	var tileset = null, sheet = null;

	try { wanted = parseInt(localStorage.getItem(STORE_KEY), 10) || 0; }
	catch (e) { wanted = 0; }
	if (!findTileset(wanted)) wanted = 0;

	function findTileset(mode) {
		for (var i = 0; i < TILESETS.length; i++)
			if (TILESETS[i].mode === mode) return TILESETS[i];
		return null;
	}

	/* Start fetching a sheet; the screen is redrawn once it arrives */
	var sheets = {};
	function loadSheet(ts) {
		if (!ts || !ts.file) return null;
		if (!sheets[ts.file]) {
			var img = new Image();
			img.onload = function () { if (tileset === ts) redrawAll(); };
			img.onerror = function () {
				if (typeof Zangband !== 'undefined')
					Zangband.plog('Could not load the tiles (' + ts.file + ')');
			};
			img.src = zangbandUrl('tiles/' + ts.file);
			sheets[ts.file] = img;
		}
		return sheets[ts.file];
	}
	if (typeof Image !== 'undefined') loadSheet(findTileset(wanted));

	var palette = [];
	for (var i = 0; i < 16; i++) palette.push('#fff');

	var curX = 0, curY = 0, curVisible = false;

	var keys = [];
	var ended = false;

	/* Map a byte to a displayable character (the game uses Latin-1) */
	var glyph = [];
	for (var b = 0; b < 256; b++) glyph.push(String.fromCharCode(b < 32 ? 32 : b));

	/*
	 * In "bigtile" rows (graphics mode), columns from bx on are two cells
	 * wide, so that map squares come out square.  bx is -1 elsewhere.
	 */
	function cellX(x, bx) {
		return (bx >= 0 && x > bx) ? (bx + 2 * (x - bx)) * cellW : x * cellW;
	}
	function cellWidth(x, bx) {
		return (bx >= 0 && x >= bx) ? 2 * cellW : cellW;
	}

	function drawTile(img, a, c, px, py, w) {
		ctx.drawImage(img, (c & 0x7f) * tileset.w, (a & 0x7f) * tileset.h,
		              tileset.w, tileset.h, px, py, w, cellH);
	}

	function drawCell(x, y) {
		var i = y * COLS + x;
		var bx = bigx[i];
		var px = cellX(x, bx), py = y * cellH, w = cellWidth(x, bx);

		if (px >= canvas.width) return;

		ctx.fillStyle = '#000';
		ctx.fillRect(px, py, w, cellH);

		if (tiled[i]) {
			if (sheet && sheet.complete && sheet.naturalWidth) {
				var ta = tattrs[i], tc = tchars[i];

				/* Terrain first, then what stands on it */
				if ((ta & 0x80) && (tc & 0x80) &&
				    (ta !== attrs[i] || tc !== chars[i]))
					drawTile(sheet, ta, tc, px, py, w);
				drawTile(sheet, attrs[i], chars[i], px, py, w);
			}
		} else if (chars[i] !== 32) {
			ctx.fillStyle = palette[attrs[i] & 15];
			ctx.fillText(glyph[chars[i]], px + (w - cellW) / 2, py + baseline, cellW);
		}

		if (curVisible && x === curX && y === curY) {
			ctx.strokeStyle = palette[11] || '#ff0';
			ctx.lineWidth = Math.max(1, Math.round(dpr));
			ctx.strokeRect(px + 0.5 * ctx.lineWidth, py + 0.5 * ctx.lineWidth,
			               w - ctx.lineWidth, cellH - ctx.lineWidth);
		}
	}

	function redrawAll() {
		if (!ctx) return;
		ctx.fillStyle = '#000';
		ctx.fillRect(0, 0, canvas.width, canvas.height);
		for (var y = 0; y < ROWS; y++)
			for (var x = 0; x < COLS; x++) drawCell(x, y);
	}

	/* Pick the largest font that fits the window */
	function layout() {
		if (!canvas) return;
		var wrap = canvas.parentElement;
		var availW = wrap.clientWidth, availH = wrap.clientHeight;
		dpr = window.devicePixelRatio || 1;

		var probe = document.createElement('canvas').getContext('2d');
		var best = 8;
		for (var size = 8; size <= 48; size++) {
			probe.font = size + 'px ' + FONT_FAMILY;
			var w = probe.measureText('M').width;
			if (w * COLS <= availW && Math.ceil(size * 1.25) * ROWS <= availH) best = size;
		}

		var size = best * dpr;
		probe.font = size + 'px ' + FONT_FAMILY;
		cellW = Math.ceil(probe.measureText('M').width);
		cellH = Math.ceil(size * 1.25);
		baseline = Math.round(size * 0.98);

		/*
		 * Tiles: two columns make a square map grid.  Use the largest
		 * even cell height that fits, and a font that fits half of it.
		 */
		if (graphics) {
			cellH = Math.floor(Math.min(2 * availW / COLS, availH / ROWS) / 2) * 2;
			cellH = Math.max(cellH, 8) * dpr;
			cellW = cellH / 2;
			size = Math.floor(Math.min(cellH / 1.25, cellW / 0.62));
			baseline = Math.round(cellH * 0.78);
		}

		font = size + 'px ' + FONT_FAMILY;

		canvas.width = cellW * COLS;
		canvas.height = cellH * ROWS;
		canvas.style.width = (canvas.width / dpr) + 'px';
		canvas.style.height = (canvas.height / dpr) + 'px';

		ctx = canvas.getContext('2d', { alpha: false });
		ctx.font = font;
		ctx.textBaseline = 'alphabetic';

		/* Keep pixel art crisp when enlarging; smooth it when shrinking */
		ctx.imageSmoothingEnabled = !!(tileset && cellH < tileset.h);
		ctx.imageSmoothingQuality = 'high';
		redrawAll();
	}

	function init() {
		if (canvas) return;
		canvas = document.getElementById('term');
		layout();
		window.addEventListener('resize', layout);
		window.addEventListener('keydown', onKey);
		initMenu();
		if (document.fonts && document.fonts.ready) document.fonts.ready.then(layout);
	}

	/* ---- Keyboard ---- */

	/* Direction keys for the original and roguelike keysets */
	var DIRS = {
		ArrowUp: 8, ArrowDown: 2, ArrowLeft: 4, ArrowRight: 6,
		Home: 7, End: 1, PageUp: 9, PageDown: 3, Clear: 5
	};
	var ROGUE_RUN = { 1: 'B', 2: 'J', 3: 'N', 4: 'H', 6: 'L', 7: 'Y', 8: 'K', 9: 'U' };

	var SPECIAL = {
		Enter: 13, Escape: 27, Backspace: 8, Tab: 9, Delete: 127
	};

	function push(s) {
		for (var i = 0; i < s.length; i++) keys.push(s.charCodeAt(i) & 0xff);
	}

	function roguelike() {
		try { return Module['_web_roguelike'] && Module['_web_roguelike'](); }
		catch (e) { return false; }
	}

	/* ---- Sound ---- */

	/*
	 * The game names an event (angband_sound_name[] in variable.c), and
	 * sounds/sound.cfg (lib/xtra/sound/sound.cfg) lists the samples for
	 * it.  Each sample is fetched the first time it is played.
	 */
	var SOUND_KEY = 'zangband-sound';
	var SOUND_MAX_PLAYING = 4;	/* more at once is only noise */
	var soundOn = true;
	var soundMap = null, soundLoading = false, soundPlaying = 0;

	try { soundOn = localStorage.getItem(SOUND_KEY) !== '0'; } catch (e) { }

	function loadSoundMap() {
		if (soundMap || soundLoading || typeof fetch === 'undefined') return;
		soundLoading = true;
		fetch(zangbandUrl('sounds/sound.cfg')).then(function (r) {
			if (!r.ok) throw new Error(r.status);
			return r.text();
		}).then(function (text) {
			var map = {};
			text.split('\n').forEach(function (line) {
				var eq = line.indexOf('=');
				if (eq < 0 || line[0] === '#' || line[0] === '[') return;
				var files = line.slice(eq + 1).trim().split(/\s+/).filter(Boolean);
				if (files.length) map[line.slice(0, eq).trim()] = files;
			});
			soundMap = map;
		}).catch(function (e) {
			console.warn('Could not load sounds/sound.cfg', e);
		}).then(function () { soundLoading = false; });
	}

	function playSound(name) {
		if (!soundOn || typeof Audio === 'undefined') return;
		if (!soundMap) { loadSoundMap(); return; }

		var files = soundMap[name];
		if (!files || soundPlaying >= SOUND_MAX_PLAYING) return;

		var audio = new Audio(zangbandUrl('sounds/' + files[Math.floor(Math.random() * files.length)]));
		audio.volume = 0.7;
		soundPlaying++;
		var done = function () {
			if (audio) { audio = null; soundPlaying--; }
		};
		audio.addEventListener('ended', done);
		audio.addEventListener('error', done);
		/* Browsers refuse to play before the first keypress; that's fine */
		var p = audio.play();
		if (p && p.catch) p.catch(done);
	}

	/* ---- Tileset menu ---- */

	function initMenu() {
		var menu = document.getElementById('tiles');
		if (!menu || menu.options.length) return;
		TILESETS.forEach(function (ts) {
			var o = document.createElement('option');
			o.value = ts.mode;
			o.textContent = ts.name;
			menu.appendChild(o);
		});
		menu.value = wanted;

		var box = document.getElementById('sound');
		if (box) {
			box.checked = soundOn;
			box.addEventListener('change', function () {
				soundOn = box.checked;
				try { localStorage.setItem(SOUND_KEY, soundOn ? '1' : '0'); } catch (e) { }
				if (soundOn) loadSoundMap();
				box.blur();
				canvas.focus();
			});
		}
		if (soundOn) loadSoundMap();
		menu.addEventListener('change', function () {
			wanted = parseInt(menu.value, 10) || 0;
			try { localStorage.setItem(STORE_KEY, wanted); } catch (e) { }
			loadSheet(findTileset(wanted));
			/* Give the keyboard back to the game */
			menu.blur();
			canvas.focus();
		});
	}

	function onKey(e) {
		if (ended) return;

		/* Let the tileset menu (or any form control) have its keys */
		var tag = e.target && e.target.tagName;
		if (tag === 'SELECT' || tag === 'INPUT' || tag === 'BUTTON') return;

		/* Leave browser/OS shortcuts alone */
		if (e.metaKey) return;
		if (/^F\d+$/.test(e.key)) return;

		var k = e.key;

		if (k in DIRS) {
			var d = DIRS[k];
			if (e.shiftKey && d !== 5) {
				/* Run */
				if (roguelike()) push(ROGUE_RUN[d]);
				else push('.' + d);
			} else {
				push(String(d));
			}
		} else if (k in SPECIAL) {
			keys.push(SPECIAL[k]);
		} else if (k.length === 1) {
			var c = k.charCodeAt(0);
			if (c > 255) return;
			if (e.ctrlKey && !e.altKey) {
				/* Let copy/paste etc. through when nothing sensible maps */
				if (/[a-z@\[\]\\^_]/i.test(k)) keys.push(k.toUpperCase().charCodeAt(0) & 0x1f);
				else return;
			} else {
				keys.push(c);
			}
		} else {
			return;
		}

		e.preventDefault();
	}

	/* ---- Persistence ---- */

	var syncing = false, syncAgain = false;

	function sync() {
		if (typeof FS === 'undefined' || !FS.syncfs) return;
		if (syncing) { syncAgain = true; return; }
		syncing = true;
		FS.syncfs(false, function (err) {
			syncing = false;
			if (err) console.error('Saving to browser storage failed', err);
			if (syncAgain) { syncAgain = false; sync(); }
		});
	}

	function showEnd(msg) {
		var o = document.getElementById('overlay');
		if (!o) return;
		var p = document.createElement('p');
		p.textContent = msg || 'The game has ended.';
		var btn = document.createElement('button');
		btn.textContent = 'Play again';
		btn.onclick = function () { location.reload(); };
		o.replaceChildren(p, btn);
		o.hidden = false;
	}

	return {
		init: init,

		/* For testing/debugging: current screen as text, and typing */
		screenText: function () {
			var lines = [];
			for (var y = 0; y < ROWS; y++)
				lines.push(String.fromCharCode.apply(null, chars.subarray(y * COLS, (y + 1) * COLS)).replace(/ +$/, ''));
			return lines.join('\n');
		},

		type: function (s) {
			push(s);
		},

		text: function (x, y, a, bytes, bx) {
			init();
			var i = y * COLS + x;
			for (var n = 0; n < bytes.length && x + n < COLS; n++) {
				chars[i + n] = bytes[n];
				attrs[i + n] = a;
				tiled[i + n] = 0;
				bigx[i + n] = bx === undefined ? -1 : bx;
				drawCell(x + n, y);
			}
		},

		pict: function (x, y, n, ap, cp, tap, tcp, bx) {
			init();
			var i = y * COLS + x;
			for (var j = 0; j < n && x + j < COLS; j++) {
				chars[i + j] = cp[j];
				attrs[i + j] = ap[j];
				tchars[i + j] = tcp[j];
				tattrs[i + j] = tap[j];
				tiled[i + j] = 1;
				bigx[i + j] = bx;
				drawCell(x + j, y);
			}
		},

		wipe: function (x, y, n, bx) {
			init();
			var i = y * COLS + x;
			for (var j = 0; j < n && x + j < COLS; j++) {
				chars[i + j] = 32;
				attrs[i + j] = 0;
				tiled[i + j] = 0;
				bigx[i + j] = bx === undefined ? -1 : bx;
				drawCell(x + j, y);
			}
		},

		clear: function () {
			init();
			chars.fill(32);
			attrs.fill(0);
			tiled.fill(0);
			bigx.fill(-1);
			redrawAll();
		},

		cursor: function (x, y, bx) {
			init();
			var ox = curX, oy = curY;
			curX = x; curY = y;
			if (ox < COLS && oy < ROWS) drawCell(ox, oy);
			if (x < COLS && y < ROWS) {
				if (bx !== undefined) bigx[y * COLS + x] = bx;
				drawCell(x, y);
			}
		},

		sound: playSound,

		/* The tileset the menu asks for (a GRAPHICS_* number) */
		graphicsRequest: function () {
			return wanted;
		},

		/* The game has switched to "mode": lay out for it and redraw */
		graphicsSet: function (mode) {
			graphics = mode;
			tileset = findTileset(mode);
			if (!tileset || !tileset.file) tileset = null;
			sheet = loadSheet(tileset);
			if (canvas) layout();
			var menu = document.getElementById('tiles');
			if (menu && parseInt(menu.value, 10) !== wanted) menu.value = wanted;
		},

		cursorVisible: function (v) {
			init();
			curVisible = !!v;
			if (curX < COLS && curY < ROWS) drawCell(curX, curY);
		},

		setColor: function (i, r, g, b) {
			palette[i] = 'rgb(' + r + ',' + g + ',' + b + ')';
			if (ctx) redrawAll();
		},

		getKey: function () {
			return keys.length ? keys.shift() : -1;
		},

		flushKeys: function () {
			keys.length = 0;
		},

		bell: function () {
			if (!canvas) return;
			canvas.classList.remove('bell');
			void canvas.offsetWidth;
			canvas.classList.add('bell');
		},

		sync: sync,

		plog: function (msg) {
			console.warn(msg);
			var t = document.getElementById('toast');
			if (!t) return;
			t.textContent = msg;
			t.hidden = false;
			clearTimeout(t._timer);
			t._timer = setTimeout(function () { t.hidden = true; }, 6000);
		},

		quit: function (msg) {
			ended = true;
			sync();
			showEnd(msg);
		}
	};
})();


var Module = typeof Module !== 'undefined' ? Module : {};

Module['preRun'] = Module['preRun'] || [];
Module['preRun'].push(function () {
	/* Load savefiles etc. from IndexedDB before the game starts */
	FS.mkdir('/persist');
	if (typeof indexedDB === 'undefined') {
		console.warn('No IndexedDB: saves will not survive a page reload');
		return;
	}
	FS.mount(IDBFS, {}, '/persist');
	addRunDependency('persist');
	FS.syncfs(true, function (err) {
		if (err) console.error('Could not load browser storage', err);
		removeRunDependency('persist');
	});
});

Module['onRuntimeInitialized'] = function () {
	Zangband.init();
	var s = document.getElementById('status');
	if (s) s.hidden = true;

	/* Save to IndexedDB regularly, and when the page is hidden */
	setInterval(Zangband.sync, 5000);
	document.addEventListener('visibilitychange', function () {
		if (document.visibilityState === 'hidden') Zangband.sync();
	});
	window.addEventListener('pagehide', Zangband.sync);
};

/* If starting fails, say so rather than leave "Downloading..." up */
Module['onAbort'] = function (what) {
	var s = document.getElementById('status');
	if (!s) return;
	s.textContent = 'Zangband failed to start (' + what + '). ' +
		'Try reloading the page.';
	s.hidden = false;
};

Module['setStatus'] = function (text) {
	var s = document.getElementById('status');
	if (s && text) s.textContent = text;
};

Module['print'] = function (t) { console.log(t); };
Module['printErr'] = function (t) { console.warn(t); };

Module['Zangband'] = Zangband;
