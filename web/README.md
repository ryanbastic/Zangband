# Zangband in the browser

The browser port compiles the existing C sources to WebAssembly with
Emscripten. `src/main-web.c` is the front end: it draws via `web/pre.js`
onto a `<canvas>`, and it takes keypresses from the page.

## Build

    web/build.sh

This needs `emcc` (tested with Emscripten 3.1.6; set `EMCC` to use one
that is not on the PATH, e.g. `EMCC=~/emsdk/upstream/emscripten/emcc`)
and Python 3 with Pillow and NumPy. The output goes to `web/dist/`:
`index.html`, `zangband.js`, `zangband.wasm`, `zangband.data` (the
`lib/` game data), `tiles/` (the tile sheets as PNGs) and `sounds/`
(the MP3s and `sound.cfg` from `lib/xtra/sound`).

## Play

Serve `web/dist` over HTTP, because browsers won't load `.wasm` or
`.data` from `file://`:

    python3 -m http.server -d web/dist 8000

Then open http://localhost:8000/.

## Deploy

Run `web/deploy.sh` from a machine with Emscripten and SSH access to the
`fptp` host. It builds the app, uploads the four files in `web/dist`, and
configures the nginx virtual host at
https://zangband.fromprompttoproduction.com/. The first run obtains a
Let's Encrypt certificate through the host's existing Certbot webroot;
later runs reuse it. Set `DEPLOY_HOST` to use a different SSH alias.

## Notes

- **Caching:** the site is behind Cloudflare, which keeps `.js` files in
  browsers for hours whatever nginx says. So `build.sh` stamps a hash of
  the build into `index.html` (which is never cached), and every other
  file is fetched as `name?v=<hash>`. A new deploy is then picked up by
  a plain reload, and a cached file from an old build can't be paired
  with new ones. If starting fails anyway, the page says so instead of
  staying on "Downloading…".
- **Tiles:** the *Tiles* menu under the game picks text or one of the
  five tilesets from `lib/xtra/graf` (see `scripts/tiles/`). The choice
  is kept in `localStorage`. The game switches when it is next waiting
  for a command, and with tiles it uses bigtile mode, so each map
  square is two text columns wide. Sheets are fetched only when chosen.
- **Sound:** the game passes each sound event to the page, which plays
  one of the MP3s `sound.cfg` lists for it (at most four at once). Each
  MP3 is fetched the first time it plays. The *Sound* box turns it off;
  that is kept in `localStorage` too. Browsers stay silent until the
  first keypress.
- **Saves** go to the browser's IndexedDB (mounted at `/persist`). The
  page syncs them every few seconds and when it is hidden. Use
  `Ctrl-S` to save; closing the tab without saving loses progress, just
  as quitting the terminal would. On startup the game loads the most
  recently written savefile.
- **Keys:** arrows, Home/End and PgUp/PgDn move; `Shift`+arrow runs
  (this works with both keysets). Browser-reserved shortcuts such as
  `Ctrl-W`, `Ctrl-T` and `Ctrl-N` can't be captured.
- **Blocking input:** the game's input loop blocks, so the build uses
  `-sASYNCIFY`. Waiting for a key yields back to the browser.
- **Compiled data:** the `.raw` data files are rebuilt from `lib/edit`
  on each page load. Prebuilt ones from a native build have a different
  layout, so they are excluded from the package.

## Tests

- `node web/test/smoke.js ' ' '\r' ...` runs the
  game headlessly and prints the screen after each typed step.
- `web/test/browser.html` (serve `web/`, not `web/dist`) creates a
  character with real key events, saves it, reloads, and checks that the
  save loads. It uses the same IndexedDB as the game on that origin.
