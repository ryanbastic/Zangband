#!/usr/bin/env python3
"""
Import the ZangbandTK tilesets into this Zangband tree.

ZangbandTK (an Angband 4.2 derivative) keys its tile pref files by *name*
("monster:cave spider:0x9A:0x81") and ships RGBA PNG sheets.  This Zangband
(2.7.x) keys its pref files by *index* ("R:12:0x9A/0x81"), loads Windows BMP
sheets, and makes some layout assumptions of its own:

  * a feature or field drawn with lighting (FF_USE_TRANS / FIELD_INFO_TRANS)
    uses three tiles in a row: lit at c, dark at c+1, torch-lit at c+2;
  * a corpse or skeleton field uses seven tiles in a row (size 0..6);
  * spell graphics come from the "S:" table (0x30.. five shapes x 16 colours);
  * flavoured objects come from the "S:" table (0x80.. eight kinds x 16
    colours, indexed by the flavour's base colour).

For every TK set this script writes lib/xtra/graf/<sheet>.bmp and
lib/pref/<graf>.prf.  The sheet is the TK sheet itself, with extra rows
appended for any tile sequence that TK does not already lay out the way
Zangband needs it, and for any art TK has no counterpart for.

Resolution order for each thing Zangband needs a picture of:
  1. a TK name that means the same thing (monster/object/terrain/trap name);
  2. the original Zangband Adam Bolt tile for it (scripts/tiles/legacy),
     matched by picture against the TK Adam Bolt sheet, and from there by
     name into the target set;
  3. the original Zangband tile itself, rescaled to the target tile size.

Usage: scripts/tiles/import-tk-tiles.py [path/to/ZangbandTK/lib]
"""

import os
import re
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ZB = os.path.normpath(os.path.join(HERE, '..', '..'))
LEGACY = os.path.join(HERE, 'legacy')
TK = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else \
    os.path.normpath(os.path.join(ZB, '..', 'ZangbandTK-3.121.0', 'lib'))

# (graf name used by $GRAF, TK dir, TK sheet, TK main prf, tile w, h,
#  output sheet, output prf, legacy sheet, legacy prf, description)
SETS = [
    ('old', 'old', '8x8.png', 'graf-xxx.prf', 8, 8,
     '8x8.bmp', 'graf-xxx.prf', '8x8.bmp', 'graf-xxx.prf',
     'the original 8x8 tiles'),
    ('new', 'adam-bolt', '16x16.png', 'graf-new.prf', 16, 16,
     '16x16.bmp', 'graf-new.prf', '16x16.bmp', 'graf-new.prf',
     "Adam Bolt's 16x16 tiles"),
    ('david', 'gervais', '32x32.png', 'graf-dvg.prf', 32, 32,
     '32x32.bmp', 'graf-dvg.prf', '16x16.bmp', 'graf-new.prf',
     "David Gervais' 32x32 tiles"),
    ('nomad', 'nomad', '8x16.png', 'graf-nmd.prf', 16, 16,
     'nomad.bmp', 'graf-nmd.prf', '16x16.bmp', 'graf-new.prf',
     "Nomad's 16x16 tiles"),
    ('neon', 'neon', '16x16.png', 'graf-neo.prf', 16, 16,
     'neon.bmp', 'graf-neo.prf', '16x16.bmp', 'graf-new.prf',
     'the Neon 16x16 tiles'),
]

# Zangband tval -> TK tval name
TVAL_NAMES = {
    7: 'chest', 16: 'shot', 17: 'arrow', 18: 'bolt', 19: 'bow',
    20: 'digger', 21: 'hafted', 22: 'polearm', 23: 'sword', 30: 'boots',
    31: 'gloves', 32: 'helm', 33: 'crown', 34: 'shield', 35: 'cloak',
    36: 'soft armor', 37: 'hard armor', 38: 'dragon armor', 39: 'light',
    40: 'amulet', 45: 'ring', 55: 'staff', 65: 'wand', 66: 'rod',
    70: 'scroll', 75: 'potion', 77: 'flask', 80: 'food', 100: 'gold',
}

# Flavoured kinds: S: slot base -> TK flavour kind
FLAVOUR_SLOTS = [
    (0x80, 'amulet'), (0x90, 'ring'), (0xA0, 'staff'), (0xB0, 'wand'),
    (0xC0, 'rod'), (0xD0, 'scroll'), (0xE0, 'potion'), (0xF0, 'mushroom'),
]

# Zangband's sixteen colours, in order, as TK spells them
COLOURS = ['dark', 'white', 'slate', 'orange', 'red', 'green', 'blue',
           'umber', 'light dark', 'light slate', 'violet', 'yellow',
           'light red', 'light green', 'light blue', 'light umber']
# TK's extra colours folded onto the nearest of the sixteen
COLOUR_ALIAS = {
    'light white': 'white', 'light pink': 'light red', 'mud': 'umber',
    'light yellow': 'yellow', 'magenta-pink': 'violet',
    'light turquoise': 'light blue', 'light violet': 'violet',
    'deep light blue': 'light blue', 'light purple': 'violet',
    'purple': 'violet', 'deep blue': 'blue', 'mustard': 'yellow',
    'blue slate': 'slate', 'turquoise': 'blue', 'light grey': 'light slate',
    'grey': 'slate', 'pink': 'light red', 'brown': 'umber',
    'light brown': 'light umber',
}

# Spell colour code (spells1.c:spell_color) -> TK projection types
SPELL_GF = {
    0x00: ['FIRE'], 0x01: ['ICE', 'COLD'], 0x02: ['ELEC'], 0x03: ['POIS'],
    0x04: ['ACID', 'WATER'], 0x05: ['DISEN'], 0x06: ['LIGHT'],
    0x07: ['DARK', 'NETHER'], 0x08: ['SHARD'], 0x09: ['SOUND'],
    0x0A: ['CHAOS'], 0x0B: ['PLASMA'], 0x0C: ['NEXUS'], 0x0D: ['TIME'],
    0x0E: ['MANA'], 0x0F: ['MISSILE', '*'],
}
# bolt_pict base -> TK direction
SPELL_DIR = {0x30: 'static', 0x40: '90', 0x50: '0', 0x60: '45', 0x70: '135'}

# Zangband f_info name -> TK terrain code (anything absent keeps its
# original Zangband art)
FEAT_CODES = {
    'open floor': 'FLOOR', 'invisible trap': 'FLOOR',
    'invisible wall': 'FLOOR', 'open door': 'OPEN', 'broken door': 'BROKEN',
    'up staircase': 'LESS', 'down staircase': 'MORE', 'door': 'CLOSED',
    'sand': 'SAND', 'wet mud': 'MUD', 'dirt': 'DIRT', 'patch of grass': 'GRASS',
    'granite wall': 'GRANITE', 'pile of rubble': 'RUBBLE',
    'magma vein': 'MAGMA', 'quartz vein': 'QUARTZ',
    'magma vein with treasure': 'MAGMA_K',
    'quartz vein with treasure': 'QUARTZ_K', 'permanent wall': 'PERM',
    'deep water': 'DEEP_WATER', 'shallow water': 'WATER',
    'very deep water': 'DEEP_WATER', 'deep lava': 'LAVA', 'tree': 'TREE',
    'rock face': 'ROCK', 'road': 'ROAD', 'dungeon entrance': 'DUNGEON',
}
# Zangband feature that TK draws as a trap
FEAT_TRAPS = {'glyph of warding': 'glyph of warding'}

# Zangband t_info name -> TK trap name, or ('feat', CODE)
FIELD_NAMES = {
    'glyph of warding': 'glyph of warding', 'trap door': 'trap door',
    'pit': 'pit', 'spiked pit': 'spiked pit', 'gas trap': 'poison gas trap',
    'locked door': ('feat', 'CLOSED'), 'stuck door': ('feat', 'CLOSED'),
    'General Store': ('feat', 'STORE_GENERAL'),
    'Armoury': ('feat', 'STORE_ARMOR'),
    'Weapon Smiths': ('feat', 'STORE_WEAPON'),
    'Alchemy Shop': ('feat', 'STORE_ALCHEMY'),
    'Magic Wares': ('feat', 'STORE_MAGIC'),
    'Black Market': ('feat', 'STORE_BLACK'), 'Home': ('feat', 'HOME'),
    'Book Store': ('feat', 'STORE_BOOK'), 'Inn': ('feat', 'INN'),
    'Healer': ('feat', 'HEALER'), 'Magetower': ('feat', 'MAGETOWER'),
    'Large Magetower': ('feat', 'MAGETOWER'),
    'Magesmith (weapons)': ('feat', 'MAGESMITH'),
    'Magesmith (armor)': ('feat', 'MAGESMITH'),
    'blank': ('feat', 'FLOOR'), 'Bazaar': ('feat', 'STORE_GENERAL'),
    'Small Castle': ('feat', 'HOME'), 'Large Castle': ('feat', 'HOME'),
}
# Per-index overrides where Zangband reuses a name for different traps
FIELD_INDEX = {12: 'fire trap', 13: 'acid trap', 16: 'slow dart',
               17: 'strength loss dart'}

# Zangband class/race -> nearest TK class/race for the player tile
CLASS_MAP = {
    'Warrior': 'Warrior', 'Mage': 'Mage', 'Priest': 'Priest',
    'Rogue': 'Rogue', 'Ranger': 'Ranger', 'Paladin': 'Paladin',
    'Warrior-Mage': 'Mage', 'Chaos-Warrior': 'Blackguard',
    'Monk': 'Warrior', 'Mindcrafter': 'Priest', 'High-Mage': 'Necromancer',
}
RACE_MAP = {
    'Human': 'Human', 'Half-Elf': 'Half-Elf', 'Elf': 'Elf',
    'Hobbit': 'Hobbit', 'Gnome': 'Gnome', 'Dwarf': 'Dwarf',
    'Half-Orc': 'Half-Orc', 'Half-Troll': 'Half-Troll',
    'Amberite': 'Dunadan', 'High-Elf': 'High-Elf', 'Barbarian': 'Human',
    'Half-Ogre': 'Half-Troll', 'Half-Giant': 'Half-Troll',
    'Half-Titan': 'Dunadan', 'Cyclops': 'Half-Troll', 'Yeek': 'Kobold',
    'Klackon': 'Kobold', 'Kobold': 'Kobold', 'Nibelung': 'Dwarf',
    'Dark-Elf': 'Elf', 'Draconian': 'Half-Orc', 'Mindflayer': 'High-Elf',
    'Imp': 'Kobold', 'Golem': 'Dwarf', 'Skeleton': 'Half-Orc',
    'Zombie': 'Half-Orc', 'Vampire': 'Human', 'Spectre': 'Elf',
    'Sprite': 'Hobbit', 'Beastman': 'Half-Orc', 'Ghoul': 'Half-Orc',
}

LIGHT3 = ('lit', 'dark', 'torch')

# Approximate RGB of the sixteen colours, to find the nearest one
COLOUR_RGB = [
    (0, 0, 0), (255, 255, 255), (128, 128, 128), (255, 128, 0),
    (192, 0, 0), (0, 128, 64), (0, 0, 255), (128, 64, 0),
    (64, 64, 64), (192, 192, 192), (255, 0, 255), (255, 255, 0),
    (255, 64, 64), (0, 255, 0), (0, 255, 255), (192, 128, 64),
]


def norm(s):
    s = s.replace('&', '').replace('~', '')
    return re.sub(r'\s+', ' ', s).strip().lower()


def num(s):
    return int(s, 0)


# ---------------------------------------------------------------- Zangband


def read_edit(name):
    """Yield (index, name, {field letter: [values]}) for an edit file."""
    cur = None
    with open(os.path.join(ZB, 'lib', 'edit', name), encoding='latin-1') as f:
        for line in f:
            line = line.rstrip('\n')
            if line.startswith('N:'):
                if cur:
                    yield cur
                _, i, nm = line.split(':', 2)
                cur = (int(i), nm, {})
            elif cur and len(line) > 1 and line[1] == ':':
                cur[2].setdefault(line[0], []).append(line[2:])
    if cur:
        yield cur


def read_legacy_prf(name):
    """R/K/F/T/S lines of an original Zangband graf prf -> {(L, i): (a, c)}"""
    out = {}
    with open(os.path.join(LEGACY, name), encoding='latin-1') as f:
        for line in f:
            m = re.match(r'^([RKFTS]):(\w+)[:/](\w+)[:/](\w+)', line)
            if m:
                out[(m.group(1), num(m.group(2)))] = \
                    (num(m.group(3)), num(m.group(4)))
    return out


# ---------------------------------------------------------------- TK


def read_tk_prf(setdir, name, keys, player, cond=None):
    """Collect name-keyed tile positions from a TK prf (and its includes)."""
    path = os.path.join(setdir, name)
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.rstrip('\n')
            if not line or line[0] == '#':
                continue
            if line.startswith('%:'):
                read_tk_prf(setdir, line[2:].strip(), keys, player, cond)
                continue
            if line.startswith('?:'):
                m = re.search(r'CLASS ([\w-]+)\].*RACE ([\w-]+)\]', line)
                cond = (m.group(1), m.group(2)) if m else None
                continue
            parts = line.split(':')
            kind = parts[0]
            try:
                a, c = num(parts[-2]), num(parts[-1])
            except ValueError:
                continue
            pos = (a & 0x7F, c & 0x7F)
            if kind == 'monster':
                if parts[1] == '<player>':
                    player[cond] = pos
                elif cond is None:
                    keys[('R', norm(parts[1]))] = pos
            elif kind == 'object':
                keys[('K', parts[1], norm(':'.join(parts[2:-2])))] = pos
                keys.setdefault(('Kn', norm(':'.join(parts[2:-2]))), pos)
            elif kind == 'feat':
                keys[('F', parts[1], parts[2])] = pos
            elif kind == 'trap':
                keys[('T', norm(parts[1]), parts[2])] = pos
            elif kind == 'GF':
                for t in parts[1].split('|'):
                    keys[('GF', t.strip(), parts[2])] = pos
            elif kind == 'flavor':
                keys[('FL', int(parts[1]))] = pos


def read_tk_flavours():
    """TK flavour index -> (kind, colour index)"""
    out = {}
    for fn in ('flavor.txt', 'flavor.zangband.txt'):
        kind = None
        with open(os.path.join(TK, 'gamedata', fn), encoding='utf-8') as f:
            for line in f:
                p = line.rstrip('\n').split(':')
                if p[0] == 'kind':
                    kind = p[1]
                elif p[0] in ('flavor', 'fixed') and kind:
                    col = p[2] if p[0] == 'flavor' else p[3]
                    col = COLOUR_ALIAS.get(col.lower(), col.lower())
                    if col in COLOURS:
                        out[int(p[1])] = (kind, COLOURS.index(col))
    return out


def load_rgba(path, transparent_black=False):
    img = np.array(Image.open(path).convert('RGBA'))
    if transparent_black:
        img[(img[:, :, :3] == 0).all(axis=2), 3] = 0
    return img


def tile_of(sheet, pos, w, h):
    r, c = pos
    t = sheet[r * h:(r + 1) * h, c * w:(c + 1) * w]
    return t if t.shape[:2] == (h, w) else None


def rescale(tile, w, h):
    if tile.shape[:2] == (h, w):
        return tile
    return np.array(Image.fromarray(tile).resize((w, h), Image.NEAREST))


class Matcher:
    """Find the TK Adam Bolt tile that looks most like a legacy tile."""

    LIMIT = 24.0    # RMS colour distance; above this it is a different picture

    def __init__(self, tk_sheet):
        rgb = tk_sheet[:, :, :3].astype(np.float32).copy()
        rgb[tk_sheet[:, :, 3] == 0] = 0
        rows, cols = rgb.shape[0] // 16, rgb.shape[1] // 16
        t = rgb[:rows * 16, :cols * 16].reshape(rows, 16, cols, 16, 3)
        self.tiles = t.transpose(0, 2, 1, 3, 4).reshape(rows * cols, -1)
        self.norms = (self.tiles ** 2).sum(1)
        self.cols = cols
        self.cache = {}

    def find(self, tile):
        rgb = tile[:, :, :3].astype(np.float32).copy()
        rgb[tile[:, :, 3] == 0] = 0
        v = rgb.reshape(-1)
        if not v.any():
            return None
        key = v.tobytes()
        if key not in self.cache:
            d = self.norms + (v ** 2).sum() - 2 * self.tiles @ v
            i = int(d.argmin())
            rms = np.sqrt(max(d[i], 0) / v.size)
            # A recoloured copy of the same picture differs a little
            # everywhere; a different picture differs a lot somewhere
            diff = np.abs(self.tiles[i] - v).reshape(-1, 3).max(1)
            same = rms < self.LIMIT and (diff > 64).mean() <= 0.01
            self.cache[key] = divmod(i, self.cols) if same else None
        return self.cache[key]


# ---------------------------------------------------------------- build


def main():
    monsters = list(read_edit('r_info.txt'))
    kinds = list(read_edit('k_info.txt'))
    feats = list(read_edit('f_info.txt'))
    fields = list(read_edit('t_info.txt'))
    tk_flavours = read_tk_flavours()

    leg16 = load_rgba(os.path.join(LEGACY, '16x16.bmp'), True)
    leg16_prf = read_legacy_prf('graf-new.prf')

    # Keys in the TK Adam Bolt set, indexed by position, for step 2
    ab_keys, ab_player = {}, {}
    read_tk_prf(os.path.join(TK, 'tiles', 'adam-bolt'), 'graf-new.prf',
                ab_keys, ab_player)
    ab_by_pos = {}
    for k, pos in ab_keys.items():
        ab_by_pos.setdefault(pos, []).append(k)
    matcher = Matcher(load_rgba(os.path.join(TK, 'tiles', 'adam-bolt',
                                             '16x16.png')))

    for (graf, tkdir, tksheet, tkprf, w, h, out_bmp, out_prf,
         leg_sheet_name, leg_prf_name, desc) in SETS:
        setdir = os.path.join(TK, 'tiles', tkdir)
        sheet = load_rgba(os.path.join(setdir, tksheet))
        keys, player = {}, {}
        read_tk_prf(setdir, tkprf, keys, player)
        if leg_sheet_name == '16x16.bmp':
            leg_sheet, leg_prf, lw, lh = leg16, leg16_prf, 16, 16
        else:
            leg_sheet = load_rgba(os.path.join(LEGACY, leg_sheet_name))
            leg_prf, lw, lh = read_legacy_prf(leg_prf_name), 8, 8

        cols = sheet.shape[1] // w
        base_rows = sheet.shape[0] // h
        extra = []          # appended tiles, row-major
        placed = {}         # tuple of tile ids -> position of first tile
        stats = {'tk': 0, 'match': 0, 'legacy': 0, 'none': 0}

        def legacy_tile(leg_pos, offset=0):
            if leg_pos is None:
                return None
            r, c = leg_pos
            c = (c & 0x7F) + offset
            t = tile_of(leg_sheet, ((r & 0x7F), c), lw, lh)
            if t is None or not t[:, :, 3].any():
                return None
            return rescale(t, w, h)

        def via_match(leg_pos, offset, kinds, light):
            """Step 2: legacy art -> TK Adam Bolt -> name -> this set."""
            if leg_pos is None:
                return None
            r, c = leg_pos
            t = tile_of(leg16, (r & 0x7F, (c & 0x7F) + offset), 16, 16)
            if t is None:
                return None
            pos = matcher.find(t)
            if pos is None:
                return None
            if tkdir == 'adam-bolt':
                return pos
            # Only follow a name for the same kind of thing (and the same
            # lighting): TK reuses some pictures for unrelated things
            for k in ab_by_pos.get(pos, []):
                if k[0] in kinds and k in keys and \
                        (light is None or k[0] not in 'FT' or k[-1] == light):
                    return keys[k]
            return None

        def tk_lookup(cands):
            for k in cands:
                if k in keys:
                    return ('pos', keys[k])
                # "*" lighting: one picture for every light level.  Zangband
                # wants a dark one, so darken it rather than lose the cue.
                if k[0] in ('F', 'T') and k[:-1] + ('*',) in keys:
                    pos = keys[k[:-1] + ('*',)]
                    if k[-1] != 'dark':
                        return ('pos', pos)
                    t = tile_of(sheet, pos, w, h).copy()
                    t[:, :, :3] = (t[:, :, :3] * 0.55).astype(np.uint8)
                    return ('img', t)
            return None

        def resolve(cand_lists, leg_pos, leg16_pos, kinds, lights=None):
            """
            Resolve a sequence of tiles, each to ('pos', (r, c)) or
            ('img', array).  The whole sequence comes from one source where
            possible, so that its lighting variants match each other.
            """
            n = len(cand_lists)
            lights = lights or (None,) * n
            steps = [
                ('tk', [tk_lookup(cl) for cl in cand_lists]),
                ('match', [None] * n),
                ('legacy', [None] * n),
            ]
            for i in range(n):
                p = via_match(leg16_pos, i, kinds, lights[i])
                steps[1][1][i] = ('pos', p) if p is not None else None
                t = legacy_tile(leg_pos, i)
                steps[2][1][i] = ('img', t) if t is not None else None
            for name, seq in steps:
                if all(seq):
                    stats[name] += n
                    return seq
            for name, seq in steps:
                if seq[0]:
                    stats[name] += n
                    return [x or seq[0] for x in seq]
            stats['none'] += n
            return None

        def place(seq):
            """Place a sequence of resolved tiles so they sit in a row."""
            if seq is None:
                return None
            if all(s[0] == 'pos' for s in seq):
                r0, c0 = seq[0][1]
                if all(s[1] == (r0, c0 + i) for i, s in enumerate(seq)):
                    return (r0, c0)
            ident = tuple((s[0], s[1] if s[0] == 'pos' else s[1].tobytes())
                          for s in seq)
            if ident in placed:
                return placed[ident]
            # Keep the sequence on one row
            if len(extra) % cols + len(seq) > cols:
                extra.extend([None] * (cols - len(extra) % cols))
            first = len(extra)
            for s in seq:
                extra.append(tile_of(sheet, s[1], w, h) if s[0] == 'pos'
                             else s[1])
            pos = (base_rows + first // cols, first % cols)
            placed[ident] = pos
            return pos

        lines = []

        def emit(letter, idx, pos, comment):
            if pos is None:
                return
            lines.append('# %s' % comment)
            lines.append('%s:%d:0x%02X/0x%02X' % (letter, idx, 0x80 + pos[0],
                                                  0x80 + pos[1]))
            lines.append('')

        # --- Features
        lines.append('##### Terrain features #####\n')
        for idx, name, info in feats:
            flags = ' '.join(info.get('F', []))
            trans = 'USE_TRANS' in flags
            lights = LIGHT3 if trans else ('lit',)
            code = FEAT_CODES.get(name)
            trap = FEAT_TRAPS.get(name)
            lp = leg_prf.get(('F', idx))
            l16 = leg16_prf.get(('F', idx))
            cand_lists = []
            for light in lights:
                cands = []
                if code:
                    cands.append(('F', code, light))
                if trap:
                    cands.append(('T', trap, light))
                cand_lists.append(cands)
            seq = resolve(cand_lists, lp, l16, 'F', lights)
            emit('F', idx, place(seq), name)

        # --- Fields
        lines.append('\n##### Fields (traps, runes, doors, buildings) #####\n')
        for idx, name, info in fields:
            flags = ' '.join(info.get('I', []))
            lp = leg_prf.get(('T', idx))
            l16 = leg16_prf.get(('T', idx))
            if name in ('corpse', 'skeleton'):
                n, lights = 7, None
            elif 'TRANS' in re.split(r'[\s|]+', flags):
                n, lights = 3, LIGHT3
            else:
                n, lights = 1, ('lit',)
            target = FIELD_INDEX.get(idx, FIELD_NAMES.get(name))
            cand_lists = []
            for i in range(n):
                cands = []
                if target and lights:
                    if isinstance(target, tuple):
                        cands.append(('F', target[1], lights[i]))
                    else:
                        cands.append(('T', norm(target), lights[i]))
                cand_lists.append(cands)
            seq = resolve(cand_lists, lp, l16, 'T' if lights else '', lights)
            emit('T', idx, place(seq), name)

        # --- Objects
        lines.append('\n##### Objects #####\n')
        by_tval = {}
        for idx, name, info in kinds:
            if idx == 0:
                continue
            tval = int(info['I'][0].split(':')[0]) if 'I' in info else 0
            nm = norm(name)
            tk_tval = TVAL_NAMES.get(tval)
            cands = [('K', tk_tval, nm)] if tk_tval else []
            cands.append(('Kn', nm))
            pos = place(resolve([cands], leg_prf.get(('K', idx)),
                                leg16_prf.get(('K', idx)), ('K', 'Kn')))
            if pos is None and by_tval.get(tval):
                # Nothing drawn for it anywhere: borrow the previous kind
                # of the same type, as a sword is better shown as a sword
                pos = by_tval[tval][-1]
            if pos is not None:
                by_tval.setdefault(tval, []).append(pos)
            emit('K', idx, pos, name.replace('& ', '').replace('~', ''))

        # --- Monsters
        lines.append('\n##### Monsters #####\n')
        for idx, name, info in monsters:
            if idx == 0:
                continue
            pos = place(resolve([[('R', norm(name))]],
                                leg_prf.get(('R', idx)),
                                leg16_prf.get(('R', idx)), ('R',)))
            emit('R', idx, pos, name)

        # --- Spells and flavours ("S:" table)
        lines.append('\n##### Spell effects #####\n')
        for base, direction in SPELL_DIR.items():
            for col, types in SPELL_GF.items():
                cands = [('GF', t, direction) for t in types] + \
                        [('GF', '*', direction)]
                pos = place(resolve([cands], leg_prf.get(('S', base + col)),
                                    leg16_prf.get(('S', base + col)),
                                    ('GF',)))
                if pos:
                    lines.append('S:0x%02X:0x%02X/0x%02X' % (
                        base + col, 0x80 + pos[0], 0x80 + pos[1]))
            lines.append('')

        lines.append('\n##### Flavoured objects (by flavour colour) #####\n')
        by_kind = {}
        for fidx, (kind, col) in tk_flavours.items():
            if ('FL', fidx) in keys:
                by_kind.setdefault(kind, {}).setdefault(col, keys[('FL', fidx)])
        for base, kind in FLAVOUR_SLOTS:
            avail = by_kind.get(kind, {})
            for col in range(16):
                if col in avail:
                    stats['tk'] += 1
                    pos = avail[col]
                    lines.append('S:0x%02X:0x%02X/0x%02X' % (
                        base + col, 0x80 + pos[0], 0x80 + pos[1]))
                    continue
                pos = place(resolve([[]], leg_prf.get(('S', base + col)),
                                    leg16_prf.get(('S', base + col)),
                                    ('FL',)))
                if avail and (pos is None or pos[0] >= base_rows):
                    # TK has this kind in other colours: use the nearest,
                    # to keep the set's own art style
                    near = min(avail, key=lambda x: sum(
                        (p - q) ** 2 for p, q in zip(COLOUR_RGB[x],
                                                     COLOUR_RGB[col])))
                    pos = avail[near]
                if pos:
                    lines.append('S:0x%02X:0x%02X/0x%02X' % (
                        base + col, 0x80 + pos[0], 0x80 + pos[1]))
            lines.append('')

        # --- The player
        lines.append('\n##### The player #####\n')
        default = player.get(None) or player.get(('Warrior', 'Human'))
        if default:
            lines.append('R:0:0x%02X/0x%02X\n' % (0x80 + default[0],
                                                  0x80 + default[1]))
        for zc, tc in CLASS_MAP.items():
            for zr, tr in RACE_MAP.items():
                pos = player.get((tc, tr)) or player.get((tc, 'Human'))
                if pos and pos != default:
                    lines.append('?:[AND [EQU $CLASS %s] [EQU $RACE %s]]' %
                                 (zc, zr))
                    lines.append('R:0:0x%02X/0x%02X' % (0x80 + pos[0],
                                                        0x80 + pos[1]))
        lines.append('?:1\n')

        # --- Write the sheet
        rows = base_rows + (len(extra) + cols - 1) // cols
        if rows > 128:
            sys.exit('%s: %d rows, more than a tile attr can address'
                     % (graf, rows))
        out = np.zeros((rows * h, cols * w, 4), np.uint8)
        out[:base_rows * h] = sheet[:base_rows * h, :cols * w]
        for i, t in enumerate(extra):
            if t is not None:
                r, c = base_rows + i // cols, i % cols
                out[r * h:(r + 1) * h, c * w:(c + 1) * w] = t
        write_bmp(out, os.path.join(ZB, 'lib', 'xtra', 'graf', out_bmp))

        with open(os.path.join(ZB, 'lib', 'pref', out_prf), 'w') as f:
            f.write(HEADER % {'prf': out_prf, 'desc': desc, 'tk': tkdir,
                              'bmp': out_bmp, 'w': w, 'h': h})
            f.write('\n'.join(lines))
            f.write('\n')

        print('%-6s %-10s %4dx%-4d rows %3d (+%d)  tiles: %s' % (
            graf, out_bmp, cols * w, rows * h, rows, rows - base_rows,
            ', '.join('%s %d' % kv for kv in stats.items())))


HEADER = """\
# File: %(prf)s
#
# Attr/char mappings for %(desc)s (%(w)dx%(h)d, lib/xtra/graf/%(bmp)s).
#
# GENERATED from ZangbandTK's "%(tk)s" tileset by
# scripts/tiles/import-tk-tiles.py -- edit that script, not this file.
#
# Lit features and fields use three tiles in a row (lit, dark, torch-lit);
# corpses and skeletons use seven (one per size).

"""


def write_bmp(rgba, path):
    """
    Write a 24-bit BMP the X11 loader can use.  Transparent pixels become
    pure black, which is the colour the X11 port treats as "see through";
    opaque pixels that would otherwise be pure black are nudged off it.
    """
    rgb = rgba[:, :, :3].copy()
    opaque = rgba[:, :, 3] >= 128
    black = opaque & (rgb < 8).all(axis=2)
    rgb[black] = 8
    rgb[~opaque] = 0
    Image.fromarray(rgb, 'RGB').save(path, 'BMP')


if __name__ == '__main__':
    main()
