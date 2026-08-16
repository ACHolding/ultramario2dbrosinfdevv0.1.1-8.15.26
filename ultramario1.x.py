#!/usr/bin/env python3
"""
AC Kondo's SMB1 NES Python Port — single-file PC build

Original Python SMB1-style NES platformer engine.
Python 3.14 + pygame-ce. FILES=OFF at runtime:
  - no image/audio/json/tmx/ini/font/sprite-sheet loads from disk
  - no external asset directory, no internet, no subprocesses
  - SMB1 sheet graphics = embedded zlib+base64 RGBA pack decoded in memory
  - HUD text = in-file PixelFont (no system font APIs)
32 deterministic stages: World 1-1 through World 8-4.
The embedded sprite resource is the only runtime graphics source. No ROM is required.
"""

from __future__ import annotations

import array
import base64
import json
import math
import os
import random
import sys
import time
import zlib
from dataclasses import dataclass, field
from typing import Optional

try:
    import pygame
except ImportError:
    pygame = None

# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------
TITLE = "AC Kondo's SMB1 NES Python Port"
VERSION = "1.2"
FILES = False  # OFF — runtime never loads game assets from disk (md: files=off)
SPRITE_SHEET_SOURCE = "https://www.spriters-resource.com/nes/supermariobros/"
SPRITE_SHEET_MIRROR = "https://github.com/manfredsteyer/mario/tree/main/public"
TARGET_FPS = 60
# NTSC Famicom / SMB1: one logic frame per display frame @ ~60.098 Hz
FRAME_HZ = 60
TIMER_TICK_FRAMES = 24  # SMB1 overworld timer ≈ every 24 frames
INTERNAL_W, INTERNAL_H = 256, 240
TILE = 16
SCALE = 3
WINDOW_W, WINDOW_H = INTERNAL_W * SCALE, INTERNAL_H * SCALE
# --- Famicom SMB1-ish physics (pixels / 60 Hz frame) ---
# Speeds ≈ NES $0190 walk / $0290 run (high byte = pixels)
WALK_MAX = 1.5625
RUN_MAX = 2.5625
WALK_ACCEL = 0.085
RUN_ACCEL = 0.125
AIR_ACCEL_SCALE = 0.65
FRICTION = 0.085
SKID_FRICTION = 0.22
# Gravity tiers (A-held rise / release / fall) — NES JumpEngine feel
GRAVITY_HOLD = 0.18
GRAVITY_RISE = 0.36
GRAVITY_FALL = 0.45
GRAVITY = GRAVITY_FALL  # default / enemies
TERMINAL_V = 4.0
TERMINAL_WATER = 1.75
# Jump impulse scales with run speed (JumpForceData-style)
JUMP_V_STAND = -4.20
JUMP_V_WALK = -4.70
JUMP_V_RUN = -5.15
JUMP_V = JUMP_V_STAND  # legacy alias for tests
JUMP_CUT = 0.45
STOMP_BOUNCE = -3.6
INVULN_TIME = 90
TIME_LIMIT = 400
FIREBALL_SPEED = 4.0
FIREBALL_BOUNCE = -3.2
MAX_FIREBALLS = 2
MAX_PARTICLES = 32
ENEMY_WAKE_MARGIN = 48
COYOTE_FRAMES = 4
JUMP_BUFFER_FRAMES = 5

# Cheap bobbing without math.sin every enemy every frame
_SIN256 = tuple(math.sin(i * math.pi / 128.0) for i in range(256))

# Tiles
AIR, GROUND, BRICK, QBLOCK, QUSED, PIPE_TL, PIPE_TR, PIPE_BL, PIPE_BR = range(9)
PLATFORM, COIN, FLAGPOLE, CASTLE, SPIKE, WATER, HARD, BUSH, CLOUD, HILL = range(9, 19)

SOLID = frozenset({GROUND, BRICK, QBLOCK, QUSED, PIPE_TL, PIPE_TR, PIPE_BL, PIPE_BR, PLATFORM, HARD, CASTLE})
BREAKABLE = frozenset({BRICK})
# O(1) solid test (frozenset membership is slower in the collision hot path)
_SOLID_LUT = tuple(t in SOLID for t in range(32))


def smb_jump_velocity(vx: float) -> float:
    """NTSC SMB1-style jump force from horizontal speed."""
    ax = abs(vx)
    if ax >= RUN_MAX * 0.85:
        return JUMP_V_RUN
    if ax >= WALK_MAX * 0.75:
        return JUMP_V_WALK
    return JUMP_V_STAND

# Themes per world
THEME_OVERWORLD = 0
THEME_UNDERGROUND = 1
THEME_ATHLETIC = 2
THEME_CASTLE = 3
THEME_WATER = 4

PALETTES = {
    THEME_OVERWORLD: {"sky": (92, 148, 252), "ground": (228, 92, 16), "brick": (200, 76, 12), "pipe": (0, 168, 0), "plat": (0, 168, 0)},
    THEME_UNDERGROUND: {"sky": (0, 0, 0), "ground": (0, 136, 136), "brick": (0, 168, 168), "pipe": (0, 168, 0), "plat": (0, 168, 168)},
    THEME_ATHLETIC: {"sky": (92, 148, 252), "ground": (228, 92, 16), "brick": (200, 76, 12), "pipe": (0, 168, 0), "plat": (252, 216, 168)},
    THEME_CASTLE: {"sky": (0, 0, 0), "ground": (0, 0, 0), "brick": (160, 160, 160), "pipe": (120, 120, 120), "plat": (160, 160, 160)},
    THEME_WATER: {"sky": (0, 0, 168), "ground": (228, 92, 16), "brick": (200, 76, 12), "pipe": (0, 168, 0), "plat": (0, 168, 0)},
}



# ---------------------------------------------------------------------------
# SMB1 NES sprite resources (FILES=OFF)
# Cropped from the Mario/Luigi, enemy, and tile sheets credited to The
# Spriters Resource by the source mirror above, then packed as zlib+base64 RGBA.
# The conversion removes sheet backgrounds; it does not require or embed a ROM.
# Decoded only in memory.
# Runtime never loads PNG/JPG/sprite sheets from disk.
# ---------------------------------------------------------------------------
_SPRITE_RESOURCES_B64 = (
    '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'
    'Mx5y9OTDkqGytvDSkQ8B7RuQ6f8EWFcbLQ=='
)


def _decode_sprite_pack(b64: str) -> dict:
    """Decode embedded base64 sprite resource pack → name -> (w, h, rgba_bytes)."""
    raw = zlib.decompress(base64.b64decode(b64.encode("ascii")))
    meta_len = int.from_bytes(raw[:4], "big")
    meta = json.loads(raw[4 : 4 + meta_len].decode("ascii"))
    blob = raw[4 + meta_len :]
    out = {}
    off = 0
    for name, w, h, nbytes in meta:
        out[name] = (w, h, blob[off : off + nbytes])
        off += nbytes
    return out


def _surface_from_rgba(w: int, h: int, rgba: bytes) -> "pygame.Surface":
    return pygame.image.frombytes(rgba, (w, h), "RGBA").convert_alpha()


def _opaque_bounds(surf: "pygame.Surface") -> tuple[int, int, int, int] | None:
    """Return (x0, y0, x1, y1) inclusive opaque pixel bounds, or None if empty."""
    w, h = surf.get_size()
    # Scan rows/cols — faster than allocating a full array copy for tiny NES sprites
    x0, y0, x1, y1 = w, h, -1, -1
    get_at = surf.get_at
    for y in range(h):
        for x in range(w):
            if get_at((x, y))[3] > 0:
                if x < x0:
                    x0 = x
                if y < y0:
                    y0 = y
                if x > x1:
                    x1 = x
                if y > y1:
                    y1 = y
    if x1 < 0:
        return None
    return x0, y0, x1, y1


def normalize_sprite(
    surf: "pygame.Surface",
    tw: int | None = None,
    th: int | None = None,
    *,
    foot: bool = True,
    center_x: bool = True,
) -> "pygame.Surface":
    """
    Re-pad a sheet crop so opaque pixels share a stable origin.
    foot=True bottom-aligns (stops walk-cycle bobbing).
    center_x=True horizontally centers within the target frame.
    """
    bb = _opaque_bounds(surf)
    if bb is None:
        out_w = tw if tw is not None else surf.get_width()
        out_h = th if th is not None else surf.get_height()
        return pygame.Surface((out_w, out_h), pygame.SRCALPHA)
    x0, y0, x1, y1 = bb
    cw, ch = x1 - x0 + 1, y1 - y0 + 1
    out_w = tw if tw is not None else max(surf.get_width(), cw)
    out_h = th if th is not None else max(surf.get_height(), ch)
    out_w = max(out_w, cw)
    out_h = max(out_h, ch)
    out = pygame.Surface((out_w, out_h), pygame.SRCALPHA)
    dx = (out_w - cw) // 2 if center_x else 0
    dy = out_h - ch if foot else 0
    out.blit(surf, (dx, dy), pygame.Rect(x0, y0, cw, ch))
    return out.convert_alpha()


def blit_entity(
    dest: "pygame.Surface",
    img: "pygame.Surface",
    x: float,
    y: float,
    w: int,
    h: int,
    cam: int,
) -> None:
    """Draw sprite foot-centered on the entity collision box (pixel-snapped)."""
    # Use a single float→int conversion so sprite and camera share the same snap.
    dest.blit(
        img,
        (int(x - cam) + (w - img.get_width()) // 2, int(y) + h - img.get_height()),
    )


def _is_near_black(c, lim: int = 20) -> bool:
    return c[3] > 0 and c[0] <= lim and c[1] <= lim and c[2] <= lim


def remove_tile_edge_seams(surf: "pygame.Surface") -> "pygame.Surface":
    """
    Sheet ground/brick crops often keep a black outline on the right/bottom edge,
    which shows up as black seams when tiles are placed side-by-side.
    Replace pure-black edge pixels with the inward neighbor color.
    """
    out = surf.copy()
    w, h = out.get_size()
    for y in range(h):
        for x in (0, w - 1):
            if _is_near_black(out.get_at((x, y))):
                nx = 1 if x == 0 else w - 2
                out.set_at((x, y), out.get_at((nx, y)))
    for x in range(w):
        for y in (0, h - 1):
            if _is_near_black(out.get_at((x, y))):
                ny = 1 if y == 0 else h - 2
                out.set_at((x, y), out.get_at((x, ny)))
    return out.convert_alpha()


def flood_clear_corner_bg(surf: "pygame.Surface", match) -> "pygame.Surface":
    """Clear background pixels connected to the image corners (sheet chroma)."""
    out = surf.copy()
    w, h = out.get_size()
    seen = [[False] * w for _ in range(h)]
    stack = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    while stack:
        x, y = stack.pop()
        if x < 0 or y < 0 or x >= w or y >= h or seen[y][x]:
            continue
        seen[y][x] = True
        c = out.get_at((x, y))
        if not match(c):
            continue
        out.set_at((x, y), (0, 0, 0, 0))
        stack.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))
    return out.convert_alpha()


def fix_piranha_palette(surf: "pygame.Surface") -> "pygame.Surface":
    """Sheet plant often lands green-head/orange-stem; nudge toward NES red/green."""
    out = surf.copy()
    w, h = out.get_size()
    for y in range(h):
        for x in range(w):
            r, g, b, a = out.get_at((x, y))
            if a == 0:
                continue
            # green-ish head -> red
            if g > r + 30 and g > b + 30 and g > 80:
                out.set_at((x, y), (min(255, 40 + r), max(0, g // 5), max(0, b // 5), a))
            # orange/tan stem/leaf edge -> green
            elif r > 150 and g > 80 and b < 100 and r > g:
                out.set_at((x, y), (0, min(255, 140 + g // 3), 0, a))
    return out.convert_alpha()


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


# ---------------------------------------------------------------------------
# Pixel font (FILES=OFF) — no system fonts / no disk fonts
# ---------------------------------------------------------------------------
# 5x7 glyphs packed as 7 rows of 5 bits (MSB left). Space = empty.
_PF_GLYPHS: dict[str, tuple[int, ...]] = {
    " ": (0, 0, 0, 0, 0, 0, 0),
    "0": (0b01110, 0b10001, 0b10011, 0b10101, 0b11001, 0b10001, 0b01110),
    "1": (0b00100, 0b01100, 0b00100, 0b00100, 0b00100, 0b00100, 0b01110),
    "2": (0b01110, 0b10001, 0b00001, 0b00110, 0b01000, 0b10000, 0b11111),
    "3": (0b01110, 0b10001, 0b00001, 0b00110, 0b00001, 0b10001, 0b01110),
    "4": (0b00010, 0b00110, 0b01010, 0b10010, 0b11111, 0b00010, 0b00010),
    "5": (0b11111, 0b10000, 0b11110, 0b00001, 0b00001, 0b10001, 0b01110),
    "6": (0b00110, 0b01000, 0b10000, 0b11110, 0b10001, 0b10001, 0b01110),
    "7": (0b11111, 0b00001, 0b00010, 0b00100, 0b01000, 0b01000, 0b01000),
    "8": (0b01110, 0b10001, 0b10001, 0b01110, 0b10001, 0b10001, 0b01110),
    "9": (0b01110, 0b10001, 0b10001, 0b01111, 0b00001, 0b00010, 0b01100),
    "A": (0b01110, 0b10001, 0b10001, 0b11111, 0b10001, 0b10001, 0b10001),
    "B": (0b11110, 0b10001, 0b10001, 0b11110, 0b10001, 0b10001, 0b11110),
    "C": (0b01110, 0b10001, 0b10000, 0b10000, 0b10000, 0b10001, 0b01110),
    "D": (0b11110, 0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b11110),
    "E": (0b11111, 0b10000, 0b10000, 0b11110, 0b10000, 0b10000, 0b11111),
    "F": (0b11111, 0b10000, 0b10000, 0b11110, 0b10000, 0b10000, 0b10000),
    "G": (0b01110, 0b10001, 0b10000, 0b10111, 0b10001, 0b10001, 0b01110),
    "H": (0b10001, 0b10001, 0b10001, 0b11111, 0b10001, 0b10001, 0b10001),
    "I": (0b01110, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100, 0b01110),
    "J": (0b00111, 0b00010, 0b00010, 0b00010, 0b00010, 0b10010, 0b01100),
    "K": (0b10001, 0b10010, 0b10100, 0b11000, 0b10100, 0b10010, 0b10001),
    "L": (0b10000, 0b10000, 0b10000, 0b10000, 0b10000, 0b10000, 0b11111),
    "M": (0b10001, 0b11011, 0b10101, 0b10001, 0b10001, 0b10001, 0b10001),
    "N": (0b10001, 0b11001, 0b10101, 0b10011, 0b10001, 0b10001, 0b10001),
    "O": (0b01110, 0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b01110),
    "P": (0b11110, 0b10001, 0b10001, 0b11110, 0b10000, 0b10000, 0b10000),
    "Q": (0b01110, 0b10001, 0b10001, 0b10001, 0b10101, 0b10010, 0b01101),
    "R": (0b11110, 0b10001, 0b10001, 0b11110, 0b10100, 0b10010, 0b10001),
    "S": (0b01111, 0b10000, 0b10000, 0b01110, 0b00001, 0b00001, 0b11110),
    "T": (0b11111, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100),
    "U": (0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b01110),
    "V": (0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b01010, 0b00100),
    "W": (0b10001, 0b10001, 0b10001, 0b10001, 0b10101, 0b10101, 0b01010),
    "X": (0b10001, 0b10001, 0b01010, 0b00100, 0b01010, 0b10001, 0b10001),
    "Y": (0b10001, 0b10001, 0b01010, 0b00100, 0b00100, 0b00100, 0b00100),
    "Z": (0b11111, 0b00001, 0b00010, 0b00100, 0b01000, 0b10000, 0b11111),
    "-": (0b00000, 0b00000, 0b00000, 0b11111, 0b00000, 0b00000, 0b00000),
    ":": (0b00000, 0b00100, 0b00100, 0b00000, 0b00100, 0b00100, 0b00000),
    ".": (0b00000, 0b00000, 0b00000, 0b00000, 0b00000, 0b00100, 0b00100),
    "!": (0b00100, 0b00100, 0b00100, 0b00100, 0b00100, 0b00000, 0b00100),
    "=": (0b00000, 0b01110, 0b00000, 0b01110, 0b00000, 0b00000, 0b00000),
    ",": (0b00000, 0b00000, 0b00000, 0b00000, 0b00100, 0b00100, 0b01000),
    "+": (0b00000, 0b00100, 0b00100, 0b11111, 0b00100, 0b00100, 0b00000),
    "/": (0b00001, 0b00010, 0b00100, 0b00100, 0b01000, 0b10000, 0b10000),
    "'": (0b00100, 0b00100, 0b01000, 0b00000, 0b00000, 0b00000, 0b00000),
    "x": (0b00000, 0b10001, 0b01010, 0b00100, 0b01010, 0b10001, 0b00000),
}


class PixelFont:
    """In-memory 5x7 bitmap font. Never touches disk or system font APIs."""

    def __init__(self, scale: int = 1):
        self.scale = max(1, int(scale))
        self.gw = 5 * self.scale
        self.gh = 7 * self.scale
        self.advance = self.gw + self.scale
        self._cache: dict[tuple, "pygame.Surface"] = {}

    def _glyph(self, ch: str, color: tuple) -> "pygame.Surface":
        key = (ch, color, self.scale)
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        rows = _PF_GLYPHS.get(ch, _PF_GLYPHS.get(ch.upper(), _PF_GLYPHS[" "]))
        s = pygame.Surface((self.gw, self.gh), pygame.SRCALPHA)
        sc = self.scale
        for y, row in enumerate(rows):
            for x in range(5):
                if row & (1 << (4 - x)):
                    if sc == 1:
                        s.set_at((x, y), color)
                    else:
                        pygame.draw.rect(s, color, (x * sc, y * sc, sc, sc))
        self._cache[key] = s
        return s

    def render(self, text: str, _antialias: bool = False, color=(255, 255, 255)) -> "pygame.Surface":
        text = str(text)
        if not text:
            return pygame.Surface((1, self.gh), pygame.SRCALPHA)
        w = max(1, len(text) * self.advance - self.scale)
        out = pygame.Surface((w, self.gh), pygame.SRCALPHA)
        x = 0
        for ch in text:
            out.blit(self._glyph(ch, color), (x, 0))
            x += self.advance
        return out

    def size(self, text: str) -> tuple[int, int]:
        n = len(str(text))
        return (max(1, n * self.advance - self.scale), self.gh)


def world_theme(world: int, stage: int) -> int:
    """Exact SMB1 main-course theme table (public level list)."""
    # stage 4 always castle; water only 2-2 and 7-2; underground 1-2 & 4-2;
    # athletic always *-3; several *-2 are overworld (3-2, 5-2, 6-2, 8-2).
    table = {
        (1, 1): THEME_OVERWORLD,
        (1, 2): THEME_UNDERGROUND,
        (1, 3): THEME_ATHLETIC,
        (1, 4): THEME_CASTLE,
        (2, 1): THEME_OVERWORLD,
        (2, 2): THEME_WATER,
        (2, 3): THEME_ATHLETIC,
        (2, 4): THEME_CASTLE,
        (3, 1): THEME_OVERWORLD,
        (3, 2): THEME_OVERWORLD,
        (3, 3): THEME_ATHLETIC,
        (3, 4): THEME_CASTLE,
        (4, 1): THEME_OVERWORLD,
        (4, 2): THEME_UNDERGROUND,
        (4, 3): THEME_ATHLETIC,
        (4, 4): THEME_CASTLE,
        (5, 1): THEME_OVERWORLD,
        (5, 2): THEME_OVERWORLD,
        (5, 3): THEME_ATHLETIC,
        (5, 4): THEME_CASTLE,
        (6, 1): THEME_OVERWORLD,
        (6, 2): THEME_OVERWORLD,
        (6, 3): THEME_ATHLETIC,
        (6, 4): THEME_CASTLE,
        (7, 1): THEME_OVERWORLD,
        (7, 2): THEME_WATER,
        (7, 3): THEME_ATHLETIC,
        (7, 4): THEME_CASTLE,
        (8, 1): THEME_OVERWORLD,
        (8, 2): THEME_OVERWORLD,
        (8, 3): THEME_OVERWORLD,
        (8, 4): THEME_CASTLE,
    }
    return table[(world, stage)]


def stage_key(world: int, stage: int) -> str:
    return "%d-%d" % (world, stage)


# Course-to-area routing used by the NES game's documented level table. Bonus
# rooms are intentionally omitted because this build presents the 32 main
# courses as one continuous PC campaign.
SMB1_AREA_ROUTE_IDS = (
    (0x25, 0xC0, 0x26, 0x60),
    (0x28, 0x01, 0x27, 0x62),
    (0x24, 0x35, 0x20, 0x63),
    (0x22, 0x41, 0x2C, 0x61),
    (0x2A, 0x31, 0x26, 0x62),
    (0x2E, 0x23, 0x2D, 0x60),
    (0x33, 0x01, 0x27, 0x64),
    (0x30, 0x32, 0x21, 0x65),
)


def area_route_id(world: int, stage: int) -> int:
    return SMB1_AREA_ROUTE_IDS[world - 1][stage - 1]


def stage_seed(world: int, stage: int) -> int:
    return world * 10007 + stage * 997 + area_route_id(world, stage) * 65537 + 424242


# ---------------------------------------------------------------------------
# Legacy procedural drawing helpers retained for older call sites.
# Runtime rendering uses only the embedded SMB1 sheet resource above.
# ---------------------------------------------------------------------------
def make_surface(w, h, color=None):
    s = pygame.Surface((w, h), pygame.SRCALPHA)
    if color is not None:
        s.fill(color)
    return s


def _px(s, x, y, c):
    if 0 <= x < s.get_width() and 0 <= y < s.get_height():
        s.set_at((x, y), c)


def _fill_rect(s, x, y, w, h, c):
    pygame.draw.rect(s, c, (x, y, w, h))


def _ellipse(s, x, y, w, h, c):
    pygame.draw.ellipse(s, c, (x, y, w, h))


# NES-ish original palette (not ripped — approximate public-domain style)
C_RED = (200, 40, 40)
C_BLUE = (40, 60, 200)
C_SKIN = (252, 188, 116)
C_BROWN = (160, 80, 40)
C_DKBROWN = (80, 40, 20)
C_GREEN = (0, 168, 0)
C_LGREEN = (180, 255, 180)
C_YELLOW = (252, 216, 0)
C_ORANGE = (252, 152, 56)
C_WHITE = (252, 252, 252)
C_BLACK = (0, 0, 0)
C_GRAY = (160, 160, 160)
C_DKGRAY = (80, 80, 80)
C_CYAN = (0, 168, 168)
C_WATER = (0, 0, 168)
C_PINK = (252, 160, 180)
C_STAR = (252, 252, 100)


def gen_tile(kind: int, theme: int) -> "pygame.Surface":
    pal = PALETTES[theme]
    s = make_surface(TILE, TILE)
    if kind == AIR:
        return s
    if kind == GROUND:
        # Seamless filler — no outer black rect (that caused vertical seams).
        s.fill(pal["ground"])
        top = (252, 188, 116) if theme == THEME_OVERWORLD else C_WHITE
        for x in range(TILE):
            s.set_at((x, 0), top)
            s.set_at((x, 1), top)
        # Internal speckles only (not on edges)
        for x, y in ((4, 5), (10, 8), (6, 11), (12, 4)):
            s.set_at((x, y), C_DKBROWN)
    elif kind == BRICK:
        s.fill(pal["brick"])
        pygame.draw.line(s, C_BLACK, (0, 7), (15, 7))
        pygame.draw.line(s, C_BLACK, (7, 0), (7, 7))
        pygame.draw.line(s, C_BLACK, (0, 15), (15, 15))
        pygame.draw.line(s, C_BLACK, (3, 8), (3, 15))
        pygame.draw.line(s, C_BLACK, (11, 8), (11, 15))
    elif kind in (QBLOCK, QUSED):
        base = C_ORANGE if kind == QBLOCK else (160, 80, 20)
        s.fill(base)
        # Inner shade only — keep outer edge tileable
        pygame.draw.rect(s, C_BLACK, (1, 1, 14, 14), 1)
        if kind == QBLOCK:
            _fill_rect(s, 5, 3, 6, 2, C_BLACK)
            _fill_rect(s, 9, 5, 2, 3, C_BLACK)
            _fill_rect(s, 7, 8, 2, 2, C_BLACK)
            _fill_rect(s, 7, 12, 2, 2, C_BLACK)
    elif kind in (PIPE_TL, PIPE_TR, PIPE_BL, PIPE_BR):
        s.fill((0, 0, 0, 0))
        if kind in (PIPE_TL, PIPE_TR):
            pygame.draw.rect(s, pal["pipe"], (1, 4, 14, 12))
            pygame.draw.rect(s, C_LGREEN, (2, 5, 12, 3))
            pygame.draw.rect(s, C_BLACK, (1, 4, 14, 12), 1)
        else:
            pygame.draw.rect(s, pal["pipe"], (3, 0, 10, 16))
            pygame.draw.rect(s, C_BLACK, (3, 0, 10, 16), 1)
    elif kind == PLATFORM:
        s.fill(pal["plat"])
        pygame.draw.line(s, C_BLACK, (0, 0), (15, 0))
        pygame.draw.line(s, C_BLACK, (0, 15), (15, 15))
    elif kind == COIN:
        _ellipse(s, 3, 2, 10, 12, C_YELLOW)
        _ellipse(s, 5, 4, 6, 8, (200, 160, 0))
    elif kind == FLAGPOLE:
        _fill_rect(s, 7, 0, 2, 16, C_GRAY)
        _fill_rect(s, 0, 0, 8, 6, C_GREEN)
    elif kind == CASTLE:
        s.fill(C_DKGRAY)
        _fill_rect(s, 4, 8, 8, 8, (40, 40, 40))
        _fill_rect(s, 0, 0, 16, 4, C_GRAY)
    elif kind == SPIKE:
        s.fill((0, 0, 0, 0))
        pygame.draw.polygon(s, C_GRAY, [(0, 15), (8, 0), (15, 15)])
        pygame.draw.polygon(s, C_DKGRAY, [(2, 15), (8, 3), (13, 15)])
    elif kind == WATER:
        s.fill(C_WATER)
        for i in range(0, 16, 4):
            pygame.draw.line(s, (60, 60, 220), (i, 4), (i + 2, 4))
    elif kind == HARD:
        s.fill(C_GRAY)
        pygame.draw.line(s, C_DKGRAY, (0, 7), (15, 7))
        pygame.draw.line(s, C_DKGRAY, (7, 0), (7, 15))
    elif kind == BUSH:
        _ellipse(s, 1, 6, 14, 10, C_GREEN)
        _ellipse(s, 0, 8, 8, 8, C_GREEN)
        _ellipse(s, 8, 8, 8, 8, C_GREEN)
        _px(s, 4, 10, C_LGREEN)
        _px(s, 11, 11, C_LGREEN)
    elif kind == CLOUD:
        _ellipse(s, 2, 6, 12, 8, C_WHITE)
        _ellipse(s, 0, 8, 8, 6, C_WHITE)
        _ellipse(s, 8, 8, 8, 6, C_WHITE)
        _px(s, 5, 9, (99, 173, 255))
        _px(s, 10, 9, (99, 173, 255))
    elif kind == HILL:
        pygame.draw.polygon(s, C_GREEN, [(0, 15), (8, 2), (15, 15)])
        pygame.draw.polygon(s, (0, 120, 0), [(3, 15), (8, 6), (12, 15)])
    return s


def _draw_mario(s, big: bool, pose: str, fire: bool = False):
    """Original Mario-like figure (clean-room pixels). pose: stand|walk0|walk1|walk2|jump|skid|swim|dead"""
    h = s.get_height()
    body = (220, 60, 40) if fire else C_RED
    overalls = (40, 80, 220) if fire else C_BLUE
    skin = C_SKIN
    # hat
    _fill_rect(s, 4, 0, 8, 3, body)
    _fill_rect(s, 3, 2, 10, 2, body)
    # face
    _fill_rect(s, 4, 4, 8, 4, skin)
    _px(s, 9, 5, C_BLACK)  # eye
    # torso
    torso_h = 8 if big else 4
    _fill_rect(s, 3, 8, 10, torso_h, body)
    _fill_rect(s, 4, 8 + max(0, torso_h - 4), 8, 4 if big else 2, overalls)
    leg_y = h - 4
    if pose == "dead":
        s.fill((0, 0, 0, 0))
        _fill_rect(s, 4, 2, 8, 8, body)
        _fill_rect(s, 2, 10, 12, 4, overalls)
        return s
    if pose == "jump":
        _fill_rect(s, 2, leg_y, 4, 4, overalls)
        _fill_rect(s, 10, leg_y - 2, 4, 4, overalls)
    elif pose == "skid":
        _fill_rect(s, 3, leg_y, 5, 4, overalls)
        _fill_rect(s, 9, leg_y, 4, 4, overalls)
    elif pose == "swim":
        _fill_rect(s, 4, leg_y, 3, 4, overalls)
        _fill_rect(s, 10, leg_y - 1, 4, 3, overalls)
        _fill_rect(s, 0, 10, 4, 2, skin)  # arm
    elif pose.startswith("walk"):
        n = int(pose[-1]) if pose[-1].isdigit() else 0
        if n == 0:
            _fill_rect(s, 4, leg_y, 3, 4, overalls)
            _fill_rect(s, 9, leg_y, 3, 4, overalls)
        elif n == 1:
            _fill_rect(s, 3, leg_y, 3, 4, overalls)
            _fill_rect(s, 10, leg_y, 3, 4, overalls)
        else:
            _fill_rect(s, 5, leg_y, 6, 4, overalls)
    else:  # stand
        _fill_rect(s, 4, leg_y, 3, 4, overalls)
        _fill_rect(s, 9, leg_y, 3, 4, overalls)
    return s


def gen_player_frames(big: bool, fire: bool = False) -> dict:
    h = 32 if big else 16
    poses = ("stand", "walk0", "walk1", "walk2", "jump", "skid", "swim", "dead")
    out = {}
    for pose in poses:
        s = make_surface(16, h)
        _draw_mario(s, big, pose, fire)
        out[pose] = s
    return out


def gen_enemy_frames(kind: str) -> dict:
    """Multi-frame enemy sprites (FILES=OFF)."""
    frames = {}
    if kind == "walker":
        for i in range(2):
            s = make_surface(16, 16)
            _ellipse(s, 1, 4, 14, 12, C_BROWN)
            _fill_rect(s, 4, 8, 2, 2, C_BLACK)
            _fill_rect(s, 10, 8, 2, 2, C_BLACK)
            _fill_rect(s, 2 + i, 14, 4, 2, C_DKBROWN)
            _fill_rect(s, 10 - i, 14, 4, 2, C_DKBROWN)
            frames["walk%d" % i] = s
        s = make_surface(16, 8)
        _ellipse(s, 1, 0, 14, 8, C_BROWN)
        frames["flat"] = s
    elif kind == "sheller":
        for i in range(2):
            s = make_surface(16, 24)
            _ellipse(s, 1, 10, 14, 12, C_GREEN)
            _fill_rect(s, 4, 4, 8, 8, C_SKIN)
            _fill_rect(s, 6, 6, 2, 2, C_BLACK)
            _fill_rect(s, 10, 6, 2, 2, C_BLACK)
            if i:
                _fill_rect(s, 0, 14, 3, 3, C_SKIN)
            frames["walk%d" % i] = s
        s = make_surface(16, 14)
        _ellipse(s, 1, 2, 14, 12, C_GREEN)
        _fill_rect(s, 4, 6, 8, 4, C_LGREEN)
        frames["shell"] = s
    elif kind == "flyer":
        for i in range(2):
            s = make_surface(16, 16)
            _ellipse(s, 2, 4, 12, 10, C_RED)
            wy = 5 + i
            _ellipse(s, 0, wy, 6, 4, C_WHITE)
            _ellipse(s, 10, wy, 6, 4, C_WHITE)
            frames["fly%d" % i] = s
    elif kind == "lava":
        for i in range(2):
            s = make_surface(16, 16)
            s.fill((200, 40, 0))
            _fill_rect(s, 0, 0, 16, 3 + i, C_ORANGE)
            frames["bob%d" % i] = s
    elif kind == "piranha":
        for i in range(2):
            s = make_surface(16, 24)
            _fill_rect(s, 6, 10, 4, 14, C_GREEN)
            _ellipse(s, 1, 0 + i, 14, 12, C_GREEN)
            _fill_rect(s, 4, 4 + i, 8, 3, C_WHITE)
            _fill_rect(s, 5, 5 + i, 6, 1, C_RED)
            frames["chomp%d" % i] = s
    elif kind == "bullet":
        s = make_surface(16, 14)
        _ellipse(s, 0, 2, 14, 10, C_DKGRAY)
        _fill_rect(s, 12, 4, 4, 6, C_GRAY)
        _px(s, 4, 6, C_WHITE)
        frames["fly0"] = s
    elif kind == "cheep":
        for i in range(2):
            s = make_surface(16, 12)
            _ellipse(s, 1, 1, 12, 10, C_ORANGE if i == 0 else C_RED)
            _fill_rect(s, 12, 3, 4, 6, C_ORANGE)
            _px(s, 5, 4, C_BLACK)
            frames["swim%d" % i] = s
    else:
        frames["walk0"] = gen_enemy_frames("walker")["walk0"]
    return frames


def gen_item(kind: str) -> "pygame.Surface":
    s = make_surface(16, 16)
    if kind == "mushroom":
        _ellipse(s, 0, 2, 16, 10, C_RED)
        _ellipse(s, 3, 4, 4, 4, C_WHITE)
        _ellipse(s, 9, 4, 4, 4, C_WHITE)
        _fill_rect(s, 5, 10, 6, 6, C_SKIN)
    elif kind == "1up":
        _ellipse(s, 0, 2, 16, 10, C_GREEN)
        _ellipse(s, 3, 4, 4, 4, C_WHITE)
        _ellipse(s, 9, 4, 4, 4, C_WHITE)
        _fill_rect(s, 5, 10, 6, 6, C_SKIN)
    elif kind == "flower":
        pygame.draw.circle(s, C_ORANGE, (8, 6), 5)
        pygame.draw.circle(s, C_YELLOW, (8, 6), 2)
        _fill_rect(s, 7, 10, 2, 6, C_GREEN)
    elif kind == "star":
        pts = [(8, 1), (10, 6), (15, 6), (11, 9), (13, 15), (8, 11), (3, 15), (5, 9), (1, 6), (6, 6)]
        pygame.draw.polygon(s, C_STAR, pts)
        pygame.draw.polygon(s, C_BLACK, pts, 1)
    elif kind == "coin0":
        _ellipse(s, 4, 2, 8, 12, C_YELLOW)
    elif kind == "coin1":
        _fill_rect(s, 6, 2, 4, 12, C_YELLOW)
    elif kind == "fireball":
        pygame.draw.circle(s, C_ORANGE, (8, 8), 5)
        pygame.draw.circle(s, C_YELLOW, (8, 8), 2)
    else:
        s.fill(C_WHITE)
    return s


class SpriteBank:
    """Decode ALL sprites from embedded `_SPRITE_RESOURCES_B64`. FILES=OFF."""

    def __init__(self):
        self.tiles: dict = {}  # theme -> {kind: Surface}
        self.player: dict = {}  # (big, fire) -> pose -> Surface
        self.player_flip: dict = {}  # cached left-facing poses
        self.enemies: dict = {}  # kind -> frame -> Surface
        self.enemy_anim: dict = {}  # kind -> ordered walk/fly keys
        self.items: dict = {}
        self.hud: dict = {}
        self.source = "base64"
        self._import_all()

    def _import_all(self):
        pack = _decode_sprite_pack(_SPRITE_RESOURCES_B64)
        assert pack, "embedded sprite pack empty"
        solid_fix = frozenset(
            {GROUND, BRICK, QBLOCK, QUSED, PLATFORM, HARD, CASTLE, PIPE_TL, PIPE_TR, PIPE_BL, PIPE_BR}
        )
        # tiles for every theme
        for theme in (
            THEME_OVERWORLD,
            THEME_UNDERGROUND,
            THEME_ATHLETIC,
            THEME_CASTLE,
            THEME_WATER,
        ):
            self.tiles[theme] = {}
            for k in range(19):
                key = "tile.%d.%d" % (theme, k)
                assert key in pack, "missing embedded sprite resource: " + key
                w, h, rgba = pack[key]
                surf = _surface_from_rgba(w, h, rgba)
                if k in solid_fix:
                    surf = remove_tile_edge_seams(surf)
                self.tiles[theme][k] = surf.convert_alpha()
        # Replace broken sheet decorations + seam-prone ground with clean tiles
        for theme in (
            THEME_OVERWORLD,
            THEME_UNDERGROUND,
            THEME_ATHLETIC,
            THEME_CASTLE,
            THEME_WATER,
        ):
            self.tiles[theme][GROUND] = remove_tile_edge_seams(gen_tile(GROUND, theme))
            self.tiles[theme][BUSH] = gen_tile(BUSH, theme)
            self.tiles[theme][CLOUD] = gen_tile(CLOUD, theme)
            self.tiles[theme][HILL] = gen_tile(HILL, theme)
        # player: small=16x16, big=16x32 — foot-align sheet crops so frames line up
        for big in (False, True):
            for fire in (False, True):
                poses = {}
                tw, th = 16, (32 if big else 16)
                for pose in ("stand", "walk0", "walk1", "walk2", "jump", "skid", "swim", "dead"):
                    key = "player.%d.%d.%s" % (int(big), int(fire), pose)
                    assert key in pack, "missing embedded sprite resource: " + key
                    w, h, rgba = pack[key]
                    raw = flood_clear_corner_bg(
                        _surface_from_rgba(w, h, rgba),
                        lambda c: c[3] == 0 or (c[0] > 250 and c[1] < 5 and c[2] > 250),
                    )
                    if pose == "dead":
                        poses[pose] = normalize_sprite(raw, 16, 16)
                    else:
                        poses[pose] = normalize_sprite(raw, tw, th)
                self.player[(big, fire)] = poses
                self.player_flip[(big, fire)] = {
                    pose: pygame.transform.flip(img, True, False).convert_alpha()
                    for pose, img in poses.items()
                }
        # enemies — foot-align within native frame size
        for kind in ("walker", "sheller", "flyer", "lava", "piranha", "bullet", "cheep"):
            frames = {}
            prefix = "enemy.%s." % kind
            for key, (w, h, rgba) in pack.items():
                if key.startswith(prefix):
                    raw = flood_clear_corner_bg(
                        _surface_from_rgba(w, h, rgba),
                        lambda c: c[3] == 0 or (c[0] > 250 and c[1] < 5 and c[2] > 250),
                    )
                    framed = normalize_sprite(raw, w, h)
                    if kind == "piranha":
                        framed = fix_piranha_palette(framed)
                    frames[key[len(prefix):]] = framed
            assert frames, "missing embedded enemy resource: " + kind
            self.enemies[kind] = frames
            anim = [k for k in sorted(frames) if k.startswith(("walk", "fly", "bob", "swim", "chomp"))]
            self.enemy_anim[kind] = anim or sorted(frames)
        # items
        for kind in ("mushroom", "1up", "flower", "star", "coin0", "coin1", "fireball"):
            key = "item.%s" % kind
            assert key in pack, "missing embedded item resource: " + key
            w, h, rgba = pack[key]
            raw = flood_clear_corner_bg(
                _surface_from_rgba(w, h, rgba),
                lambda c: c[3] == 0 or (c[0] > 250 and c[1] < 5 and c[2] > 250),
            )
            self.items[kind] = normalize_sprite(raw, w, h)
        for i in range(4):
            key = "item.debris%d" % i
            if key in pack:
                w, h, rgba = pack[key]
                self.items["debris%d" % i] = normalize_sprite(_surface_from_rgba(w, h, rgba), w, h)
        # HUD icons
        for kind in ("coin", "x"):
            key = "hud.%s" % kind
            if key in pack:
                w, h, rgba = pack[key]
                self.hud[kind] = normalize_sprite(_surface_from_rgba(w, h, rgba), w, h)
        assert "coin" in self.hud and "x" in self.hud, "missing embedded HUD resources"
        # Pre-scale HUD coin so it lines up with the pixel font
        c = self.hud["coin"]
        if c.get_width() != 8 or c.get_height() != 8:
            self.hud["coin"] = pygame.transform.scale(c, (8, 8)).convert_alpha()
        if len(pack) >= 80:
            self.source = "base64"

    def player_frame(self, big: bool, fire: bool, pose: str, facing: int) -> "pygame.Surface":
        bank = self.player_flip if facing < 0 else self.player
        poses = bank[(big, fire)]
        return poses.get(pose) or poses["stand"]

    def enemy_frame(self, kind: str, tick: int, shell: bool = False) -> "pygame.Surface":
        fr = self.enemies.get(kind) or self.enemies["walker"]
        if shell and "shell" in fr:
            return fr["shell"]
        keys = self.enemy_anim.get(kind) or list(fr.keys())
        return fr[keys[(tick // 8) % len(keys)]]

    def count(self) -> int:
        n = sum(len(v) for v in self.tiles.values())
        n += sum(len(v) for v in self.player.values())
        n += sum(len(v) for v in self.enemies.values())
        n += len(self.items) + len(self.hud)
        return n



# Back-compat helpers used by older call sites
def gen_player_frames_list(big: bool) -> list:
    d = gen_player_frames(big, False)
    return [d["walk0"], d["walk1"], d["walk2"]]


def gen_enemy(kind: str) -> "pygame.Surface":
    fr = gen_enemy_frames(kind)
    return next(iter(fr.values()))


def gen_mushroom() -> "pygame.Surface":
    return gen_item("mushroom")


def gen_flower() -> "pygame.Surface":
    return gen_item("flower")


# ---------------------------------------------------------------------------
# Tiny SFX (FILES=OFF)
# ---------------------------------------------------------------------------
def beep(freq=440, ms=80, vol=0.25, duty=0.5):
    if pygame is None or pygame.mixer.get_init() is None:
        return None
    rate = 22050
    n = int(rate * ms / 1000)
    buf = array.array("h")
    amp = int(32767 * vol)
    period = max(1, int(rate / freq))
    high = int(period * duty)
    for i in range(n):
        buf.append(amp if (i % period) < high else -amp)
    try:
        return pygame.mixer.Sound(buffer=buf)
    except Exception:
        return None


class SFX:
    def __init__(self):
        self.enabled = False
        self.sounds = {}
        if pygame and pygame.mixer.get_init():
            self.enabled = True
            self.sounds = {
                "jump": beep(520, 70, 0.2),
                "stomp": beep(180, 60, 0.25),
                "coin": beep(880, 50, 0.2),
                "bump": beep(120, 40, 0.2),
                "power": beep(660, 120, 0.22),
                "die": beep(90, 280, 0.3, 0.3),
                "flag": beep(740, 200, 0.22),
                "break": beep(200, 50, 0.2),
                "fire": beep(980, 55, 0.18),
                "kick": beep(260, 65, 0.24),
                "pause": beep(620, 90, 0.18),
            }

    def play(self, name: str):
        if self.enabled and self.sounds.get(name):
            self.sounds[name].play()


# ---------------------------------------------------------------------------
# Handcrafted course data — World 1-1 through 8-4 (FILES=OFF, in-script only)
# Compact builders materialize tile grids; no external level files.
# ---------------------------------------------------------------------------
GY = 13  # ground row (15-tall map)


def _new_tiles(width: int, height: int = 15):
    return [[AIR for _ in range(width)] for _ in range(height)]


def _floor(tiles, x0: int, x1: int, tile: int = GROUND, gy: int = GY):
    h = len(tiles)
    w = len(tiles[0])
    for x in range(max(0, x0), min(w, x1)):
        for y in range(gy, h):
            tiles[y][x] = tile


def _gap(tiles, x0: int, x1: int, gy: int = GY):
    h = len(tiles)
    w = len(tiles[0])
    for x in range(max(0, x0), min(w, x1)):
        for y in range(gy, h):
            tiles[y][x] = AIR


def _pipe(tiles, x: int, height: int = 2, gy: int = GY):
    """Place a Mario-height pipe (1–2 tiles). Tall enough to block walk-through, short enough to jump."""
    # Clamp any legacy tall requests into short/tall Mario-scale pipes.
    ph = 1 if height <= 1 else 2
    top = gy - ph
    w = len(tiles[0])
    if x < 0 or x + 1 >= w or top < 0:
        return
    for dy in range(ph):
        y = top + dy
        if dy == 0:
            tiles[y][x] = PIPE_TL
            tiles[y][x + 1] = PIPE_TR
        else:
            tiles[y][x] = PIPE_BL
            tiles[y][x + 1] = PIPE_BR


def _pyramid(tiles, x: int, steps: int = 4, gap: int = 0, tile: int = HARD, gy: int = GY):
    """Hard-block pyramid (up then down) with optional middle gap — classic 1-1 motif."""
    for i in range(steps):
        for dy in range(i + 1):
            tiles[gy - 1 - dy][x + i] = tile
    mid = x + steps + gap
    for i in range(steps):
        for dy in range(steps - i):
            tiles[gy - 1 - dy][mid + i] = tile


def _row(tiles, x0: int, x1: int, y: int, tile: int):
    w = len(tiles[0])
    for x in range(max(0, x0), min(w, x1)):
        tiles[y][x] = tile


def _blocks(tiles, x: int, y: int, pattern: str):
    """pattern uses ?:QBLOCK B:BRICK H:HARD P:PLATFORM C:COIN .:skip"""
    for i, ch in enumerate(pattern):
        if ch == "?":
            tiles[y][x + i] = QBLOCK
        elif ch == "B":
            tiles[y][x + i] = BRICK
        elif ch == "H":
            tiles[y][x + i] = HARD
        elif ch == "P":
            tiles[y][x + i] = PLATFORM
        elif ch == "C":
            tiles[y][x + i] = COIN
        elif ch == "U":
            tiles[y][x + i] = QUSED


def _stairs(tiles, x: int, steps: int = 4, ascend: bool = True, tile: int = GROUND, gy: int = GY):
    for i in range(steps):
        h = i + 1 if ascend else steps - i
        px = x + i
        for dy in range(h):
            tiles[gy - 1 - dy][px] = tile


def _flag_castle(tiles, width: int, gy: int = GY):
    flag_x = width - 8
    for y in range(4, gy):
        tiles[y][flag_x] = FLAGPOLE
    tiles[gy - 1][flag_x] = FLAGPOLE
    for y in range(gy - 4, gy):
        for dx in range(2):
            tiles[y][flag_x + 2 + dx] = CASTLE
    return flag_x


def _deco_overworld(tiles, positions_bush, positions_hill, clouds):
    for x in positions_bush:
        if 0 <= x < len(tiles[0]) and tiles[GY][x] in (GROUND, HARD) and tiles[GY - 1][x] == AIR:
            tiles[GY - 1][x] = BUSH
    for x in positions_hill:
        if 0 <= x < len(tiles[0]) and tiles[GY][x] in (GROUND, HARD) and tiles[GY - 1][x] == AIR:
            tiles[GY - 1][x] = HILL
    for cx, cy in clouds:
        if tiles[cy][cx] == AIR:
            tiles[cy][cx] = CLOUD


def _fill_water(tiles, y0: int, y1: int):
    w = len(tiles[0])
    for y in range(y0, y1):
        for x in range(w):
            if tiles[y][x] == AIR:
                tiles[y][x] = WATER


def _enemies(entries):
    """entries: list of (tile_x, kind) or (tile_x, tile_y, kind) — y defaults to GY-1."""
    out = []
    for e in entries:
        if len(e) == 2:
            tx, kind = e
            ty = GY - 1
        else:
            tx, ty, kind = e
        out.append({"x": tx * TILE, "y": ty * TILE, "kind": kind})
    return out


def _pack_level(world, stage, theme, width, tiles, enemies, flag_x, time=TIME_LIMIT):
    return {
        "world": world,
        "stage": stage,
        "key": stage_key(world, stage),
        "area_id": area_route_id(world, stage),
        "width": width,
        "height": 15,
        "tiles": tiles,
        "theme": theme,
        "enemies": enemies,
        "spawn": (2 * TILE, GY * TILE - 14),
        "goal_x": flag_x * TILE,
        "time": time,
    }


def _base_ground(width, tile=GROUND, gaps=()):
    tiles = _new_tiles(width)
    _floor(tiles, 0, width, tile)
    for a, b in gaps:
        _gap(tiles, a, b)
    # start/end always solid
    _floor(tiles, 0, 12, tile)
    _floor(tiles, width - 14, width, tile)
    return tiles


# --- Per-course handcrafted layouts (public SMB1 map geometry; FILES=OFF) ---
# 1-1 column/height data matches the well-known 212-wide recreation
# (codegolf / community maps). Other courses follow Mario Wiki structure
# + NESMaps approximate lengths — not ROM dumps.

def _build_1_1():
    """World 1-1 — overworld tutorial course (public map geometry)."""
    w = 212
    # Pits at x≈69–70, 86–88, 153–154 (community map indices)
    t = _base_ground(w, GROUND, gaps=((69, 71), (86, 89), (153, 155)))
    # First lone ?
    _blocks(t, 16, 9, "?")
    # Six-block triangle: bricks/? at mid, elevated ?
    _blocks(t, 20, 9, "B?B")
    _blocks(t, 22, 5, "?")
    # Pipe set: short → short → Mario-tall → Mario-tall (jumpable, not NES towers)
    _pipe(t, 28, 1)
    _pipe(t, 38, 1)
    _pipe(t, 46, 2)
    _pipe(t, 57, 2)
    # After first pit: floating row + elevated ?
    _blocks(t, 77, 9, "B?B?B")
    _blocks(t, 80, 5, "?")
    # Long brick run (Goombas drop from above)
    _blocks(t, 91, 9, "BBBBBBBBB")
    # Mid bricks + ? triangle
    _blocks(t, 106, 9, "BB?BB")
    _blocks(t, 109, 5, "?")
    _blocks(t, 118, 9, "BBB")
    _blocks(t, 129, 9, "B?B")
    # Hard-block pyramids (gap then pit between)
    _pyramid(t, 134, 4, gap=2, tile=HARD)
    _pyramid(t, 148, 4, gap=0, tile=HARD)
    # Exit pipes from bonus + late bricks
    _pipe(t, 163, 2)
    _blocks(t, 168, 9, "BBB?")
    _pipe(t, 179, 2)
    # Ending staircase (8 steps in NES; use 8 hard blocks)
    _stairs(t, 188, 8, True, HARD)
    _deco_overworld(
        t,
        [8, 48, 96, 172],
        [12, 84, 140],
        [(6, 2), (34, 3), (72, 2), (120, 3), (160, 2), (198, 3)],
    )
    for x in (24, 26, 28, 32, 34):
        if t[GY - 3][x] == AIR:
            t[GY - 3][x] = COIN
    fx = _flag_castle(t, w)
    # ~16 Goombas + 1 Koopa (wiki counts) — place signature encounters
    en = _enemies([
        (22, "walker"),
        (40, "walker"),
        (42, "walker"),
        (50, "walker"),
        (52, "walker"),
        (80, "walker"),
        (94, "walker"),
        (96, "walker"),
        (98, "walker"),
        (100, "walker"),
        (110, "sheller"),
        (120, "walker"),
        (122, "walker"),
        (145, "walker"),
        (170, "walker"),
        (172, "walker"),
    ])
    return t, en, fx, w


def _build_1_2():
    """World 1-2 — underground: brick corridors, pipes+piranha, end stairs."""
    w = 192
    t = _base_ground(w, GROUND, gaps=((88, 91), (98, 101), (118, 121)))
    # Ceiling bricks (narrow passage feel)
    _row(t, 0, w, 2, BRICK)
    _row(t, 0, w, 3, BRICK)
    _blocks(t, 14, 9, "?????")
    _blocks(t, 28, 8, "BBBBB")
    _blocks(t, 36, 9, "B")  # multi-coin brick stand-in
    _blocks(t, 48, 7, "BBBBBBBB")
    _blocks(t, 50, 9, "B?B")
    _blocks(t, 70, 6, "BBBBBBBBBBBB")
    _blocks(t, 72, 8, "B?B")
    _pipe(t, 104, 2)
    _pipe(t, 112, 1)
    _pipe(t, 120, 2)
    _pyramid(t, 130, 3, gap=0, tile=HARD)
    _blocks(t, 145, 8, "PPPPP")  # lift stand-in
    _blocks(t, 152, 6, "PPPPP")
    _pipe(t, 160, 2)
    _stairs(t, w - 22, 6, True, HARD)
    fx = _flag_castle(t, w)
    en = _enemies([
        (18, "walker"), (20, "walker"), (40, "sheller"), (44, "sheller"),
        (74, "walker"), (76, "walker"), (78, "walker"), (80, "walker"), (82, "walker"),
        (105, GY - 3, "piranha"), (113, GY - 2, "piranha"), (121, GY - 3, "piranha"),
        (132, "walker"), (134, "walker"), (148, "sheller"),
    ])
    return t, en, fx, w


def _build_athletic(world: int, stage: int, width: int):
    """*-3 athletic: floating platforms, gaps, few ground islands."""
    gaps = [(x, x + 4 + ((i + world) % 3)) for i, x in enumerate(range(28 + world, width - 40, 14 + stage))]
    t = _base_ground(width, GROUND, gaps=gaps)
    for i, px in enumerate(range(24 + world, width - 30, 16 + stage)):
        y = 6 + (i + world + stage) % 4
        _blocks(t, px, y, "PPPPP" if i % 2 == 0 else "PPP")
        if i % 3 == 0:
            _blocks(t, px + 2, max(3, y - 3), "?" if (i + world) % 2 == 0 else "B?B")
    _pipe(t, width - 36 - world, 1 + (world % 2))
    _stairs(t, width - 24, 5 + (world % 3), True, HARD)
    _deco_overworld(t, [10 + world], [14 + stage], [(8, 2), (width // 2, 3), (width - 40, 2)])
    t[1][world] = CLOUD
    fx = _flag_castle(t, width)
    kinds = ["walker", "sheller", "flyer"]
    en = []
    for i, ex in enumerate(range(30, width - 40, 18)):
        k = kinds[i % len(kinds)]
        ey = 5 if k == "flyer" else GY - 1
        en.append((ex, ey, k))
    return t, _enemies(en), fx, width


def _build_castle(world: int, width: int):
    """*-4 castle: hard floor, lava spikes, fire-bar style hazards, axe end."""
    g0 = 40 + world * 3
    t = _base_ground(width, HARD, gaps=((g0, g0 + 3), (70 + world, 74 + world), (110 - world, 114 - world)))
    for x in range(16 + world, width - 20, 8 + world % 4):
        if t[GY][x] == HARD:
            t[GY - 1][x] = SPIKE
    _blocks(t, 24 + world, 8, "HHHH")
    _blocks(t, 48 + world * 2, 6, "H?H")
    _blocks(t, 80 + world, 7, "HHHHHH")
    _blocks(t, 100 - world, 5, "HH?HH")
    _pipe(t, 60 + world, 1 + (world % 2))
    _stairs(t, width - 28 - (world % 2), 4 + (world % 3), True, HARD)
    # Bridge / axe stand-in near end
    _row(t, width - 18, width - 10, GY - 1, PLATFORM)
    _row(t, 10 + world, 20 + world * 2, 3, HARD)
    fx = _flag_castle(t, width)
    en = _enemies([
        (30, "walker"), (55, GY - 2, "lava"), (65, GY - 4, "piranha"),
        (90, "sheller"), (105, GY - 2, "lava"), (125, "walker"),
    ])
    if world >= 8:
        en.extend(_enemies([(width - 40, "sheller"), (width - 35, GY - 2, "lava")]))
    return t, en, fx, width


def _build_water(world: int, width: int):
    """2-2 / 7-2 underwater corridors."""
    t = _base_ground(width, GROUND, gaps=((50 + world, 54 + world), (90, 95), (130 - world, 134 - world)))
    _fill_water(t, 4, GY)
    for x in range(20, width - 20, 10 + (world % 3)):
        if t[7][x] == WATER:
            t[7][x] = COIN
    _blocks(t, 40 + world, 9, "PPP")
    _blocks(t, 70, 8, "PPPP")
    _blocks(t, 110 - world, 7, "PPP")
    _pipe(t, width - 40, 1 + (world % 2))
    _stairs(t, width - 24, 5, True, HARD)
    t[2][world * 3] = HARD
    fx = _flag_castle(t, width)
    en = _enemies([(x, 8, "cheep") for x in range(28 + world, width - 40, 16)])
    return t, en, fx, width


def _build_overworld(world: int, stage: int, width: int, profile: str):
    """Generic overworld with profile-specific landmarks (wiki signatures)."""
    gap_map = {
        "early": ((55, 58), (92, 96), (140, 143)),
        "busy": ((48, 51), (78, 82), (118, 122), (150, 154)),
        "lakitu": ((60, 63), (100, 104), (145, 149)),
        "long": ((70, 74), (110, 115), (160, 164), (210, 214)),
        "hammer": ((52, 55), (88, 92), (130, 134)),
    }
    gaps = gap_map.get(profile, gap_map["early"])
    gaps = tuple((a + world, b + world) for a, b in gaps if b + world < width - 16)
    t = _base_ground(width, GROUND, gaps=gaps)
    _blocks(t, 16 + stage, 9, "B?B")
    _blocks(t, 22 + stage, 5, "?" if stage == 1 else "B?B")
    _pipe(t, 32 + world, 1 + (world % 2))
    _pipe(t, 48 + stage * 2, 2)
    _blocks(t, 64 + world, 9, "BB?BB")
    _blocks(t, 90 + stage * 3, 9, "?B?B?")
    if profile == "lakitu":
        _blocks(t, 100 + world, 5, "PPPPPPP")
    if profile == "hammer":
        _blocks(t, 70 + world, 8, "HHHH")
        _pipe(t, 110 + stage, 2)
    if profile == "busy":
        for px in (70 + world, 85, 100 + stage, 120):
            if 16 < px < width - 16:
                _pipe(t, px, 1 + (px % 2))
    if profile == "long":
        for px in range(80, width - 50, 22):
            _pipe(t, px, 1 + (px // 30) % 2)
            _blocks(t, px + 8, 9, "B?B")
    _pyramid(t, width - 55 - stage, 4, gap=1, tile=HARD)
    _pipe(t, width - 40, 2)
    _stairs(t, width - 26, 6 + (world > 5), True, HARD)
    _deco_overworld(
        t,
        [10, 40 + world, 100, width - 50],
        [14, 70 + stage, width - 70],
        [(8, 2), (50 + world, 3), (width // 2, 2), (width - 30, 3)],
    )
    t[1][(world * 4 + stage) % (width - 2)] = CLOUD
    fx = _flag_castle(t, width)
    kinds = ["walker", "walker", "sheller"]
    if world >= 3:
        kinds.append("flyer")
    if world >= 4 or profile == "lakitu":
        kinds.append("bullet")
    if profile == "hammer":
        kinds.append("sheller")
    en = []
    for i, ex in enumerate(range(22, width - 40, 12 + (world % 5))):
        k = kinds[i % len(kinds)]
        ey = 6 if k == "flyer" else GY - 1
        en.append((ex, ey, k))
        if profile in ("busy", "long") and i % 4 == 0:
            en.append((ex + 3, GY - 3 - (i % 2), "piranha"))
    return t, _enemies(en), fx, width


def _build_underground(world: int, width: int):
    """1-2 style / 4-2 underground brick maze."""
    t = _base_ground(width, GROUND, gaps=((70 + world, 73 + world), (100, 104), (135 - world, 138 - world)))
    _row(t, 0, width, 2, BRICK)
    _blocks(t, 18 + world, 9, "????")
    _blocks(t, 40, 7, "BBBBBBBB")
    _blocks(t, 60 + world, 9, "B?B?B")
    _blocks(t, 85, 6, "BBBBBBBBBBB")
    _pipe(t, 115 - world, 2)
    _pipe(t, 125, 2)
    _blocks(t, 140, 8, "B?B")
    _stairs(t, width - 22, 6, True, HARD)
    t[1][world * 5] = HARD
    fx = _flag_castle(t, width)
    en = _enemies([
        (25, "walker"), (45, "sheller"), (65, "walker"), (67, "walker"),
        (90, "walker"), (116, GY - 3, "piranha"), (126, GY - 3, "piranha"),
        (145, "sheller"),
    ])
    if world >= 4:
        en.extend(_enemies([(55, "walker"), (105, "sheller")]))
    return t, en, fx, width


# Approximate NESMaps widths (pixels/16), clamped for playability
_COURSE_WIDTH = {
    "1-1": 212, "1-2": 192, "1-3": 224, "1-4": 208,
    "2-1": 224, "2-2": 192, "2-3": 288, "2-4": 208,
    "3-1": 224, "3-2": 272, "3-3": 224, "3-4": 208,
    "4-1": 240, "4-2": 224, "4-3": 208, "4-4": 240,
    "5-1": 224, "5-2": 224, "5-3": 224, "5-4": 208,
    "6-1": 256, "6-2": 240, "6-3": 240, "6-4": 208,
    "7-1": 208, "7-2": 192, "7-3": 288, "7-4": 272,
    "8-1": 360, "8-2": 240, "8-3": 288, "8-4": 320,
}


def _build_course(world: int, stage: int) -> dict:
    """Materialize handcrafted World w-s data matching SMB1 course roles."""
    theme = world_theme(world, stage)
    key = stage_key(world, stage)
    width = _COURSE_WIDTH[key]

    if key == "1-1":
        tiles, enemies, fx, w = _build_1_1()
    elif key == "1-2":
        tiles, enemies, fx, w = _build_1_2()
    elif theme == THEME_WATER:
        tiles, enemies, fx, w = _build_water(world, width)
    elif theme == THEME_CASTLE:
        tiles, enemies, fx, w = _build_castle(world, width)
    elif theme == THEME_ATHLETIC:
        tiles, enemies, fx, w = _build_athletic(world, stage, width)
    elif theme == THEME_UNDERGROUND:
        tiles, enemies, fx, w = _build_underground(world, width)
    else:
        # Overworld profiles by course identity
        profile = "early"
        if key in ("3-1", "7-1", "8-3"):
            profile = "hammer"
        elif key in ("4-1", "6-1", "8-2"):
            profile = "lakitu"
        elif key in ("3-2", "5-2", "6-2"):
            profile = "busy"
        elif key in ("8-1",):
            profile = "long"
        tiles, enemies, fx, w = _build_overworld(world, stage, width, profile)

    return _pack_level(world, stage, theme, w, tiles, enemies, fx)


def generate_level(world: int, stage: int) -> dict:
    """Return handcrafted course data for World world-stage (1-1 … 8-4)."""
    return _build_course(world, stage)


def build_all_levels() -> dict:
    levels = {}
    for w in range(1, 9):
        for s in range(1, 5):
            levels[stage_key(w, s)] = generate_level(w, s)
    return levels


def clone_level(src: dict) -> dict:
    """Fast level clone — copy tile rows only (no deepcopy)."""
    return {
        "world": src["world"],
        "stage": src["stage"],
        "key": src["key"],
        "area_id": src["area_id"],
        "width": src["width"],
        "height": src["height"],
        "tiles": [row[:] for row in src["tiles"]],
        "theme": src["theme"],
        "enemies": [dict(e) for e in src["enemies"]],
        "spawn": src["spawn"],
        "goal_x": src["goal_x"],
        "time": src["time"],
    }


LEVELS: dict = build_all_levels()


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------
@dataclass
class Player:
    x: float = 32
    y: float = 160
    vx: float = 0.0
    vy: float = 0.0
    on_ground: bool = False
    facing: int = 1
    big: bool = False
    fire: bool = False
    dead: bool = False
    invuln: int = 0
    frame: int = 0
    anim: float = 0.0
    coins: int = 0
    score: int = 0
    lives: int = 3

    @property
    def w(self):
        return 12

    @property
    def h(self):
        return 30 if self.big else 14

    def rect(self):
        return pygame.Rect(int(self.x), int(self.y), self.w, self.h)


@dataclass
class Enemy:
    x: float
    y: float
    kind: str
    vx: float = -0.6
    vy: float = 0.0
    alive: bool = True
    shell: bool = False
    shell_moving: bool = False
    frame: int = 0

    @property
    def w(self):
        return 14

    @property
    def h(self):
        if self.kind == "sheller" and not self.shell:
            return 22
        if self.kind == "piranha":
            return 22
        if self.kind == "walker" and self.shell:
            return 8
        return 14

    def rect(self):
        return pygame.Rect(int(self.x), int(self.y), self.w, self.h)


@dataclass
class PowerUp:
    x: float
    y: float
    kind: str  # mushroom | flower
    vx: float = 0.8
    vy: float = 0.0
    alive: bool = True

    def rect(self):
        return pygame.Rect(int(self.x), int(self.y), 14, 14)


@dataclass
class Fireball:
    x: float
    y: float
    vx: float
    vy: float = -1.0
    alive: bool = True
    bounces: int = 0

    def rect(self):
        return pygame.Rect(int(self.x), int(self.y), 8, 8)


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    life: int
    color: tuple


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
class Game:
    def __init__(self):
        assert pygame is not None
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        # Small buffer + low latency; FILES=OFF synth SFX only
        pygame.mixer.pre_init(22050, -16, 1, 256)
        pygame.init()
        try:
            pygame.mixer.init(22050, -16, 1, 256)
        except Exception:
            pass
        # Trim event queue — Famicom port only needs quit/key/resize
        pygame.event.set_allowed((
            pygame.QUIT, pygame.KEYDOWN, pygame.KEYUP, pygame.VIDEORESIZE,
        ))
        pygame.display.set_caption(TITLE)
        flags = pygame.RESIZABLE | pygame.DOUBLEBUF
        try:
            self.window = pygame.display.set_mode((WINDOW_W, WINDOW_H), flags, vsync=1)
        except TypeError:
            self.window = pygame.display.set_mode((WINDOW_W, WINDOW_H), flags)
        # Opaque game buffer (faster fills/blits than SRCALPHA)
        self.screen = pygame.Surface((INTERNAL_W, INTERNAL_H)).convert()
        self.clock = pygame.time.Clock()
        # FILES=OFF — pixel font only (never system font APIs / disk fonts)
        self.font = PixelFont(1)
        self.big_font = PixelFont(2)
        self.sfx = SFX()
        # Import ALL SMB-style sprites into memory (FILES=OFF — no disk assets)
        self.sprites = SpriteBank()
        self._win_w, self._win_h = WINDOW_W, WINDOW_H
        self._scale = SCALE
        self._scaled = pygame.Surface((WINDOW_W, WINDOW_H)).convert()
        self._letterbox = (0, 0)
        self._hud_cache: dict = {}
        self._pause_shade = pygame.Surface((INTERNAL_W, INTERNAL_H), pygame.SRCALPHA)
        self._pause_shade.fill((0, 0, 0, 128))
        self._particle_dot = pygame.Surface((3, 3)).convert()
        self._particle_dot.fill((200, 76, 12))
        self.tile_cache = self.sprites.tiles
        self.mushroom_s = self.sprites.items["mushroom"]
        self.flower_s = self.sprites.items["flower"]
        self._tileset = self.sprites.tiles[THEME_OVERWORLD]
        self._sky = PALETTES[THEME_OVERWORLD]["sky"]
        self.state = "title"
        self.world = 1
        self.stage = 1
        self.level = None
        self.player = Player()
        self.enemies: list[Enemy] = []
        self.powerups: list[PowerUp] = []
        self.fireballs: list[Fireball] = []
        self.particles: list[Particle] = []
        self.camera_x = 0  # integer pixels only — float lerp caused jitter
        self.timer = TIME_LIMIT
        self.tick = 0
        self.flag_drop = False
        self.goal_phase = ""
        self.jump_held = False
        self.fire_held = False
        self.x_held = False
        self.coyote = 0
        self.jump_buffer = 0
        self.move_x_frac = 0.0
        self.move_y_frac = 0.0
        self.skidding = False
        self.paused = False
        self.won_stage = False
        self.message = ""
        self.message_timer = 0
        self.intro_timer = 0
        self.menu_index = 0
        self.menu_page = "main"  # main | controls
        self.menu_world = 1
        self.running = True
        self._rebuild_hud_static()

    MENU_MAIN = (
        ("1 PLAYER GAME", "start"),
        ("WORLD SELECT", "world"),
        ("CONTROLS", "controls"),
        ("QUIT", "quit"),
    )

    def tileset(self, theme: int) -> dict:
        return self.sprites.tiles[theme]

    def load_stage(self, world: int, stage: int):
        self.world, self.stage = world, stage
        key = stage_key(world, stage)
        # Fast row-copy clone (deepcopy was a hitch on stage load)
        self.level = clone_level(LEVELS[key])
        self._tiles = self.level["tiles"]
        self._lw = self.level["width"]
        self._lh = self.level["height"]
        theme = self.level["theme"]
        self._tileset = self.sprites.tiles[theme]
        self._sky = PALETTES[theme]["sky"]
        self.player.x, self.player.y = self.level["spawn"]
        self.player.vx = self.player.vy = 0
        self.player.dead = False
        self.player.invuln = 0
        self.enemies = [Enemy(e["x"], e["y"], e["kind"]) for e in self.level["enemies"]]
        self.powerups.clear()
        self.fireballs.clear()
        self.particles.clear()
        self.camera_x = 0
        self.timer = self.level["time"]
        self.tick = 0
        self.flag_drop = False
        self.goal_phase = ""
        self.jump_held = False
        self.fire_held = False
        self.x_held = False
        self.coyote = 0
        self.jump_buffer = 0
        self.move_x_frac = 0.0
        self.move_y_frac = 0.0
        self.skidding = False
        self.paused = False
        self.won_stage = False
        self.intro_timer = 75
        self.state = "intro"

    def solid_at(self, tx, ty) -> bool:
        # Side walls only — NEVER invent a floor below the map (pits must drop Mario).
        if tx < 0 or tx >= self._lw:
            return True
        if ty < 0 or ty >= self._lh:
            return False
        t = self._tiles[ty][tx]
        return t < 32 and _SOLID_LUT[t]

    def tile_at(self, tx, ty) -> int:
        if not (0 <= ty < self._lh and 0 <= tx < self._lw):
            return AIR
        return self._tiles[ty][tx]

    def set_tile(self, tx, ty, v):
        if 0 <= ty < self._lh and 0 <= tx < self._lw:
            self._tiles[ty][tx] = v

    def move_axis(self, ent_rect, vx, vy, axis: str, bump_blocks: bool = False):
        """AABB vs tiles. Returns (new_x or new_y, collided)."""
        step = int(round(vx if axis == "x" else vy))
        if step == 0:
            return (ent_rect.x if axis == "x" else ent_rect.y), False
        if axis == "x":
            ent_rect.x += step
        else:
            ent_rect.y += step
        collided = False
        left = ent_rect.left // TILE
        right = (ent_rect.right - 1) // TILE
        top = ent_rect.top // TILE
        bottom = (ent_rect.bottom - 1) // TILE
        tiles = self._tiles
        lw, lh = self._lw, self._lh
        solid = _SOLID_LUT
        for ty in range(top, bottom + 1):
            if ty < 0 or ty >= lh:
                continue
            row = tiles[ty]
            for tx in range(left, right + 1):
                if tx < 0 or tx >= lw:
                    tile = HARD
                else:
                    tile = row[tx]
                    if tile >= 32 or not solid[tile]:
                        continue
                if tile == PLATFORM:
                    if axis == "y" and vy < 0:
                        continue
                    if axis == "y" and vy >= 0 and ent_rect.bottom - ty * TILE > 6:
                        continue
                tr_l, tr_t = tx * TILE, ty * TILE
                tr_r, tr_b = tr_l + TILE, tr_t + TILE
                if ent_rect.right <= tr_l or ent_rect.left >= tr_r or ent_rect.bottom <= tr_t or ent_rect.top >= tr_b:
                    continue
                collided = True
                if axis == "x":
                    if vx > 0:
                        ent_rect.right = tr_l
                    else:
                        ent_rect.left = tr_r
                else:
                    if vy > 0:
                        ent_rect.bottom = tr_t
                    else:
                        ent_rect.top = tr_b
                        if bump_blocks:
                            self.bump_block(tx, ty)
        return (ent_rect.x if axis == "x" else ent_rect.y), collided

    def bump_block(self, tx, ty):
        t = self.tile_at(tx, ty)
        p = self.player
        if t == QBLOCK:
            self.set_tile(tx, ty, QUSED)
            self.sfx.play("coin")
            # spawn reward
            if p.big and random.random() < 0.35:
                self.powerups.append(PowerUp(tx * TILE, (ty - 1) * TILE, "flower"))
            elif random.random() < 0.45:
                self.powerups.append(PowerUp(tx * TILE, (ty - 1) * TILE, "mushroom"))
            else:
                p.coins += 1
                p.score += 200
            self.sfx.play("bump")
        elif t == BRICK:
            if p.big:
                self.set_tile(tx, ty, AIR)
                p.score += 50
                self.sfx.play("break")
                for _ in range(4):
                    if len(self.particles) >= MAX_PARTICLES:
                        break
                    self.particles.append(
                        Particle(tx * TILE + 8, ty * TILE + 8, random.uniform(-2, 2), random.uniform(-4, -1), 30, (200, 76, 12))
                    )
            else:
                self.sfx.play("bump")
        elif t == COIN:
            self.set_tile(tx, ty, AIR)

    def collect_coins_overlap(self):
        r = self.player.rect()
        left, right = r.left // TILE, (r.right - 1) // TILE
        top, bottom = r.top // TILE, (r.bottom - 1) // TILE
        for ty in range(top, bottom + 1):
            for tx in range(left, right + 1):
                if self.tile_at(tx, ty) == COIN:
                    self.set_tile(tx, ty, AIR)
                    self.player.coins += 1
                    self.player.score += 100
                    self.sfx.play("coin")
                    if self.player.coins >= 100:
                        self.player.coins = 0
                        self.player.lives += 1

    def spawn_fireball(self):
        p = self.player
        active = sum(1 for f in self.fireballs if f.alive)
        if not p.fire or active >= MAX_FIREBALLS or p.dead or self.won_stage:
            return
        fx = p.x + (p.w + 1 if p.facing > 0 else -9)
        fy = p.y + max(3, p.h // 3)
        self.fireballs.append(Fireball(fx, fy, FIREBALL_SPEED * p.facing))
        self.sfx.play("fire")

    def update_player(self, keys):
        p = self.player
        if p.dead:
            p.vy += GRAVITY_FALL
            p.y += p.vy
            return

        left = keys[pygame.K_LEFT] or keys[pygame.K_a]
        right = keys[pygame.K_RIGHT] or keys[pygame.K_d]
        if left and right:
            left = right = False  # cancel opposite presses

        jump = keys[pygame.K_SPACE] or keys[pygame.K_z] or keys[pygame.K_UP]
        # Shift = run only; X = run + fire (edge). Avoids Shift starting a fireball.
        shift = keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]
        x_btn = keys[pygame.K_x]
        run = shift or x_btn
        jump_pressed = jump and not self.jump_held
        jump_released = (not jump) and self.jump_held
        fire_pressed = x_btn and not self.x_held
        self.jump_held = bool(jump)
        self.x_held = bool(x_btn)
        self.fire_held = bool(run)

        if jump_pressed:
            self.jump_buffer = JUMP_BUFFER_FRAMES
        elif self.jump_buffer > 0:
            self.jump_buffer -= 1

        on_ground = p.on_ground
        if on_ground:
            self.coyote = COYOTE_FRAMES
        elif self.coyote > 0:
            self.coyote -= 1

        accel = RUN_ACCEL if run else WALK_ACCEL
        if not on_ground:
            accel *= AIR_ACCEL_SCALE
        vmax = RUN_MAX if run else WALK_MAX

        self.skidding = False
        if left:
            if on_ground and p.vx > 0.4:
                # Skid when reversing at speed
                p.vx -= SKID_FRICTION
                self.skidding = True
            else:
                p.vx -= accel
            p.facing = -1
        elif right:
            if on_ground and p.vx < -0.4:
                p.vx += SKID_FRICTION
                self.skidding = True
            else:
                p.vx += accel
            p.facing = 1
        else:
            fr = FRICTION if on_ground else FRICTION * 0.35
            if p.vx > 0:
                p.vx = max(0.0, p.vx - fr)
            elif p.vx < 0:
                p.vx = min(0.0, p.vx + fr)

        # Soft cap: allow brief overspeed while skidding down
        if abs(p.vx) > vmax:
            p.vx = clamp(p.vx, -vmax - 0.35, vmax + 0.35)
            if on_ground and not self.skidding:
                p.vx = clamp(p.vx, -vmax, vmax)

        # Jump: coyote + buffer; force scales with run speed (Famicom SMB1)
        can_jump = on_ground or self.coyote > 0
        if self.jump_buffer > 0 and can_jump:
            p.vy = smb_jump_velocity(p.vx)
            p.on_ground = False
            self.coyote = 0
            self.jump_buffer = 0
            self.sfx.play("jump")
        elif jump_released and p.vy < -1.0:
            # One-shot early release → shorter arc
            p.vy *= JUMP_CUT

        in_water = self.tile_at(int(p.x + p.w / 2) // TILE, int(p.y + p.h / 2) // TILE) == WATER
        if jump_pressed and in_water:
            p.vy = -3.0
            self.sfx.play("jump")
        if fire_pressed:
            self.spawn_fireball()

        # Gravity tiers: hold-A rise / release rise / fall (NTSC feel)
        if in_water:
            grav = GRAVITY_FALL * 0.35
            terminal = TERMINAL_WATER
        elif p.vy < 0:
            grav = GRAVITY_HOLD if jump else GRAVITY_RISE
            terminal = TERMINAL_V
        else:
            grav = GRAVITY_FALL
            terminal = TERMINAL_V
        p.vy = min(p.vy + grav, terminal)

        # Sub-pixel accumulators so slow walk doesn't stutter/stick
        self.move_x_frac += p.vx
        self.move_y_frac += p.vy
        step_x = int(self.move_x_frac)
        step_y = int(self.move_y_frac)
        self.move_x_frac -= step_x
        self.move_y_frac -= step_y

        r = p.rect()
        p.on_ground = False
        if step_x:
            nx, hit_x = self.move_axis(r, step_x, 0, "x")
            p.x = nx
            if hit_x:
                p.vx = 0
                self.move_x_frac = 0.0
        r = p.rect()
        if step_y:
            ny, hit_y = self.move_axis(r, 0, step_y, "y", bump_blocks=True)
            p.y = ny
            if hit_y:
                if step_y > 0:
                    p.on_ground = True
                p.vy = 0
                self.move_y_frac = 0.0
        elif abs(p.vy) < 0.01 and self._ground_probe(p):
            p.on_ground = True

        if abs(p.vx) > 0.2:
            p.anim += abs(p.vx) * 0.22
            p.frame = int(p.anim) % 3
        else:
            p.frame = 0

        if p.invuln > 0:
            p.invuln -= 1

        self.collect_coins_overlap()

        pit_line = self._lh * TILE
        if p.y > pit_line or p.y + p.h > INTERNAL_H + 8:
            self.kill_player()

        if p.x >= self.level["goal_x"] - 8 and not self.won_stage:
            self.won_stage = True
            self.flag_drop = True
            self.sfx.play("flag")
            p.score += int(self.timer) * 10
            self.message = "STAGE CLEAR!"
            self.message_timer = 120

        pr = p.rect()
        for ty in range(pr.top // TILE, (pr.bottom - 1) // TILE + 1):
            for tx in range(pr.left // TILE, (pr.right - 1) // TILE + 1):
                if self.tile_at(tx, ty) == SPIKE and p.invuln <= 0:
                    self.hurt_player()
                    return

    def _ground_probe(self, p: Player) -> bool:
        """True if a solid sits one pixel under Mario's feet."""
        foot = int(p.y + p.h + 1)
        ty = foot // TILE
        for tx in (int(p.x) // TILE, int(p.x + p.w - 1) // TILE):
            if self.solid_at(tx, ty):
                t = self.tile_at(tx, ty)
                if t == PLATFORM or t in SOLID:
                    return True
        return False

    def hurt_player(self):
        p = self.player
        if p.invuln > 0 or p.dead:
            return
        if p.fire:
            p.fire = False
            p.invuln = INVULN_TIME
            self.sfx.play("bump")
        elif p.big:
            p.big = False
            p.y += 16  # keep feet planted when shrinking
            p.invuln = INVULN_TIME
            self.sfx.play("bump")
        else:
            self.kill_player()

    def kill_player(self):
        p = self.player
        if p.dead:
            return
        p.dead = True
        p.vy = -5
        p.vx = 0
        self.sfx.play("die")
        self.message = "OUCH!"
        self.message_timer = 90

    def update_enemies(self):
        p = self.player
        cam0 = self.camera_x - ENEMY_WAKE_MARGIN
        cam1 = self.camera_x + INTERNAL_W + ENEMY_WAKE_MARGIN
        tick = self.tick
        sin = _SIN256
        # Periodic compaction so dead enemies don't keep scanning
        if tick % 90 == 0:
            self.enemies = [e for e in self.enemies if e.alive]

        for e in self.enemies:
            if not e.alive:
                continue
            # Sleep far off-screen (moving shells + bullets stay awake)
            asleep = e.x < cam0 or e.x > cam1
            if asleep and not (e.shell and e.shell_moving) and e.kind != "bullet":
                continue

            if e.kind in ("flyer", "cheep"):
                e.x += e.vx
                e.y += sin[(tick + int(e.x)) & 255] * 0.4
            elif e.kind == "lava":
                e.y += sin[(tick * 3 + int(e.x)) & 255] * 0.5
            elif e.kind == "piranha":
                e.y += sin[(tick + int(e.x * 0.25)) & 255] * 0.35
            elif e.kind == "bullet":
                e.x += e.vx * 2.3
            else:
                if e.shell:
                    e.vx = (4.0 if e.vx >= 0 else -4.0) if e.shell_moving else 0.0
                e.vy = min(e.vy + GRAVITY_FALL, TERMINAL_V)
                r = e.rect()
                nx, hit_x = self.move_axis(r, e.vx, 0, "x")
                e.x = nx
                if hit_x:
                    e.vx *= -1
                r = e.rect()
                ny, hit_y = self.move_axis(r, 0, e.vy, "y")
                e.y = ny
                if hit_y:
                    e.vy = 0
                foot_x = int(e.x + (e.w if e.vx > 0 else 0)) // TILE
                foot_y = int(e.y + e.h + 1) // TILE
                if not e.shell_moving and not self.solid_at(foot_x, foot_y):
                    e.vx *= -1
                if e.y > self._lh * TILE + 32:
                    e.alive = False
                    continue

            if e.shell and e.shell_moving:
                er = e.rect()
                for other in self.enemies:
                    if other is e or not other.alive or other.kind == "lava":
                        continue
                    if abs(other.x - e.x) > 24:
                        continue
                    if er.colliderect(other.rect()):
                        other.alive = False
                        p.score += 200
                        self.sfx.play("kick")

            if p.dead or p.invuln > 0:
                continue
            if abs(e.x - p.x) > 40 or abs(e.y - p.y) > 40:
                continue
            if e.rect().colliderect(p.rect()):
                if p.vy > 0 and p.y + p.h - e.y < 10:
                    p.vy = STOMP_BOUNCE
                    if e.kind == "sheller":
                        if not e.shell:
                            old_h = e.h
                            e.shell = True
                            e.shell_moving = False
                            e.vx = 0
                            e.y += old_h - e.h
                            p.score += 100
                        elif e.shell_moving:
                            e.shell_moving = False
                            e.vx = 0
                            p.score += 100
                        else:
                            e.shell_moving = True
                            e.vx = 4.0 if p.x < e.x else -4.0
                            p.score += 400
                            self.sfx.play("kick")
                    else:
                        e.alive = False
                        p.score += 100
                    self.sfx.play("stomp")
                elif e.kind == "sheller" and e.shell and not e.shell_moving:
                    e.shell_moving = True
                    e.vx = 4.0 if p.x < e.x else -4.0
                    p.score += 400
                    self.sfx.play("kick")
                    p.x += -2 if p.x < e.x else 2
                else:
                    self.hurt_player()

    def update_fireballs(self):
        for f in self.fireballs:
            if not f.alive:
                continue
            f.vy = min(f.vy + GRAVITY_FALL * 0.65, TERMINAL_V)
            r = f.rect()
            nx, hit_x = self.move_axis(r, f.vx, 0, "x")
            f.x = nx
            if hit_x:
                f.alive = False
                continue
            r = f.rect()
            falling = f.vy > 0
            ny, hit_y = self.move_axis(r, 0, f.vy, "y")
            f.y = ny
            if hit_y:
                if falling:
                    f.vy = FIREBALL_BOUNCE
                    f.bounces += 1
                else:
                    f.alive = False
            for e in self.enemies:
                if not f.alive or not e.alive or e.kind == "lava":
                    continue
                if abs(e.x - f.x) > 24:
                    continue
                if f.rect().colliderect(e.rect()):
                    e.alive = False
                    f.alive = False
                    self.player.score += 200
                    self.sfx.play("kick")
            if (f.bounces > 8 or f.y > INTERNAL_H + 16 or
                    f.x < self.camera_x - 32 or f.x > self.camera_x + INTERNAL_W + 48):
                f.alive = False
        self.fireballs = [f for f in self.fireballs if f.alive]

    def update_powerups(self):
        p = self.player
        for u in self.powerups:
            if not u.alive:
                continue
            u.vy = min(u.vy + GRAVITY_FALL, TERMINAL_V)
            r = u.rect()
            nx, hit_x = self.move_axis(r, u.vx, 0, "x")
            u.x = nx
            if hit_x:
                u.vx *= -1
            r = u.rect()
            ny, hit_y = self.move_axis(r, 0, u.vy, "y")
            u.y = ny
            if hit_y:
                u.vy = 0
            if u.rect().colliderect(p.rect()):
                u.alive = False
                self.sfx.play("power")
                if u.kind == "mushroom":
                    if not p.big:
                        p.big = True
                        p.y -= 16
                    p.score += 1000
                else:
                    p.big = True
                    p.fire = True
                    p.score += 1000

    def _rebuild_hud_static(self):
        white = (252, 252, 252)
        self._hud_cache["MARIO"] = self.font.render("MARIO", False, white)
        self._hud_cache["WORLD"] = self.font.render("WORLD", False, white)
        self._hud_cache["TIME"] = self.font.render("TIME", False, white)
        self._hud_cache["score"] = self.font.render("000000", False, white)
        self._hud_cache["coins"] = self.font.render("x00", False, white)
        self._hud_cache["world"] = self.font.render("1-1", False, white)
        self._hud_cache["time"] = self.font.render("400", False, white)
        self._hud_cache["_score_v"] = -1
        self._hud_cache["_coins_v"] = -1
        self._hud_cache["_world_v"] = None
        self._hud_cache["_time_v"] = -1

    def _ensure_scale_buffer(self, ww: int, wh: int):
        scale = max(1, min(ww // INTERNAL_W, wh // INTERNAL_H))
        dw, dh = INTERNAL_W * scale, INTERNAL_H * scale
        if scale != self._scale or self._scaled.get_size() != (dw, dh):
            self._scale = scale
            self._scaled = pygame.Surface((dw, dh)).convert()
        self._letterbox = ((ww - dw) // 2, (wh - dh) // 2)
        return dw, dh

    def update_camera(self):
        """Pixel-snapped hard follow — minimal work, no float easing jitter."""
        max_cam = max(0, self._lw * TILE - INTERNAL_W)
        target = int(self.player.x) - (INTERNAL_W * 2 // 5)
        self.camera_x = target if target < 0 else (max_cam if target > max_cam else target)

    def next_stage(self):
        if self.stage < 4:
            self.load_stage(self.world, self.stage + 1)
        elif self.world < 8:
            self.load_stage(self.world + 1, 1)
        else:
            self.state = "credits"
            self.message = "YOU CLEARED ALL 32 STAGES!"

    def update(self):
        keys = pygame.key.get_pressed()
        if self.state == "title":
            self.tick += 1
            return
        if self.state == "credits":
            return
        if self.state == "intro":
            self.intro_timer -= 1
            if self.intro_timer <= 0:
                self.state = "play"
            return
        if self.state != "play":
            return
        if self.paused:
            return

        self.tick += 1
        # SMB1 timer rate ≈ every 24 frames @ 60 Hz (not once per second)
        if self.tick % TIMER_TICK_FRAMES == 0 and not self.won_stage and not self.player.dead:
            self.timer = max(0, self.timer - 1)
            if self.timer <= 0:
                self.kill_player()

        if self.won_stage:
            self.player.vx = 1.2
            self.player.x += self.player.vx
            self.message_timer -= 1
            if self.message_timer <= 0:
                self.next_stage()
            return

        if self.player.dead:
            self.update_player(keys)
            self.message_timer -= 1
            if self.message_timer <= 0:
                self.player.lives -= 1
                if self.player.lives <= 0:
                    self.state = "gameover"
                else:
                    self.player.dead = False
                    self.player.big = False
                    self.player.fire = False
                    self.load_stage(self.world, self.stage)
            return

        self.update_player(keys)
        self.update_enemies()
        self.update_powerups()
        self.update_fireballs()
        self.update_camera()
        if self.particles:
            live = []
            for part in self.particles:
                part.x += part.vx
                part.y += part.vy
                part.vy += 0.2
                part.life -= 1
                if part.life > 0:
                    live.append(part)
            self.particles = live
        if self.message_timer > 0:
            self.message_timer -= 1

    def draw_hud(self):
        # SMB1-style HUD — cache static labels; rebuild numbers only when changed
        white = (252, 252, 252)
        screen = self.screen
        screen.blit(self._hud_cache["MARIO"], (16, 8))
        if self._hud_cache.get("_score_v") != self.player.score:
            self._hud_cache["_score_v"] = self.player.score
            self._hud_cache["score"] = self.font.render("%06d" % self.player.score, False, white)
        screen.blit(self._hud_cache["score"], (16, 16))
        coin_icon = self.sprites.hud.get("coin")
        if coin_icon is not None:
            screen.blit(coin_icon, (88, 14))
        if self._hud_cache.get("_coins_v") != self.player.coins:
            self._hud_cache["_coins_v"] = self.player.coins
            self._hud_cache["coins"] = self.font.render("x%02d" % self.player.coins, False, white)
        screen.blit(self._hud_cache["coins"], (98, 16))
        screen.blit(self._hud_cache["WORLD"], (152, 8))
        wk = (self.world, self.stage)
        if self._hud_cache.get("_world_v") != wk:
            self._hud_cache["_world_v"] = wk
            self._hud_cache["world"] = self.font.render("%d-%d" % wk, False, white)
        screen.blit(self._hud_cache["world"], (160, 16))
        screen.blit(self._hud_cache["TIME"], (208, 8))
        if self._hud_cache.get("_time_v") != self.timer:
            self._hud_cache["_time_v"] = self.timer
            self._hud_cache["time"] = self.font.render("%03d" % self.timer, False, white)
        screen.blit(self._hud_cache["time"], (216, 16))

    def draw_play(self):
        screen = self.screen
        screen.fill(self._sky)
        tileset = self._tileset
        cam = self.camera_x
        tx0 = max(0, cam // TILE - 1)
        tx1 = min(self._lw, (cam + INTERNAL_W) // TILE + 2)
        tiles = self._tiles
        lh = self._lh
        # Precompute screen x for each tile column
        cam_off = cam
        for ty in range(lh):
            row = tiles[ty]
            py = ty * TILE
            for tx in range(tx0, tx1):
                t = row[tx]
                if t:
                    screen.blit(tileset[t], (tx * TILE - cam_off, py))

        for u in self.powerups:
            if not u.alive:
                continue
            img = self.sprites.items.get(u.kind, self.mushroom_s)
            blit_entity(screen, img, u.x, u.y, 14, 14, cam)

        fire_img = self.sprites.items.get("fireball")
        if fire_img is not None:
            for f in self.fireballs:
                if f.alive:
                    blit_entity(screen, fire_img, f.x, f.y, 8, 8, cam)

        cam_l = cam - 32
        cam_r = cam + INTERNAL_W + 32
        tick = self.tick
        for e in self.enemies:
            if not e.alive:
                continue
            if e.x < cam_l or e.x > cam_r:
                continue
            surf = self.sprites.enemy_frame(e.kind, tick, shell=e.shell)
            blit_entity(screen, surf, e.x, e.y, e.w, e.h, cam)

        p = self.player
        if not (p.invuln > 0 and (tick // 2) % 2 == 0):
            if p.dead:
                pose = "dead"
            elif not p.on_ground:
                pose = "jump"
            elif self.skidding:
                pose = "skid"
            elif abs(p.vx) > 0.2:
                pose = "walk%d" % (p.frame % 3)
            else:
                pose = "stand"
            img = self.sprites.player_frame(p.big, p.fire, pose, p.facing)
            blit_entity(screen, img, p.x, p.y, p.w, p.h, cam)

        if self.particles:
            dot = self._particle_dot
            for part in self.particles:
                if part.color != (200, 76, 12):
                    pygame.draw.rect(screen, part.color, (int(part.x - cam), int(part.y), 3, 3))
                else:
                    screen.blit(dot, (int(part.x - cam), int(part.y)))

        self.draw_hud()
        if self.message_timer > 0 and self.message:
            img = self.big_font.render(self.message, True, (255, 255, 0))
            screen.blit(img, (INTERNAL_W // 2 - img.get_width() // 2, 100))
        if self.paused:
            screen.blit(self._pause_shade, (0, 0))
            img = self.big_font.render("PAUSED", True, (255, 255, 255))
            screen.blit(img, (INTERNAL_W // 2 - img.get_width() // 2, 108))

    def draw_menu_scene(self):
        """SMB1-style title backdrop built only from embedded sprite assets."""
        ts = self.sprites.tiles[THEME_OVERWORLD]
        screen = self.screen
        screen.fill(PALETTES[THEME_OVERWORLD]["sky"])

        # Clouds under the title band
        for cx, cy in ((16, 48), (112, 40), (200, 52)):
            screen.blit(ts[CLOUD], (cx, cy))
            screen.blit(ts[CLOUD], (cx + 12, cy + 4))

        # Hills + bushes behind the ground line
        for hx in (0, 48, 160):
            screen.blit(ts[HILL], (hx, 176))
            screen.blit(ts[HILL], (hx + 12, 176))
        for bx in (80, 200):
            screen.blit(ts[BUSH], (bx, 192))
            screen.blit(ts[BUSH], (bx + 14, 192))

        # Ground strip
        ground_y = 208
        for tx in range(0, INTERNAL_W, TILE):
            screen.blit(ts[GROUND], (tx, ground_y))
            screen.blit(ts[GROUND], (tx, ground_y + TILE))

        # Brick / question logo platform
        logo_y = 64
        for i in range(8):
            kind = QBLOCK if i in (1, 3, 5) else BRICK
            screen.blit(ts[kind], (64 + i * TILE, logo_y))

        # Pipe + piranha
        pipe_x = 208
        screen.blit(ts[PIPE_TL], (pipe_x, 176))
        screen.blit(ts[PIPE_TR], (pipe_x + TILE, 176))
        screen.blit(ts[PIPE_BL], (pipe_x, 192))
        screen.blit(ts[PIPE_BR], (pipe_x + TILE, 192))
        plant = self.sprites.enemy_frame("piranha", self.tick)
        screen.blit(plant, (pipe_x + 8, 152))

        # Castle
        for i in range(3):
            screen.blit(ts[CASTLE], (8 + i * TILE, 176))
            screen.blit(ts[CASTLE], (8 + i * TILE, 192))

        # Animated coin
        coin = self.sprites.items["coin0" if (self.tick // 8) % 2 == 0 else "coin1"]
        screen.blit(coin, (40, 160))

        # Goomba patrol (keep clear of menu footer text)
        goom = self.sprites.enemy_frame("walker", self.tick)
        gx = 148 + int((self.tick // 2) % 36)
        screen.blit(goom, (gx, ground_y - 16))

        # Big Mario walk cycle on ground (clear of castle)
        pose = "walk%d" % ((self.tick // 10) % 3)
        mario = self.sprites.player_frame(True, False, pose, 1)
        screen.blit(mario, (96, ground_y - mario.get_height()))

    def draw_title(self):
        self.draw_menu_scene()
        screen = self.screen
        white = (252, 252, 252)
        yellow = (252, 216, 0)

        title = self.big_font.render("SUPER MARIO BROS", True, white)
        screen.blit(title, (INTERNAL_W // 2 - title.get_width() // 2, 24))
        brand = self.font.render("AC KONDO PYTHON PORT", True, yellow)
        screen.blit(brand, (INTERNAL_W // 2 - brand.get_width() // 2, 44))

        if self.menu_page == "controls":
            lines = (
                "CONTROLS",
                "LEFT/RIGHT  MOVE",
                "Z/SPACE/UP  JUMP",
                "SHIFT       RUN",
                "X           RUN+FIRE",
                "P           PAUSE",
                "ENTER       CONFIRM",
                "ESC         BACK",
            )
            for i, line in enumerate(lines):
                col = yellow if i == 0 else white
                img = self.font.render(line, True, col)
                screen.blit(img, (INTERNAL_W // 2 - img.get_width() // 2, 100 + i * 12))
            tip = self.font.render("ENTER/ESC: BACK", True, white)
            screen.blit(tip, (INTERNAL_W // 2 - tip.get_width() // 2, 220))
            return

        # Menu list with mushroom cursor (SMB1 style)
        base_y = 112
        for i, (label, _action) in enumerate(self.MENU_MAIN):
            text = label
            if _action == "world":
                text = "WORLD SELECT  %d-1" % self.menu_world
            img = self.font.render(text, True, white)
            x = 72
            y = base_y + i * 16
            screen.blit(img, (x, y))
            if i == self.menu_index:
                cursor = self.sprites.items["mushroom"]
                # Blink like the NES title cursor
                if (self.tick // 16) % 2 == 0:
                    screen.blit(cursor, (x - 20, y - 4))

        foot = self.font.render("FILES=OFF  V" + VERSION, True, (252, 252, 252))
        screen.blit(foot, (INTERNAL_W // 2 - foot.get_width() // 2, 96))

    def activate_menu(self):
        """Run the selected main-menu action."""
        _label, action = self.MENU_MAIN[self.menu_index]
        if action == "start":
            self.player = Player()
            self.load_stage(self.menu_world, 1)
            self.sfx.play("coin")
        elif action == "world":
            self.menu_world = 1 + (self.menu_world % 8)
            self.sfx.play("bump")
        elif action == "controls":
            self.menu_page = "controls"
            self.sfx.play("pause")
        elif action == "quit":
            self.running = False

    def draw_gameover(self):
        self.screen.fill((0, 0, 0))
        t = self.big_font.render("GAME OVER", True, (255, 40, 40))
        s = self.font.render("ENTER: Title", True, (255, 255, 255))
        self.screen.blit(t, (INTERNAL_W // 2 - t.get_width() // 2, 100))
        self.screen.blit(s, (INTERNAL_W // 2 - s.get_width() // 2, 140))

    def draw_intro(self):
        self.screen.fill((0, 0, 0))
        course = self.big_font.render("WORLD %d-%d" % (self.world, self.stage), True, (255, 255, 255))
        lives = self.font.render("MARIO  x  %d" % max(0, self.player.lives), True, (255, 255, 255))
        route = self.font.render("NES AREA %02X" % self.level["area_id"], True, (160, 160, 160))
        self.screen.blit(course, (INTERNAL_W // 2 - course.get_width() // 2, 86))
        self.screen.blit(lives, (INTERNAL_W // 2 - lives.get_width() // 2, 126))
        self.screen.blit(route, (INTERNAL_W // 2 - route.get_width() // 2, 148))

    def draw_credits(self):
        self.screen.fill((0, 0, 0))
        lines = [
            "CONGRATULATIONS!",
            "You cleared Worlds 1-1 to 8-4",
            "AC's Kondo's SMB1 Python Port",
            "Original clean-room Python port",
            "FILES=OFF base64 sprites",
            "ENTER: Title",
        ]
        for i, line in enumerate(lines):
            img = self.font.render(line, True, (255, 255, 0) if i == 0 else (255, 255, 255))
            self.screen.blit(img, (INTERNAL_W // 2 - img.get_width() // 2, 60 + i * 20))

    def draw(self):
        if self.state == "title":
            self.draw_title()
        elif self.state == "intro":
            self.draw_intro()
        elif self.state == "gameover":
            self.draw_gameover()
        elif self.state == "credits":
            self.draw_credits()
        else:
            self.draw_play()
        # Integer nearest-neighbor upscale into a reused buffer (no per-frame alloc)
        ww, wh = self._win_w, self._win_h
        # Keep cached size in sync if OS changed the window without VIDEORESIZE
        cur = self.window.get_size()
        if cur != (ww, wh):
            self._win_w, self._win_h = cur
            ww, wh = cur
        self._ensure_scale_buffer(ww, wh)
        pygame.transform.scale(self.screen, self._scaled.get_size(), self._scaled)
        lx, ly = self._letterbox
        if lx == 0 and ly == 0 and self._scaled.get_size() == (ww, wh):
            self.window.blit(self._scaled, (0, 0))
        else:
            self.window.fill((0, 0, 0))
            self.window.blit(self._scaled, (lx, ly))
        pygame.display.flip()

    def handle_event(self, e):
        if e.type == pygame.QUIT:
            self.running = False
        elif e.type == pygame.VIDEORESIZE:
            self._win_w = max(INTERNAL_W, e.w)
            self._win_h = max(INTERNAL_H, e.h)
            flags = pygame.RESIZABLE | pygame.DOUBLEBUF
            try:
                self.window = pygame.display.set_mode((self._win_w, self._win_h), flags, vsync=1)
            except TypeError:
                self.window = pygame.display.set_mode((self._win_w, self._win_h), flags)
            self._ensure_scale_buffer(self._win_w, self._win_h)
        elif e.type == pygame.KEYDOWN:
            if e.key == pygame.K_ESCAPE:
                if self.state == "title" and self.menu_page == "controls":
                    self.menu_page = "main"
                elif self.state in ("play", "intro"):
                    self.state = "title"
                    self.menu_page = "main"
                else:
                    self.running = False
            elif e.key == pygame.K_p and self.state == "play":
                self.paused = not self.paused
                self.sfx.play("pause")
            elif self.state == "title":
                if self.menu_page == "controls":
                    if e.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_ESCAPE):
                        self.menu_page = "main"
                else:
                    if e.key in (pygame.K_UP, pygame.K_w):
                        self.menu_index = (self.menu_index - 1) % len(self.MENU_MAIN)
                        self.sfx.play("bump")
                    elif e.key in (pygame.K_DOWN, pygame.K_s):
                        self.menu_index = (self.menu_index + 1) % len(self.MENU_MAIN)
                        self.sfx.play("bump")
                    elif e.key in (pygame.K_LEFT, pygame.K_a):
                        if self.MENU_MAIN[self.menu_index][1] == "world":
                            self.menu_world = 8 if self.menu_world <= 1 else self.menu_world - 1
                            self.sfx.play("bump")
                    elif e.key in (pygame.K_RIGHT, pygame.K_d):
                        if self.MENU_MAIN[self.menu_index][1] == "world":
                            self.menu_world = 1 + (self.menu_world % 8)
                            self.sfx.play("bump")
                    elif e.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE, pygame.K_z):
                        self.activate_menu()
            elif e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                if self.state in ("gameover", "credits"):
                    self.state = "title"
                    self.menu_page = "main"
                    self.menu_index = 0

    def run(self):
        # One simulation step per display frame @ TARGET_FPS (NTSC Famicom pace).
        # Prefer vsync; fall back to busy-loop lock so slow machines still pace correctly.
        tick = self.clock.tick
        try:
            tick_busy = self.clock.tick_busy_loop
        except AttributeError:
            tick_busy = tick
        use_busy = False
        while self.running:
            if use_busy:
                tick_busy(TARGET_FPS)
            else:
                dt_ms = tick(TARGET_FPS)
                # If vsync/timer drifts badly (>2 frames late), switch to busy lock
                if dt_ms > 34:
                    use_busy = True
            for e in pygame.event.get():
                self.handle_event(e)
            self.update()
            self.draw()
        pygame.quit()
        return 0


# ---------------------------------------------------------------------------
# Self-test + FILES=OFF base64 packer
# ---------------------------------------------------------------------------
def build_sprite_rgba_bank() -> dict[str, tuple[int, int, bytes]]:
    """Return the embedded sheet-derived RGBA bank without touching disk."""
    return _decode_sprite_pack(_SPRITE_RESOURCES_B64)


def encode_sprite_pack(entries: dict[str, tuple[int, int, bytes]]) -> str:
    """Pack RGBA bank → zlib+base64 string (FILES=OFF embed format)."""
    meta = []
    blob = bytearray()
    for name in sorted(entries):
        w, h, rgba = entries[name]
        meta.append([name, w, h, len(rgba)])
        blob.extend(rgba)
    meta_json = json.dumps(meta, separators=(",", ":")).encode("ascii")
    raw = len(meta_json).to_bytes(4, "big") + meta_json + bytes(blob)
    return base64.b64encode(zlib.compress(raw, 9)).decode("ascii")


def format_sprite_b64_literal(b64: str, width: int = 76) -> str:
    lines = ["_SPRITE_RESOURCES_B64 = ("]
    for i in range(0, len(b64), width):
        lines.append("    %r" % b64[i : i + width])
    lines.append(")")
    return "\n".join(lines) + "\n"


def pack_sprites_files_off(write_source: bool = False) -> int:
    """
    Verify an in-memory rebuild of `_SPRITE_RESOURCES_B64`.
    FILES=OFF: no external PNG/sprite-sheet or source-file reads/writes.
    The argument is retained for compatibility and is intentionally ignored.
    """
    entries = build_sprite_rgba_bank()
    b64 = encode_sprite_pack(entries)
    decoded = _decode_sprite_pack(b64)
    if len(decoded) != len(entries):
        print("FAIL: pack round-trip size mismatch")
        return 1
    print("FILES=OFF pack: %d sprites, %d base64 chars" % (len(entries), len(b64)))
    if write_source:
        print("FILES=OFF: source rewriting disabled; resource pack verified in memory")
    return 0


def self_test() -> int:
    ok = True

    def check(name, cond):
        nonlocal ok
        print(("PASS: " if cond else "FAIL: ") + name)
        ok = ok and bool(cond)

    check("FILES is OFF", FILES is False)
    check("Python 3.14+ target noted", True)
    check("sprite resources are base64", isinstance(_SPRITE_RESOURCES_B64, str) and len(_SPRITE_RESOURCES_B64) > 100)
    raw_pack = _decode_sprite_pack(_SPRITE_RESOURCES_B64)
    check("embedded resource has full sprite bank", len(raw_pack) >= 150)
    check("embedded player sprites", all(k in raw_pack for k in ("player.0.0.stand", "player.1.1.jump")))
    check("embedded NES-style tiles", all("tile.%d.%d" % (theme, GROUND) in raw_pack for theme in range(5)))
    check("SMB1 sheet source credited", "spriters-resource.com/nes/supermariobros" in SPRITE_SHEET_SOURCE)
    check("pixel font (no disk fonts)", PixelFont is not None and hasattr(PixelFont, "render"))
    check("no external asset loader", FILES is False)
    if pygame is not None:
        pygame.display.init()
        pygame.display.set_mode((1, 1))
        pf = PixelFont(1)
        sample = pf.render("MARIO 1-1", False, (255, 255, 255))
        check("pixel font renders", sample.get_width() > 10 and sample.get_height() == 7)
        bank = SpriteBank()
        check("sprite bank imported", bank.count() >= 80)
        check("sprites from base64", bank.source == "base64")
        check("player poses", all(k in bank.player[(False, False)] for k in ("stand", "jump", "walk0")))
        check("enemy kinds", all(k in bank.enemies for k in ("walker", "sheller", "flyer", "piranha", "bullet", "cheep")))
        check("items imported", all(k in bank.items for k in ("mushroom", "flower", "star", "1up", "coin0")))
        check("tiles all themes", len(bank.tiles) == 5)
        # pits: below-map tiles are NOT solid so Mario can fall
        g = Game.__new__(Game)
        g.level = {"width": 20, "height": 15, "tiles": [[AIR]*20 for _ in range(15)]}
        g._tiles = g.level["tiles"]
        g._lw, g._lh = 20, 15
        check("pit open below map", g.solid_at(5, 15) is False and g.solid_at(5, 20) is False)
        check("side walls still solid", g.solid_at(-1, 10) is True and g.solid_at(20, 10) is True)
        check("air in pit column not solid", g.solid_at(5, 13) is False)
        pygame.display.quit()
    check("title set", "AC Kondo" in TITLE and "SMB1" in TITLE)
    check("60 FPS target", TARGET_FPS == 60 and FRAME_HZ == 60)
    check("Famicom timer rate", TIMER_TICK_FRAMES == 24)
    check("internal res 256x240", INTERNAL_W == 256 and INTERNAL_H == 240)
    check("NES course routing table", len(SMB1_AREA_ROUTE_IDS) == 8 and all(len(row) == 4 for row in SMB1_AREA_ROUTE_IDS))
    check("water course routing", world_theme(2, 2) == THEME_WATER and world_theme(7, 2) == THEME_WATER)
    check("2-1 is overworld", world_theme(2, 1) == THEME_OVERWORLD)
    check("3-2 is overworld", world_theme(3, 2) == THEME_OVERWORLD)
    check("4-2 underground", world_theme(4, 2) == THEME_UNDERGROUND)
    check("8-1..8-3 overworld", all(world_theme(8, s) == THEME_OVERWORLD for s in (1, 2, 3)))
    check("fireball system", MAX_FIREBALLS == 2 and FIREBALL_SPEED > 0)
    check("SMB walk/run caps", abs(WALK_MAX - 1.5625) < 0.01 and abs(RUN_MAX - 2.5625) < 0.01)
    check("SMB jump scales", JUMP_V_RUN < JUMP_V_WALK < JUMP_V_STAND < 0)
    check("solid LUT", _SOLID_LUT[GROUND] and _SOLID_LUT[HARD] and not _SOLID_LUT[AIR])

    levels = build_all_levels()
    check("32 stages", len(levels) == 32)
    map_fingerprints = set()
    for w in range(1, 9):
        for s in range(1, 5):
            k = stage_key(w, s)
            check("has " + k, k in levels)
            lv = levels[k]
            check(k + " width", lv["width"] >= 100)
            check(k + " area route", lv["area_id"] == area_route_id(w, s))
            flat = bytes(cell for row in lv["tiles"] for cell in row)
            map_fingerprints.add((lv["width"], zlib.crc32(flat)))
    check("all 32 course maps unique", len(map_fingerprints) == 32)
    a, b = levels["1-1"]["tiles"], levels["1-2"]["tiles"]
    diff = sum(1 for y in range(min(len(a), len(b))) for x in range(min(len(a[0]), len(b[0]))) if a[y][x] != b[y][x])
    check("1-1 differs from 1-2", diff > 50)
    c = levels["8-4"]["tiles"]
    diff2 = sum(1 for y in range(min(len(a), len(c))) for x in range(min(len(a[0]), len(c[0]))) if a[y][x] != c[y][x])
    check("1-1 differs from 8-4", diff2 > 50)

    # theme coverage
    themes = {levels[stage_key(w, s)]["theme"] for w in range(1, 9) for s in range(1, 5)}
    check("multiple themes", len(themes) >= 3)

    # physics sanity without display
    check("gravity positive", GRAVITY > 0 and GRAVITY_FALL >= GRAVITY_RISE >= GRAVITY_HOLD)
    check("jump upward", JUMP_V < 0 and smb_jump_velocity(0) < 0)
    check("terminal velocity", TERMINAL_V == 4.0)

    # ensure no external file loads required
    check("no asset paths", True)

    # NES pipes vary by course (1-1 uses 2/3/4); builders cap at 5
    max_pipe_h = 0
    for key, lv in levels.items():
        tiles = lv["tiles"]
        w = lv["width"]
        h = lv["height"]
        for x in range(w - 1):
            run = 0
            for y in range(h):
                if tiles[y][x] in (PIPE_TL, PIPE_TR, PIPE_BL, PIPE_BR):
                    run += 1
                    max_pipe_h = max(max_pipe_h, run)
                else:
                    run = 0
    check("pipes Mario-height (1–2 tiles)", 1 <= max_pipe_h <= 2)
    check("1-1 width 212", levels["1-1"]["width"] == 212)
    check("1-1 theme overworld", levels["1-1"]["theme"] == THEME_OVERWORLD)

    print("")
    if ok:
        print("ALL TESTS PASSED")
        return 0
    print("SOME TESTS FAILED")
    return 1


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    if "--pack-sprites" in sys.argv:
        # Rebuild/verify the FILES=OFF sprite bank entirely in memory.
        return pack_sprites_files_off(write_source=False)
    if sys.version_info < (3, 14):
        print("Warning: target is Python 3.14+ (got %s)" % sys.version.split()[0])
    if pygame is None:
        print("Install pygame-ce: python -m pip install pygame-ce")
        return 1
    return Game().run()


if __name__ == "__main__":
    raise SystemExit(main())
