/* File: snd-unix.c */

/*
 * Copyright (c) 1997 Ben Harrison, and others
 *
 * This software may be copied and distributed for educational, research,
 * and not for profit purposes provided that this copyright and statement
 * are included in all such copies.
 */

/*
 * Sound for the Unix front ends (X11 and curses).
 *
 * The samples and "lib/xtra/sound/sound.cfg", which maps each event in
 * angband_sound_name[] to one or more of them, come from ZangbandTK.  The
 * samples are MP3s, so rather than link a decoder we hand each one to an
 * external player.  The player is the command in $ANGBAND_SOUND_PLAYER
 * (the file name is appended), or else the first of a few common ones
 * found on the PATH.
 */

#include "angband.h"

#if (defined(USE_X11) || defined(USE_GCU)) && !defined(USE_WEB)

#include <sys/types.h>
#include <sys/wait.h>
#include <fcntl.h>

/* Most samples an event may have */
#define SAMPLE_MAX	8

/* Most players running at once; more than this and a sound is skipped */
#define PLAYING_MAX	4

/* Longest player command, in words */
#define PLAYER_ARGS	16

/* Sample file names, per event */
static cptr samples[SOUND_MAX][SAMPLE_MAX];
static int num_samples[SOUND_MAX];

/* The player command, split into words */
static char *player_argv[PLAYER_ARGS + 2];
static char player_buf[1024];

/* Players still running */
static int playing = 0;


/*
 * Players to try, best first.  Each needs to play an MP3 and exit.
 */
static cptr known_players[] =
{
	"mpg123 -q",
	"ffplay -nodisp -autoexit -loglevel quiet",
	"mpv --really-quiet --no-video",
	"pw-play",
	"paplay",
	NULL
};


/*
 * Is the first word of "cmd" an executable on the PATH?
 */
static bool on_path(cptr cmd)
{
	char name[256], path[1024];
	cptr dirs = getenv("PATH");
	int len = 0;

	/* The program name */
	while (cmd[len] && (cmd[len] != ' ') && (len < 255)) len++;
	memcpy(name, cmd, len);
	name[len] = '\0';

	if (strchr(name, '/')) return (access(name, X_OK) == 0);

	while (dirs && *dirs)
	{
		cptr end = strchr(dirs, ':');
		int n = end ? (int)(end - dirs) : (int)strlen(dirs);

		if (n && (n + len + 2 < (int)sizeof(path)))
		{
			memcpy(path, dirs, n);
			path[n] = '/';
			strcpy(path + n + 1, name);

			if (access(path, X_OK) == 0) return (TRUE);
		}

		dirs = end ? end + 1 : NULL;
	}

	return (FALSE);
}


/*
 * Split the player command into words.
 */
static void set_player(cptr cmd)
{
	int n = 0;
	char *s;

	my_strcpy(player_buf, cmd, sizeof(player_buf));

	for (s = strtok(player_buf, " \t"); s && (n < PLAYER_ARGS);
		 s = strtok(NULL, " \t"))
	{
		player_argv[n++] = s;
	}

	/* The sample goes after the command */
	player_argv[n] = NULL;
	player_argv[n + 1] = NULL;
}


/*
 * Read "sound.cfg": lines of "event = sample sample ...".
 */
static int read_sound_cfg(void)
{
	char path[1024], buf[1024];
	int total = 0;
	FILE *fff;

	path_build(path, sizeof(path), ANGBAND_DIR_XTRA, "sound/sound.cfg");

	fff = my_fopen(path, "r");
	if (!fff) return (0);

	while (0 == my_fgets(fff, buf, sizeof(buf)))
	{
		char *eq = strchr(buf, '=');
		char *name = buf, *s, *end;
		int i;

		/* Skip comments, sections and blank lines */
		if (!eq || (buf[0] == '#') || (buf[0] == '[')) continue;

		/* Trim the event name */
		*eq = '\0';
		while (*name == ' ') name++;
		for (end = eq; (end > name) && (end[-1] == ' '); end--) ;
		*end = '\0';

		for (i = 1; i < SOUND_MAX; i++)
		{
			if (streq(name, angband_sound_name[i])) break;
		}
		if (i == SOUND_MAX) continue;

		for (s = strtok(eq + 1, " \t"); s && (num_samples[i] < SAMPLE_MAX);
			 s = strtok(NULL, " \t"))
		{
			char file[1024];

			path_build(file, sizeof(file), ANGBAND_DIR_XTRA,
					   format("sound/%s", s));

			/* Ignore samples that are not there */
			if (access(file, R_OK) != 0) continue;

			samples[i][num_samples[i]++] = string_make(file);
			total++;
		}
	}

	my_fclose(fff);

	return (total);
}


/*
 * Prepare to play sounds.  Returns TRUE if we can.
 */
bool init_sound_unix(void)
{
	cptr cmd = getenv("ANGBAND_SOUND_PLAYER");
	int i;

	if (cmd && *cmd)
	{
		if (!on_path(cmd))
		{
			plog_fmt("Sound player not found: %s", cmd);
			return (FALSE);
		}
	}
	else
	{
		for (i = 0; known_players[i]; i++)
		{
			if (on_path(known_players[i])) break;
		}

		if (!known_players[i])
		{
			plog("No sound player found (try mpg123 or ffplay).");
			return (FALSE);
		}

		cmd = known_players[i];
	}

	set_player(cmd);

	if (!read_sound_cfg())
	{
		plog("No sound samples found in lib/xtra/sound.");
		return (FALSE);
	}

	return (TRUE);
}


/*
 * Play a sound for event "v".
 */
void play_sound_unix(int v)
{
	int n, fd;
	pid_t pid;

	if ((v <= 0) || (v >= SOUND_MAX) || !num_samples[v]) return;

	/* Reap players that have finished */
	while (playing > 0)
	{
		pid = waitpid(-1, NULL, WNOHANG);

		if (pid > 0) playing--;

		/* No children left to wait for (or they are reaped for us) */
		else if (pid < 0) playing = 0;

		else break;
	}

	/* Too many at once is only noise */
	if (playing >= PLAYING_MAX) return;

	/* Put the sample on the end of the command */
	for (n = 0; player_argv[n]; n++) ;
	player_argv[n] = (char *)samples[v][randint0(num_samples[v])];

	pid = fork();

	if (pid == 0)
	{
		/* Keep the player quiet, and away from the game's files */
		fd = open("/dev/null", O_RDWR);
		if (fd >= 0)
		{
			(void)dup2(fd, 0);
			(void)dup2(fd, 1);
			(void)dup2(fd, 2);
		}
		for (fd = 3; fd < 256; fd++) (void)close(fd);

		(void)execvp(player_argv[0], player_argv);
		_exit(1);
	}

	player_argv[n] = NULL;

	if (pid > 0) playing++;
}

#endif /* (USE_X11 || USE_GCU) && !USE_WEB */
