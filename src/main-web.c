/* File: main-web.c */

/* Purpose: Browser (Emscripten / WebAssembly) visual module */

/*
 * This port has its own "main()" and is linked without "main.c".
 *
 * Drawing is done by the JavaScript side (see web/zangband.js) into a
 * canvas.  Keypresses are queued by JavaScript and pulled from here.
 *
 * The game's main loop blocks waiting for keys, which a browser cannot
 * do, so the build uses ASYNCIFY: whenever we wait for input we call
 * emscripten_sleep(), which unwinds the stack back to the browser and
 * resumes it later.
 *
 * Tiles: the page offers a menu of the tilesets in lib/xtra/graf (as
 * PNGs made by web/build.sh).  Picking one sets a request that we pick
 * up while waiting for a key (see web_check_graphics()), and the tiles
 * themselves are drawn by the JavaScript side.  Graphics use "bigtile"
 * mode, so each map square is two text columns wide and roughly square.
 *
 * Sound: we pass each event's name (angband_sound_name[]) to the page,
 * which plays one of the MP3s lib/xtra/sound/sound.cfg lists for it.
 *
 * Savefiles, scores and user pref files live in "/persist", which is
 * an IndexedDB-backed filesystem that the JavaScript side mounts and
 * loads before main() runs, and syncs back periodically.
 */

#include "angband.h"

#ifdef USE_WEB

#include <emscripten.h>
#include "maid-grf.h"
#include <dirent.h>
#include <sys/stat.h>


/* Size of the main window */
#define WEB_COLS	80
#define WEB_ROWS	24

/* Where the writable directories live */
#define WEB_PERSIST	"/persist"


typedef struct term_data term_data;

struct term_data
{
	term t;
};

static term_data data;

/* Time of the last yield to the browser (ms) */
static double last_yield;


/*
 * Interface to the JavaScript side (web/zangband.js)
 */
/*
 * "bx" is the first column of the bigtile region on that row, from which
 * each column is two cells wide, or -1 if the row has none.
 */
EM_JS(void, js_text, (int x, int y, int n, int a, const char *s, int bx),
{
	Zangband.text(x, y, a, HEAPU8.subarray(s, s + n), bx);
});

EM_JS(void, js_wipe, (int x, int y, int n, int bx),
{
	Zangband.wipe(x, y, n, bx);
});

EM_JS(void, js_curs, (int x, int y, int bx),
{
	Zangband.cursor(x, y, bx);
});

EM_JS(void, js_pict, (int x, int y, int n, const byte *ap, const char *cp,
                      const byte *tap, const char *tcp, int bx),
{
	Zangband.pict(x, y, n, HEAPU8.subarray(ap, ap + n),
	              HEAPU8.subarray(cp, cp + n), HEAPU8.subarray(tap, tap + n),
	              HEAPU8.subarray(tcp, tcp + n), bx);
});

EM_JS(void, js_sound, (const char *name),
{
	Zangband.sound(UTF8ToString(name));
});

EM_JS(int, js_graphics_request, (void),
{
	return Zangband.graphicsRequest();
});

EM_JS(void, js_graphics_set, (int mode),
{
	Zangband.graphicsSet(mode);
});

EM_JS(void, js_cursor_visible, (int v),
{
	Zangband.cursorVisible(v);
});

EM_JS(void, js_set_color, (int i, int r, int g, int b),
{
	Zangband.setColor(i, r, g, b);
});

EM_JS(int, js_getkey, (void),
{
	return Zangband.getKey();
});

EM_JS(void, js_flush_keys, (void),
{
	Zangband.flushKeys();
});

EM_JS(void, js_bell, (void),
{
	Zangband.bell();
});

EM_JS(void, js_sync, (void),
{
	Zangband.sync();
});

EM_JS(void, js_quit, (const char *s),
{
	Zangband.quit(s ? UTF8ToString(s) : "");
});

EM_JS(void, js_plog, (const char *s),
{
	Zangband.plog(UTF8ToString(s));
});


/*
 * Give the browser a chance to run if we have been busy for a while.
 *
 * Without this, things like resting or running (which poll for keys
 * without waiting) would freeze the page.
 */
static void web_maybe_yield(void)
{
	double now = emscripten_get_now();

	if (now - last_yield > 40.0)
	{
		emscripten_sleep(0);
		last_yield = emscripten_get_now();
	}
}


/*
 * Let the JavaScript side know which keyset is in use (for running)
 */
EMSCRIPTEN_KEEPALIVE int web_roguelike(void)
{
	return (rogue_like_commands ? 1 : 0);
}


/*
 * Send the current palette to JavaScript
 */
static void web_react(void)
{
	int i;

	for (i = 0; i < 16; i++)
	{
		js_set_color(i, angband_color_table[i][1],
		             angband_color_table[i][2], angband_color_table[i][3]);
	}
}


/*
 * First bigtile column on row "y", or -1
 */
static int web_bigx(int y)
{
	if (use_bigtile && (y >= Term->scr->big_y1) && (y <= Term->scr->big_y2))
	{
		return (Term->scr->big_x1);
	}

	return (-1);
}


/*
 * Switch the game to tileset "mode" (a GRAPHICS_* value; 0 is text).
 */
static void web_set_graphics(int mode)
{
	use_graphics = mode;
	use_transparency = (mode != GRAPHICS_NONE);

	/* Tell the page first, so it lays the canvas out for the new mode */
	js_graphics_set(mode);

	/* Tiles want square map grids */
	if (use_bigtile != (mode != GRAPHICS_NONE))
	{
		if (character_dungeon) toggle_bigtile();
		else use_bigtile = !use_bigtile;
	}
}


/*
 * Act on a tileset picked from the page's menu.
 *
 * Before the game has started there is nothing on screen to change, and
 * play_game() loads the visuals itself.  Once it has, we wait until the
 * game is at the command prompt, where redrawing everything cannot
 * disturb a menu or a prompt.
 */
static void web_check_graphics(void)
{
	int mode = js_graphics_request();

	if ((mode < 0) || (mode == use_graphics)) return;

	if (!character_dungeon)
	{
		web_set_graphics(mode);
		return;
	}

	if (!p_ptr->cmd.inkey_flag || character_icky) return;

	web_set_graphics(mode);

	/* Pick up the new attr/char mappings, and draw with them */
	reset_visuals();
	do_cmd_redraw();

	/* Put the cursor back on the player, as after a resize */
	move_cursor_relative(p_ptr->px, p_ptr->py);
	Term_fresh();
}


/*
 * Process events, with optional wait
 */
static errr Term_xtra_web_event(int v)
{
	int k;

	while (TRUE)
	{
		web_check_graphics();

		k = js_getkey();

		if (k >= 0)
		{
			Term_keypress(k);
			return (0);
		}

		if (!v)
		{
			web_maybe_yield();
			return (1);
		}

		/* Wait for the browser to deliver a key */
		emscripten_sleep(16);
		last_yield = emscripten_get_now();
	}
}


static errr Term_xtra_web(int n, int v)
{
	switch (n)
	{
		case TERM_XTRA_NOISE:
			js_bell();
			return (0);

		case TERM_XTRA_FRESH:
			/* Drawing is immediate; let the page repaint if busy */
			web_maybe_yield();
			return (0);

		case TERM_XTRA_SHAPE:
			js_cursor_visible(v);
			return (0);

		case TERM_XTRA_EVENT:
			return (Term_xtra_web_event(v));

		case TERM_XTRA_FLUSH:
			js_flush_keys();
			return (0);

		case TERM_XTRA_DELAY:
			if (v > 0) emscripten_sleep(v);
			last_yield = emscripten_get_now();
			return (0);

		case TERM_XTRA_REACT:
			web_react();
			return (0);

		case TERM_XTRA_SOUND:
			if ((v > 0) && (v < SOUND_MAX)) js_sound(angband_sound_name[v]);
			return (0);
	}

	return (1);
}


static errr Term_curs_web(int x, int y)
{
	js_curs(x, y, web_bigx(y));
	return (0);
}


static errr Term_wipe_web(int x, int y, int n)
{
	js_wipe(x, y, n, web_bigx(y));
	return (0);
}


static errr Term_text_web(int x, int y, int n, byte a, cptr s)
{
	js_text(x, y, n, a, s, web_bigx(y));
	return (0);
}


static errr Term_pict_web(int x, int y, int n, const byte *ap, const char *cp,
                          const byte *tap, const char *tcp)
{
	js_pict(x, y, n, ap, cp, tap, tcp, web_bigx(y));
	return (0);
}


static void term_data_link(term_data *td)
{
	term *t = &td->t;

	term_init(t, WEB_COLS, WEB_ROWS, 256);

	t->attr_blank = TERM_DARK;
	t->char_blank = ' ';

	t->text_hook = Term_text_web;
	t->wipe_hook = Term_wipe_web;
	t->curs_hook = Term_curs_web;
	t->xtra_hook = Term_xtra_web;
	t->pict_hook = Term_pict_web;

	/* Draw attr/char pairs with the high bits set as tiles */
	t->higher_pict = TRUE;

	t->data = td;

	Term_activate(t);
}


static void hook_plog(cptr str)
{
	if (str) js_plog(str);
}


static void hook_quit(cptr str)
{
	/* Make sure anything that was saved reaches IndexedDB */
	js_sync();

	js_quit(str);
}


/*
 * Replace one of the ANGBAND_DIR_* paths with a writable one,
 * creating the directory if needed.
 */
static void web_set_dir(cptr *dir, cptr sub)
{
	char buf[1024];

	strnfmt(buf, sizeof(buf), "%s/%s", WEB_PERSIST, sub);
	mkdir(buf, 0777);

	string_free(*dir);
	*dir = string_make(buf);
}


/*
 * Pick the most recently written savefile, if there is one.
 *
 * If there is none, "savefile" is left empty and the game will name
 * one after the character once it has been created.
 */
static void web_find_savefile(void)
{
	DIR *d;
	struct dirent *de;
	struct stat st;
	char buf[1024];
	time_t best = 0;

	savefile[0] = '\0';

	d = opendir(ANGBAND_DIR_SAVE);
	if (!d) return;

	while ((de = readdir(d)) != NULL)
	{
		if (de->d_name[0] == '.') continue;

		path_make(buf, ANGBAND_DIR_SAVE, de->d_name);

		if (stat(buf, &st) != 0) continue;
		if (!S_ISREG(st.st_mode)) continue;

		if (!savefile[0] || st.st_mtime >= best)
		{
			best = st.st_mtime;
			strcpy(savefile, buf);
		}
	}

	closedir(d);
}


int main(void)
{
	bool new_game = FALSE;

	plog_aux = hook_plog;
	quit_aux = hook_quit;
	core_aux = hook_quit;

	/* Game data is packaged read-only at "/lib" */
	init_file_paths("/lib/");

	/* Things the game writes go to persistent storage */
	web_set_dir(&ANGBAND_DIR_SAVE, "save");
	web_set_dir(&ANGBAND_DIR_APEX, "apex");
	web_set_dir(&ANGBAND_DIR_USER, "user");
	web_set_dir(&ANGBAND_DIR_BONE, "bone");

	/* The compiled ".raw" data files are rebuilt here on every load */
	mkdir(ANGBAND_DIR_DATA, 0777);

	web_find_savefile();

	/* Prepare the window */
	term_data_link(&data);
	angband_term[0] = &data.t;

	ANGBAND_SYS = "web";

	/* The page has a switch to turn sound off */
	use_sound = TRUE;

	/* The tileset remembered by the page, if any */
	web_check_graphics();

	web_react();

	last_yield = emscripten_get_now();

	/* Initialize (parses the edit files on first run) */
	init_angband();

	/* Wait for response */
	pause_line(23);

	/* Play the game */
	play_game(new_game);

	/* Free resources */
	cleanup_angband();

	quit(NULL);

	return (0);
}

#endif /* USE_WEB */
