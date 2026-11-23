#!/usr/bin/env python3
"""
Generate pure-vector hand-drawn sketchbook SVG assets for itsnang's GitHub Profile README,
matching the wireframe/sketchbook design system of https://lornsamnang.com in both
Light Mode (warm ivory graph paper) and Dark Mode (warm charcoal sketchbook).

Why pure-vector SVG paths for text?
GitHub serves repository SVGs with `Content-Security-Policy: default-src 'none'`,
which blocks `@font-face` (including base64 data URIs) and external `<image>` URLs.
By shaping Caveat Bold + Architects Daughter with HarfBuzz and converting unique glyphs
to deduplicated `<defs>` SVG paths, every browser renders the exact portfolio typography
pixel-perfectly with zero external dependencies.

Usage:
    python3 scripts/generate_assets.py
"""

from __future__ import annotations

import io
import math
import random
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from xml.sax.saxutils import escape as xml_escape

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

ROOT = Path(__file__).resolve().parent.parent
FONTS_DIR = ROOT / "scripts" / "fonts"
ASSETS_DIR = ROOT / "assets"


# ---------------------------------------------------------------------------
# Theme Tokens (Light = exact lornsamnang.com tokens; Dark = charcoal twin)
# ---------------------------------------------------------------------------
THEMES: Dict[str, Dict[str, str]] = {
    "light": {
        "paper": "#fbfaf5",
        "paper2": "#f3f1e8",
        "paper_border": "#e4e0d3",
        "card_border": "#e6e2d5",
        "grid": "#282832",
        "grid_op": "0.055",
        "ink": "#25252a",
        "ink_soft": "#5b5b62",
        "ink_faint": "#a7a59c",
        "line": "#2a2a30",
        "accent": "#e2402c",
        "accent_soft": "#e2402c26",
        "green": "#4a7a5a",
        "green_bg": "#f0f7f2",
        "tape_fill": "#e4d296",
        "tape_op": "0.58",
        "tape_stroke": "#96823c",
        "tape_stroke_op": "0.42",
        "btn_solid_bg": "#25252a",
        "btn_solid_fg": "#fbfaf5",
        "btn_outline_bg": "#fbfaf5",
        "chip_bg": "#f3f1e8",
        "chip_border": "#e3dfd2",
        "pill_bg": "#fbfaf5",
        "quote_mark": "#e2402c55",
        "sketch_fill": "#ebe7da",
    },
    "dark": {
        "paper": "#16161a",
        "paper2": "#1f1f25",
        "paper_border": "#2a2a33",
        "card_border": "#2c2c36",
        "grid": "#fbfaf5",
        "grid_op": "0.045",
        "ink": "#f3f1e8",
        "ink_soft": "#b0aea5",
        "ink_faint": "#6e6c66",
        "line": "#d8d5c9",
        "accent": "#f05a47",
        "accent_soft": "#f05a4733",
        "green": "#6ac489",
        "green_bg": "#18291f",
        "tape_fill": "#d9c47e",
        "tape_op": "0.24",
        "tape_stroke": "#d9c47e",
        "tape_stroke_op": "0.35",
        "btn_solid_bg": "#f3f1e8",
        "btn_solid_fg": "#16161a",
        "btn_outline_bg": "#1f1f25",
        "chip_bg": "#1f1f25",
        "chip_border": "#2f2f39",
        "pill_bg": "#16161a",
        "quote_mark": "#f05a4766",
        "sketch_fill": "#272730",
    },
}


# ---------------------------------------------------------------------------
# Font Shaping & Glyph Path Engine
# ---------------------------------------------------------------------------
class FontFaceData:
    def __init__(self, ttfont: TTFont, raw_ttf_bytes: bytes, prefix: str):
        self.tt = ttfont
        self.prefix = prefix
        self.upem = ttfont["head"].unitsPerEm
        self.glyph_set = ttfont.getGlyphSet()
        self.glyph_order = ttfont.getGlyphOrder()
        self.hb_face = hb.Face(raw_ttf_bytes)
        self.hb_font = hb.Font(self.hb_face)
        self.hb_font.scale = (self.upem, self.upem)
        self._path_cache: Dict[int, str] = {}

    def shape(self, text: str) -> Tuple[List[Tuple[int, int, int, int]], int]:
        """Return list of (gid, x_cursor, x_off, y_off) and total advance in font units."""
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(self.hb_font, buf)
        infos = buf.glyph_infos
        positions = buf.glyph_positions
        out: List[Tuple[int, int, int, int]] = []
        cx = 0
        for info, pos in zip(infos, positions):
            out.append((info.codepoint, cx, pos.x_offset, pos.y_offset))
            cx += pos.x_advance
        return out, cx

    def glyph_svg_path(self, gid: int) -> str:
        if gid not in self._path_cache:
            gname = self.glyph_order[gid]
            pen = SVGPathPen(self.glyph_set)
            self.glyph_set[gname].draw(pen)
            self._path_cache[gid] = pen.getCommands()
        return self._path_cache[gid]


class FontEngine:
    def __init__(self) -> None:
        # Instantiate Caveat Bold (wght=700) to match `.wf-h { font-weight: 700 }`
        caveat_tt = TTFont(str(FONTS_DIR / "caveat.woff2"))
        caveat_bold = instantiateVariableFont(caveat_tt, {"wght": 700})
        caveat_bold.flavor = None
        buf_c = io.BytesIO()
        caveat_bold.save(buf_c)
        self.faces: Dict[str, FontFaceData] = {
            "hand": FontFaceData(TTFont(io.BytesIO(buf_c.getvalue())), buf_c.getvalue(), "h"),
        }

        # Load Architects Daughter (400) to match `.wf-m`
        arch_tt = TTFont(str(FONTS_DIR / "architects-daughter.woff2"))
        arch_tt.flavor = None
        buf_a = io.BytesIO()
        arch_tt.save(buf_a)
        self.faces["marker"] = FontFaceData(TTFont(io.BytesIO(buf_a.getvalue())), buf_a.getvalue(), "m")

    def measure(self, font_key: str, text: str, size: float, letter_spacing: float = 0.0) -> float:
        face = self.faces[font_key]
        shaped, total_adv = face.shape(text)
        scale = size / face.upem
        extra = max(0, len(shaped) - 1) * letter_spacing
        return total_adv * scale + extra

    def wrap(self, font_key: str, text: str, size: float, max_width: float) -> List[str]:
        words = text.split()
        lines: List[str] = []
        cur = ""
        for w in words:
            cand = f"{cur} {w}".strip()
            if cur and self.measure(font_key, cand, size) > max_width:
                lines.append(cur)
                cur = w
            else:
                cur = cand
        if cur:
            lines.append(cur)
        return lines


# ---------------------------------------------------------------------------
# Hand-Drawn SVG Path Helpers
# ---------------------------------------------------------------------------
def fmt(n: float) -> str:
    s = f"{n:.1f}"
    if s.endswith(".0"):
        return s[:-2]
    return s


def sketch_line_path(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    amp: float = 1.0,
    segs: int = 16,
    seed: int = 1,
) -> str:
    rng = random.Random(seed)
    dx = x2 - x1
    dy = y2 - y1
    length = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / length, dx / length
    pts = [(x1, y1)]
    for i in range(1, segs):
        t = i / segs
        off = rng.uniform(-amp, amp)
        pts.append((x1 + dx * t + nx * off, y1 + dy * t + ny * off))
    pts.append((x2, y2))

    d = [f"M{fmt(pts[0][0])},{fmt(pts[0][1])}"]
    for i in range(1, len(pts) - 1):
        mx = (pts[i][0] + pts[i + 1][0]) / 2
        my = (pts[i][1] + pts[i + 1][1]) / 2
        d.append(f"Q{fmt(pts[i][0])},{fmt(pts[i][1])} {fmt(mx)},{fmt(my)}")
    d.append(f"L{fmt(pts[-1][0])},{fmt(pts[-1][1])}")
    return " ".join(d)


def sketch_rect_path(
    x: float,
    y: float,
    w: float,
    h: float,
    amp: float = 0.85,
    seed: int = 11,
) -> str:
    """Closed subtle hand-drawn rectangular path (4 slightly organic edges)."""
    rng = random.Random(seed)

    def edge(ax: float, ay: float, bx: float, by: float, segs: int) -> List[Tuple[float, float]]:
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / length, dx / length
        pts = []
        for i in range(1, segs):
            t = i / segs
            off = rng.uniform(-amp, amp)
            pts.append((ax + dx * t + nx * off, ay + dy * t + ny * off))
        return pts

    corners = [
        (x + rng.uniform(-0.4, 0.4), y + rng.uniform(-0.4, 0.4)),
        (x + w + rng.uniform(-0.4, 0.4), y + rng.uniform(-0.4, 0.4)),
        (x + w + rng.uniform(-0.4, 0.4), y + h + rng.uniform(-0.4, 0.4)),
        (x + rng.uniform(-0.4, 0.4), y + h + rng.uniform(-0.4, 0.4)),
    ]
    segs_h = max(3, int(w / 45))
    segs_v = max(2, int(h / 45))
    all_pts: List[Tuple[float, float]] = [corners[0]]
    all_pts.extend(edge(*corners[0], *corners[1], segs_h))
    all_pts.append(corners[1])
    all_pts.extend(edge(*corners[1], *corners[2], segs_v))
    all_pts.append(corners[2])
    all_pts.extend(edge(*corners[2], *corners[3], segs_h))
    all_pts.append(corners[3])
    all_pts.extend(edge(*corners[3], *corners[0], segs_v))

    d = [f"M{fmt(all_pts[0][0])},{fmt(all_pts[0][1])}"]
    for px, py in all_pts[1:]:
        d.append(f"L{fmt(px)},{fmt(py)}")
    d.append("Z")
    return " ".join(d)


# ---------------------------------------------------------------------------
# SVG Document Builder with Deduplicated Glyph Definitions
# ---------------------------------------------------------------------------
class SvgDoc:
    def __init__(self, width: float, height: float, fonts: FontEngine, title: str = ""):
        self.w = width
        self.h = height
        self.fonts = fonts
        self.title = title
        self.defs: List[str] = []
        self.body: List[str] = []
        self._glyph_ids: Dict[Tuple[str, int], str] = {}

    def add_def(self, snippet: str) -> None:
        self.defs.append(snippet)

    def add(self, snippet: str) -> None:
        self.body.append(snippet)

    def add_graph_paper_bg(self, t: Dict[str, str], rx: float = 10, border: bool = True) -> None:
        self.add_def(
            f'<pattern id="wf-grid" width="26" height="26" patternUnits="userSpaceOnUse">'
            f'<path d="M 26 0 L 0 0 0 26" fill="none" stroke="{t["grid"]}" stroke-opacity="{t["grid_op"]}" stroke-width="1"/>'
            f"</pattern>"
        )
        stroke_attr = f' stroke="{t["paper_border"]}" stroke-width="1.2"' if border else ""
        self.add(
            f'<rect x="0.6" y="0.6" width="{fmt(self.w - 1.2)}" height="{fmt(self.h - 1.2)}" '
            f'rx="{fmt(rx)}" fill="{t["paper"]}"/>'
        )
        self.add(
            f'<rect x="0.6" y="0.6" width="{fmt(self.w - 1.2)}" height="{fmt(self.h - 1.2)}" '
            f'rx="{fmt(rx)}" fill="url(#wf-grid)"{stroke_attr}/>'
        )

    def add_divider(self, x1: float, y: float, x2: float, t: Dict[str, str], seed: int = 7) -> None:
        path = sketch_line_path(x1, y, x2, y, amp=0.95, segs=28, seed=seed)
        self.add(
            f'<path d="{path}" fill="none" stroke="{t["line"]}" stroke-opacity="0.55" '
            f'stroke-width="1.7" stroke-linecap="round"/>'
        )

    def add_tape(self, cx: float, cy: float, w: float, h: float, angle: float, t: Dict[str, str]) -> None:
        self.add(
            f'<g transform="translate({fmt(cx)},{fmt(cy)}) rotate({fmt(angle)})">'
            f'<rect x="{fmt(-w / 2)}" y="{fmt(-h / 2)}" width="{fmt(w)}" height="{fmt(h)}" '
            f'fill="{t["tape_fill"]}" fill-opacity="{t["tape_op"]}" '
            f'stroke="{t["tape_stroke"]}" stroke-opacity="{t["tape_stroke_op"]}" stroke-width="1"/>'
            f"</g>"
        )

    def text(
        self,
        font_key: str,
        content: str,
        x: float,
        y: float,
        size: float,
        fill: str,
        align: str = "left",
        letter_spacing: float = 0.0,
        rotate: Optional[float] = None,
        opacity: Optional[float] = None,
    ) -> float:
        """Render text as deduplicated `<use>` glyph paths. Returns rendered width."""
        face = self.fonts.faces[font_key]
        shaped, total_adv = face.shape(content)
        scale = size / face.upem
        extra_per_char = letter_spacing / scale if letter_spacing else 0.0
        width_px = total_adv * scale + max(0, len(shaped) - 1) * letter_spacing

        draw_x = x
        if align == "center":
            draw_x = x - width_px / 2
        elif align == "right":
            draw_x = x - width_px

        uses: List[str] = []
        for idx, (gid, cx, x_off, y_off) in enumerate(shaped):
            path_d = face.glyph_svg_path(gid)
            if not path_d:
                continue
            key = (font_key, gid)
            if key not in self._glyph_ids:
                sym_id = f"{face.prefix}{len(self._glyph_ids)}"
                self._glyph_ids[key] = sym_id
                self.add_def(f'<path id="{sym_id}" d="{path_d}"/>')
            sym_id = self._glyph_ids[key]
            gx = cx + x_off + idx * extra_per_char
            gy = y_off
            attrs = f'href="#{sym_id}"'
            if abs(gx) > 0.1:
                attrs += f' x="{fmt(gx)}"'
            if abs(gy) > 0.1:
                attrs += f' y="{fmt(gy)}"'
            uses.append(f"<use {attrs}/>")

        if not uses:
            return width_px

        tf = f"translate({fmt(draw_x)},{fmt(y)})"
        if rotate is not None:
            tf = f"translate({fmt(draw_x)},{fmt(y)}) rotate({fmt(rotate)})"
        tf += f" scale({scale:.5f},{-scale:.5f})"
        op_attr = f' opacity="{opacity}"' if opacity is not None else ""
        self.add(f'<g fill="{fill}"{op_attr} transform="{tf}">{"".join(uses)}</g>')
        return width_px

    def render(self) -> str:
        safe_title = xml_escape(self.title, {'"': "&quot;"})
        title_el = f"<title>{safe_title}</title>" if safe_title else ""
        defs_el = f"<defs>{''.join(self.defs)}</defs>" if self.defs else ""
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{fmt(self.w)}" height="{fmt(self.h)}" '
            f'viewBox="0 0 {fmt(self.w)} {fmt(self.h)}" role="img" aria-label="{safe_title}">'
            f"{title_el}{defs_el}{''.join(self.body)}</svg>"
        )


# ---------------------------------------------------------------------------
# Hand-Drawn Decorative & UI Icons (Pure Vector, CSP-safe)
# ---------------------------------------------------------------------------
def draw_arrow_right(x: float, y: float, color: str, size: float = 12) -> str:
    s = size / 14.0
    return (
        f'<g transform="translate({fmt(x)},{fmt(y)}) scale({s:.3f})" '
        f'fill="none" stroke="{color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
        f'<path d="M1,7 C5,6.5 9,7.2 13,7"/><path d="M9,3.2 L13.2,7 L9,10.8"/></g>'
    )


def draw_arrow_ne(x: float, y: float, color: str, size: float = 11) -> str:
    s = size / 14.0
    return (
        f'<g transform="translate({fmt(x)},{fmt(y)}) scale({s:.3f})" '
        f'fill="none" stroke="{color}" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">'
        f'<path d="M3,11 L11,3"/><path d="M5,3 L11,3 L11,9"/></g>'
    )


def draw_spark(cx: float, cy: float, color: str, r: float = 5.5) -> str:
    return (
        f'<path d="M{fmt(cx)},{fmt(cy - r)} Q{fmt(cx)},{fmt(cy)} {fmt(cx + r)},{fmt(cy)} '
        f'Q{fmt(cx)},{fmt(cy)} {fmt(cx)},{fmt(cy + r)} '
        f'Q{fmt(cx)},{fmt(cy)} {fmt(cx - r)},{fmt(cy)} '
        f'Q{fmt(cx)},{fmt(cy)} {fmt(cx)},{fmt(cy - r)} Z" fill="{color}"/>'
    )


def draw_wave_hand(x: float, y: float, stroke: str, accent: str, size: float = 15) -> str:
    """Minimalist hand-drawn waving hand icon matching `say hi`."""
    s = size / 20.0
    return (
        f'<g transform="translate({fmt(x)},{fmt(y)}) scale({s:.3f})" '
        f'fill="none" stroke-linecap="round" stroke-linejoin="round">'
        f'<path d="M6.2,11.2 L4.4,6.4 C4.1,5.6 5.2,5.1 5.8,5.8 L8.1,9.4 '
        f'L7.1,4.2 C6.9,3.3 8.2,3.0 8.6,3.9 L10.2,8.8 '
        f'L10.3,3.7 C10.3,2.8 11.7,2.8 11.8,3.7 L12.2,9.0 '
        f'L13.6,5.2 C13.9,4.4 15.1,4.8 14.9,5.7 L13.8,11.5 '
        f'C13.6,14.8 11.5,17.2 8.7,17.2 C6.5,17.2 5.0,15.8 4.4,13.8 L3.2,10.7 '
        f'C2.9,9.9 4.0,9.3 4.6,10.0 Z" fill="#f7cf68" stroke="{stroke}" stroke-width="1.35"/>'
        f'<path d="M15.8,3.2 C17.1,4.0 17.8,5.3 17.9,6.7" stroke="{accent}" stroke-width="1.4"/>'
        f'<path d="M1.7,5.4 C1.5,6.5 1.7,7.6 2.2,8.5" stroke="{accent}" stroke-width="1.4"/>'
        f"</g>"
    )


def draw_pin_icon(x: float, y: float, color: str) -> str:
    return (
        f'<g transform="translate({fmt(x)},{fmt(y)}) scale(0.62)" fill="none" stroke="{color}" '
        f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        f'<path d="M12 21s-7-5.5-7-11a7 7 0 0 1 14 0c0 5.5-7 11-7 11z"/>'
        f'<circle cx="12" cy="10" r="2.5"/></g>'
    )


def draw_mail_icon(x: float, y: float, color: str) -> str:
    return (
        f'<g transform="translate({fmt(x)},{fmt(y)}) scale(0.62)" fill="none" stroke="{color}" '
        f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        f'<rect x="2" y="4" width="20" height="16" rx="2"/>'
        f'<path d="m22 7-8.99 5.73a2 2 0 0 1-2.02 0L2 7"/></g>'
    )


def draw_link_icon(x: float, y: float, color: str) -> str:
    return (
        f'<g transform="translate({fmt(x)},{fmt(y)}) scale(0.62)" fill="none" stroke="{color}" '
        f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        f'<path d="M10 14a4 4 0 0 0 5.6 0l3-3a4 4 0 0 0-5.6-5.6l-1.5 1.5"/>'
        f'<path d="M14 10a4 4 0 0 0-5.6 0l-3 3a4 4 0 0 0 5.6 5.6l1.5-1.5"/></g>'
    )


def draw_social_icon(kind: str, x: float, y: float, t: Dict[str, str]) -> str:
    if kind == "web":
        return draw_link_icon(x, y, t["ink"])
    if kind == "email":
        return draw_mail_icon(x, y, t["ink"])
    if kind == "linkedin":
        return (
            f'<g transform="translate({fmt(x)},{fmt(y)})">'
            f'<rect x="0" y="0" width="15" height="15" rx="3" fill="#0a66c2"/>'
            f'<circle cx="4.3" cy="4.4" r="1.15" fill="#fff"/>'
            f'<rect x="3.3" y="6.5" width="2" height="5.5" fill="#fff"/>'
            f'<path d="M7.1,6.5 H8.9 V7.4 C9.3,6.7 10.1,6.3 11.0,6.3 C12.4,6.3 13.0,7.2 13.0,8.8 V12 H11.0 V9.1 '
            f'C11.0,8.3 10.7,7.9 10.0,7.9 C9.3,7.9 9.0,8.4 9.0,9.1 V12 H7.1 Z" fill="#fff"/></g>'
        )
    if kind == "telegram":
        return (
            f'<g transform="translate({fmt(x)},{fmt(y)})">'
            f'<circle cx="7.5" cy="7.5" r="7.5" fill="#26a5e4"/>'
            f'<path d="M3.4,7.4 L11.4,4.3 L10.1,11.1 L7.4,9.1 L6.1,10.3 L6.3,8.3 L10.0,5.2 L5.3,7.9 Z" fill="#fff"/></g>'
        )
    if kind == "instagram":
        return (
            f'<g transform="translate({fmt(x)},{fmt(y)})">'
            f'<rect x="0" y="0" width="15" height="15" rx="4" fill="#e1306c"/>'
            f'<rect x="2.6" y="2.6" width="9.8" height="9.8" rx="2.7" fill="none" stroke="#fff" stroke-width="1.35"/>'
            f'<circle cx="7.5" cy="7.5" r="2.3" fill="none" stroke="#fff" stroke-width="1.35"/>'
            f'<circle cx="10.6" cy="4.4" r="0.85" fill="#fff"/></g>'
        )
    return ""


# ---------------------------------------------------------------------------
# Pure-Vector Tech Stack Brand Icons (16×16 box)
# ---------------------------------------------------------------------------
def draw_tech_icon(name: str, x: float, y: float, t: Dict[str, str], dark: bool) -> str:
    g = f'<g transform="translate({fmt(x)},{fmt(y)})">'
    end = "</g>"
    mono = "#f3f1e8" if dark else "#25252a"
    inv = "#16161a" if dark else "#ffffff"

    if name == "ReactJS":
        return (
            g
            + '<circle cx="8" cy="8" r="1.7" fill="#00b4d8"/>'
            + '<ellipse cx="8" cy="8" rx="7" ry="2.7" fill="none" stroke="#00b4d8" stroke-width="1.2"/>'
            + '<ellipse cx="8" cy="8" rx="7" ry="2.7" fill="none" stroke="#00b4d8" stroke-width="1.2" transform="rotate(60 8 8)"/>'
            + '<ellipse cx="8" cy="8" rx="7" ry="2.7" fill="none" stroke="#00b4d8" stroke-width="1.2" transform="rotate(120 8 8)"/>'
            + end
        )
    if name == "Next.js":
        return (
            g
            + f'<circle cx="8" cy="8" r="7.2" fill="{mono}"/>'
            + f'<path d="M5.2,11.3 V4.8 L11.7,12.6" fill="none" stroke="{inv}" stroke-width="1.45" stroke-linecap="round" stroke-linejoin="round"/>'
            + f'<line x1="10.7" y1="4.8" x2="10.7" y2="9.2" stroke="{inv}" stroke-width="1.45" stroke-linecap="round"/>'
            + end
        )
    if name == "Vue.js":
        return (
            g
            + '<polygon points="1,2.5 8,14.5 15,2.5 12.2,2.5 8,9.8 3.8,2.5" fill="#41b883"/>'
            + '<polygon points="3.8,2.5 8,9.8 12.2,2.5 9.8,2.5 8,5.7 6.2,2.5" fill="#35495e"/>'
            + end
        )
    if name == "Tailwind CSS":
        return (
            g
            + '<path d="M4.2,6.8 C4.9,4.5 6.5,3.8 8.2,4.3 C9.3,4.6 9.9,5.5 10.8,5.9 C11.8,6.3 12.8,6.0 13.7,4.9 '
            + 'C13.0,7.2 11.4,7.9 9.7,7.4 C8.6,7.1 8.0,6.2 7.1,5.8 C6.1,5.4 5.1,5.7 4.2,6.8 Z" fill="#38bdf8"/>'
            + '<path d="M1.8,11.1 C2.5,8.8 4.1,8.1 5.8,8.6 C6.9,8.9 7.5,9.8 8.4,10.2 C9.4,10.6 10.4,10.3 11.3,9.2 '
            + 'C10.6,11.5 9.0,12.2 7.3,11.7 C6.2,11.4 5.6,10.5 4.7,10.1 C3.7,9.7 2.7,10.0 1.8,11.1 Z" fill="#38bdf8"/>'
            + end
        )
    if name == "TypeScript":
        return (
            g
            + '<rect x="1" y="1" width="14" height="14" rx="2.4" fill="#3178c6"/>'
            + '<path d="M3.6,6.8 H8.2 M5.9,6.8 V12.5" stroke="#fff" stroke-width="1.5" stroke-linecap="round"/>'
            + '<path d="M12.5,7.3 C11.9,6.7 10.3,6.6 9.8,7.4 C9.3,8.2 10.1,8.8 11.2,9.2 C12.4,9.6 12.9,10.3 12.4,11.4 C11.9,12.5 10.1,12.5 9.3,11.7" '
            + 'fill="none" stroke="#fff" stroke-width="1.45" stroke-linecap="round"/>'
            + end
        )
    if name == "TanStack Query":
        return (
            g
            + '<circle cx="8" cy="8" r="7" fill="#fef3c7" stroke="#f59e0b" stroke-width="1"/>'
            + '<path d="M2.2,11.2 Q8,8.8 13.8,11.2 A6.5,6.5 0 0 1 2.2,11.2 Z" fill="#10b981"/>'
            + '<circle cx="11.2" cy="5.4" r="2.1" fill="#ef4444"/>'
            + '<path d="M6.2,10.8 C6.0,8.2 6.6,6.2 7.5,5.0" stroke="#92400e" stroke-width="1.3" stroke-linecap="round" fill="none"/>'
            + '<path d="M7.5,5.0 C5.6,4.2 4.1,4.8 3.6,6.0 M7.5,5.0 C8.2,3.4 9.7,3.4 10.4,4.4 M7.5,5.0 C6.2,3.4 4.8,3.2 4.0,3.8" '
            + 'stroke="#15803d" stroke-width="1.2" stroke-linecap="round" fill="none"/>'
            + end
        )
    if name == "Express.js":
        return (
            g
            + f'<path d="M1.4,8.6 H7.0 C7.0,6.3 5.7,5.2 4.2,5.2 C2.4,5.2 1.4,6.6 1.4,8.6 C1.4,10.6 2.6,11.8 4.4,11.8 C5.5,11.8 6.3,11.3 6.8,10.6" '
            + f'fill="none" stroke="{mono}" stroke-width="1.35" stroke-linecap="round" stroke-linejoin="round"/>'
            + f'<path d="M9.0,5.5 L14.4,11.6 M14.4,5.5 L9.0,11.6" stroke="{mono}" stroke-width="1.35" stroke-linecap="round"/>'
            + end
        )
    if name == "NestJS":
        return (
            g
            + '<path d="M3.2,3.0 L6.0,5.4 C7.3,4.9 8.7,4.9 10.0,5.4 L12.8,3.0 L13.4,7.4 C13.8,10.8 11.4,14.2 8.0,14.6 '
            + 'C4.6,14.2 2.2,10.8 2.6,7.4 Z" fill="#e0234e"/>'
            + '<circle cx="5.9" cy="8.5" r="1.0" fill="#fff"/>'
            + '<circle cx="10.1" cy="8.5" r="1.0" fill="#fff"/>'
            + '<polygon points="8,9.8 6.9,11.2 9.1,11.2" fill="#fff"/>'
            + end
        )
    if name == "Serverless":
        return (
            g
            + '<rect x="1" y="1.5" width="14" height="13" rx="2.2" fill="#1e1e24"/>'
            + '<path d="M3,5.2 H6.6 L5.6,7.1 H3 Z M3,8.5 H5.0 L4.0,10.4 H3 Z M8.5,5.2 H13 V7.1 H7.5 Z M6.9,8.5 H13 V10.4 H5.9 Z" fill="#fd5750"/>'
            + end
        )
    if name == "Node.js":
        return (
            g
            + '<polygon points="8,1.2 14,4.6 14,11.4 8,14.8 2,11.4 2,4.6" fill="#539e43"/>'
            + '<path d="M6.0,10.6 V5.6 L10.0,10.6 V5.6" fill="none" stroke="#fff" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>'
            + end
        )
    if name == "Docker":
        return (
            g
            + '<rect x="3.2" y="5.6" width="2.1" height="1.9" rx="0.3" fill="#2496ed"/>'
            + '<rect x="5.7" y="5.6" width="2.1" height="1.9" rx="0.3" fill="#2496ed"/>'
            + '<rect x="8.2" y="5.6" width="2.1" height="1.9" rx="0.3" fill="#2496ed"/>'
            + '<rect x="5.7" y="3.3" width="2.1" height="1.9" rx="0.3" fill="#2496ed"/>'
            + '<rect x="8.2" y="3.3" width="2.1" height="1.9" rx="0.3" fill="#2496ed"/>'
            + '<path d="M1.4,8.4 H12.4 C13.2,8.4 13.7,7.6 14.3,7.3 C15.0,8.2 14.7,9.7 13.6,10.4 '
            + 'C12.3,12.7 9.6,13.6 6.6,13.6 C3.2,13.6 1.2,11.4 1.4,8.4 Z" fill="#2496ed"/>'
            + '<circle cx="4.3" cy="10.4" r="0.7" fill="#fff"/>'
            + end
        )
    if name == "GraphQL":
        return (
            g
            + '<polygon points="8,2 13.2,5 13.2,11 8,14 2.8,11 2.8,5" fill="none" stroke="#e10098" stroke-width="1.15"/>'
            + '<polygon points="8,2 13.2,11 2.8,11" fill="none" stroke="#e10098" stroke-width="1.15"/>'
            + '<circle cx="8" cy="2" r="1.4" fill="#e10098"/><circle cx="13.2" cy="5" r="1.4" fill="#e10098"/>'
            + '<circle cx="13.2" cy="11" r="1.4" fill="#e10098"/><circle cx="8" cy="14" r="1.4" fill="#e10098"/>'
            + '<circle cx="2.8" cy="11" r="1.4" fill="#e10098"/><circle cx="2.8" cy="5" r="1.4" fill="#e10098"/>'
            + end
        )
    if name == "Flutter":
        return (
            g
            + '<polygon points="9.2,1.5 2.4,8.3 4.6,10.5 13.6,1.5" fill="#54c5f8"/>'
            + '<polygon points="9.2,7.6 5.6,11.2 9.2,14.8 13.6,14.8 9.9,11.1 13.6,7.6" fill="#01579b"/>'
            + '<polygon points="9.2,7.6 5.6,11.2 7.8,13.4 13.6,7.6" fill="#29b6f6"/>'
            + end
        )
    if name == "Dart":
        return (
            g
            + '<polygon points="4.0,4.0 11.2,4.0 14.5,7.3 14.5,12.5 12.2,12.5 4.0,4.3" fill="#00b4ab"/>'
            + '<polygon points="4.0,4.0 1.8,7.4 4.0,11.8 10.5,14.2 12.2,12.5 4.0,4.3" fill="#0175c2"/>'
            + '<polygon points="4.0,4.0 11.2,4.0 12.2,12.5 4.0,11.8" fill="#13b9fd"/>'
            + end
        )
    if name == "GetX":
        return (
            g
            + '<path d="M3,3 L13,13 M13,3 L3,13" stroke="#8b5cf6" stroke-width="2.4" stroke-linecap="round"/>'
            + '<circle cx="8" cy="8" r="2.2" fill="#c084fc"/>'
            + end
        )
    if name == "Bloc":
        return (
            g
            + '<polygon points="8,1.5 14,4.8 8,8.2 2,4.8" fill="#38bdf8"/>'
            + '<polygon points="2,4.8 8,8.2 8,14.6 2,11.2" fill="#0284c7"/>'
            + '<polygon points="14,4.8 8,8.2 8,14.6 14,11.2" fill="#0369a1"/>'
            + end
        )
    if name == "PostgreSQL":
        return (
            g
            + '<path d="M4.5,4.2 C6.2,2.2 10.6,2.2 12.2,4.5 C13.5,6.4 13.2,10.2 11.4,11.8 C10.4,12.7 9.6,12.4 9.5,13.9 '
            + 'C9.4,14.6 8.3,14.6 8.1,13.6 C7.9,12.4 7.7,11.3 6.6,11.1 C4.3,10.7 2.8,8.8 3.2,6.4 C3.4,5.4 3.9,4.7 4.5,4.2 Z" fill="#336791"/>'
            + '<circle cx="6.8" cy="6.6" r="0.9" fill="#fff"/>'
            + '<path d="M9.8,7.4 C10.8,8.2 11.0,9.8 10.1,10.8" fill="none" stroke="#fff" stroke-width="1.1" stroke-linecap="round"/>'
            + end
        )
    if name == "MongoDB":
        return (
            g
            + '<path d="M8,1.4 C5.4,4.2 4.3,7.2 4.9,10.1 C5.4,12.0 6.8,13.2 8,13.8 C9.2,13.2 10.6,12.0 11.1,10.1 C11.7,7.2 10.6,4.2 8,1.4 Z" fill="#47a248"/>'
            + '<path d="M8,3.6 V14.8" stroke="#c8f2c8" stroke-width="1.1" stroke-linecap="round"/>'
            + end
        )
    if name == "MySQL":
        return (
            g
            + '<ellipse cx="8" cy="4.2" rx="5.6" ry="2.2" fill="#00758f"/>'
            + '<path d="M2.4,4.2 V11.5 C2.4,12.8 4.9,13.8 8,13.8 C11.1,13.8 13.6,12.8 13.6,11.5 V4.2" fill="none" stroke="#00758f" stroke-width="1.5"/>'
            + '<path d="M2.4,7.9 C2.4,9.1 4.9,10.1 8,10.1 C11.1,10.1 13.6,9.1 13.6,7.9" fill="none" stroke="#f29111" stroke-width="1.4"/>'
            + end
        )
    return ""


# ---------------------------------------------------------------------------
# Company Badges (36×36, faithful to lornsamnang.com Experience section)
# ---------------------------------------------------------------------------
def draw_company_badge(kind: str, x: float, y: float, t: Dict[str, str]) -> str:
    g = f'<g transform="translate({fmt(x)},{fmt(y)})">'
    end = "</g>"
    if kind == "dichi":
        return (
            g
            + '<rect x="0" y="0" width="36" height="36" rx="6" fill="#d61f2c"/>'
            + '<path d="M11.5,9.5 H18.5 C23.2,9.5 26.0,12.7 26.0,18.0 C26.0,23.3 23.2,26.5 18.5,26.5 H11.5 Z" '
            + 'fill="none" stroke="#fff" stroke-width="2.6" stroke-linejoin="round"/>'
            + '<circle cx="17.5" cy="18" r="2.2" fill="#fff"/>'
            + end
        )
    if kind == "cellcard":
        return (
            g
            + '<rect x="0" y="0" width="36" height="36" rx="6" fill="#f59e0b"/>'
            + '<path d="M10.5,25.5 A15,15 0 0 1 25.5,10.5" fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round"/>'
            + '<path d="M15.5,25.5 A10,10 0 0 1 25.5,15.5" fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round"/>'
            + '<circle cx="23.2" cy="23.2" r="2.4" fill="#fff"/>'
            + end
        )
    if kind == "pethstrey":
        return (
            g
            + f'<rect x="0" y="0" width="36" height="36" rx="6" fill="{t["paper"]}" stroke="{t["card_border"]}" stroke-width="1.2"/>'
            + '<path d="M18,26 C18,26 10,21.2 10,15.3 C10,12.5 12.2,10.6 14.7,10.6 C16.3,10.6 17.4,11.4 18,12.5 '
            + 'C18.6,11.4 19.7,10.6 21.3,10.6 C23.8,10.6 26,12.5 26,15.3 C26,21.2 18,26 18,26 Z" '
            + 'fill="none" stroke="#ec4899" stroke-width="2.1" stroke-linejoin="round"/>'
            + '<path d="M18,15.3 V21.0 M15.2,18.2 H20.8" stroke="#0d9488" stroke-width="2" stroke-linecap="round"/>'
            + end
        )
    if kind == "prutteka":
        return (
            g
            + f'<rect x="0" y="0" width="36" height="36" rx="6" fill="{t["paper"]}" stroke="{t["card_border"]}" stroke-width="1.2"/>'
            + '<path d="M6,12.5 Q18,16 30,12.5" fill="none" stroke="#5b5b62" stroke-width="1.3"/>'
            + '<polygon points="7.5,13 13.5,14.2 10.2,21.5" fill="#ef4444"/>'
            + '<polygon points="15,14.4 21,14.4 18,22.2" fill="#f59e0b"/>'
            + '<polygon points="22.5,14.2 28.5,13 25.8,21.5" fill="#3b82f6"/>'
            + end
        )
    return ""


# ---------------------------------------------------------------------------
# Section Generators
# ---------------------------------------------------------------------------
def build_hero(fonts: FontEngine, theme_name: str) -> str:
    t = THEMES[theme_name]
    W, H = 860, 326
    doc = SvgDoc(W, H, fonts, "Lorn Samnang — Software Developer")
    doc.add_graph_paper_bg(t, rx=10)

    # --- LEFT COLUMN ---
    lx = 42

    # Dashed green `● available for work` pill
    pill_text = "available for work"
    tw = fonts.measure("marker", pill_text, 11.5, letter_spacing=0.4)
    pw = tw + 30
    doc.add(
        f'<rect x="{lx}" y="30" width="{fmt(pw)}" height="24" '
        f'fill="{t["green_bg"]}" stroke="{t["green"]}" stroke-width="1.4" stroke-dasharray="4 3"/>'
    )
    doc.add(f'<circle cx="{lx + 11}" cy="42" r="3.4" fill="{t["green"]}"/>')
    doc.text("marker", pill_text, lx + 20, 46, 11.5, t["green"], letter_spacing=0.4)

    # Eyebrow: `// HELLO WORLD, THIS IS`
    doc.text("marker", "// HELLO WORLD, THIS IS", lx, 80, 10.5, t["ink_soft"], letter_spacing=1.3)

    # Giant Caveat Bold Name: `Lorn Samnang`
    doc.text("hand", "Lorn Samnang", lx, 144, 62, t["ink"])

    # Subtitle: `“Software Developer”` + iconic vermilion red squiggle underline
    sub = '“Software Developer”'
    sub_w = doc.text("marker", sub, lx, 178, 19.5, t["ink_soft"])
    ux, uy = lx - 2, 185
    sx = (sub_w + 8) / 220.0
    doc.add(
        f'<path d="M{fmt(ux + 3 * sx)},{fmt(uy + 6)} '
        f'C{fmt(ux + 70 * sx)},{fmt(uy + 0.5)} {fmt(ux + 160 * sx)},{fmt(uy + 10)} {fmt(ux + 217 * sx)},{fmt(uy + 3.5)}" '
        f'fill="none" stroke="{t["accent"]}" stroke-width="2.6" stroke-linecap="round"/>'
    )

    # Bio paragraph (exact text from lornsamnang.com!)
    bio = (
        "Hi, I'm Samnang — you can call me Chhay. An introverted Software Developer "
        "passionate about building real-world projects that improve quality of life. "
        "Currently based in Phnom Penh, Cambodia."
    )
    lines = fonts.wrap("marker", bio, 13.5, 456)
    by = 224
    for line in lines:
        doc.text("marker", line, lx, by, 13.5, t["ink_soft"])
        by += 22

    # --- RIGHT COLUMN: Taped Hand-Drawn Profile Sketch Card ---
    # Tilted vermilion red margin note + curved hand-drawn arrow
    doc.text("marker", "drawn by hand,", 466, 41, 12, t["accent"], rotate=-4.2)
    b_w = doc.text("marker", "built to ship", 470, 56, 12, t["accent"], rotate=-4.2)
    doc.add(draw_spark(470 + b_w + 8, 47, t["accent"], r=4.4))
    doc.add(
        f'<g fill="none" stroke="{t["accent"]}" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round">'
        f'<path d="M558,54 C584,54 598,63 603,80"/>'
        f'<path d="M596,75 L603,81 L608,73"/>'
        f"</g>"
    )

    # Taped sketch notebook card (`#f3f1e8`)
    cx, cy, cw, ch = 548, 72, 272, 218
    doc.add(f'<rect x="{cx + 4}" y="{cy + 4}" width="{cw}" height="{ch}" rx="3" fill="{t["ink"]}" fill-opacity="0.06"/>')
    frame_path = sketch_rect_path(cx, cy, cw, ch, amp=0.9, seed=42)
    doc.add(f'<path d="{frame_path}" fill="{t["paper2"]}" stroke="{t["line"]}" stroke-width="1.7"/>')
    doc.add_tape(cx + cw / 2, cy + 1, 64, 20, -3.5, t)

    # Inside `profile.sketch` card
    doc.text("marker", "// PROFILE.SKETCH", cx + 18, cy + 32, 10, t["ink_soft"], letter_spacing=1.1)
    doc.add(f'<circle cx="{cx + cw - 20}" cy="{cy + 28}" r="3.5" fill="{t["accent"]}"/>')
    doc.add(
        f'<path d="{sketch_line_path(cx + 16, cy + 43, cx + cw - 16, cy + 43, amp=0.6, segs=10, seed=43)}" '
        f'fill="none" stroke="{t["line"]}" stroke-opacity="0.35" stroke-width="1.2"/>'
    )

    rows = [
        ("role", "Full Stack & Mobile"),
        ("based", "Phnom Penh, Cambodia"),
        ("stack", "Next.js · NestJS · Flutter"),
        ("study", "BSc CS @ RUPP"),
        ("site", "lornsamnang.com"),
    ]
    ry = cy + 68
    for label, val in rows:
        doc.text("marker", f"{label}:", cx + 18, ry, 11.5, t["accent"])
        doc.text("marker", val, cx + 68, ry, 12.2, t["ink"])
        ry += 28

    doc.text("marker", "always shipping", cx + cw - 18, cy + ch - 12, 10, t["ink_faint"], align="right", rotate=-1.5)
    return doc.render()


def build_button(
    fonts: FontEngine,
    theme_name: str,
    label: str,
    solid: bool,
    icon_kind: str,
    seed: int,
) -> str:
    t = THEMES[theme_name]
    tw = fonts.measure("marker", label, 14)
    icon_w = 22 if icon_kind else 0
    W = round(tw + icon_w + 42)
    H = 40
    doc = SvgDoc(W, H, fonts, label)

    bg = t["btn_solid_bg"] if solid else t["btn_outline_bg"]
    fg = t["btn_solid_fg"] if solid else t["ink"]
    border = t["btn_solid_bg"] if solid else t["line"]

    path = sketch_rect_path(2.5, 2.5, W - 5, H - 5, amp=0.75, seed=seed)
    doc.add(f'<path d="{path}" fill="{bg}" stroke="{border}" stroke-width="1.85" stroke-linejoin="round"/>')

    total_w = tw + (icon_w if icon_kind else 0)
    sx = (W - total_w) / 2
    doc.text("marker", label, sx, 25, 14, fg)

    ix = sx + tw + 8
    if icon_kind == "arrow_right":
        doc.add(draw_arrow_right(ix, 14, fg, size=12))
    elif icon_kind == "wave":
        doc.add(draw_wave_hand(ix, 12, t["ink"], t["accent"], size=16))
    elif icon_kind == "arrow_ne":
        doc.add(draw_arrow_ne(ix, 14.5, t["accent"], size=11))

    return doc.render()


def build_contact_chip(fonts: FontEngine, theme_name: str, label: str, icon_kind: str) -> str:
    t = THEMES[theme_name]
    tw = fonts.measure("marker", label, 12.5)
    W = round(tw + 44)
    H = 34
    doc = SvgDoc(W, H, fonts, label)
    doc.add(
        f'<rect x="1" y="1" width="{W - 2}" height="{H - 2}" rx="6" '
        f'fill="{t["chip_bg"]}" stroke="{t["chip_border"]}" stroke-width="1.15"/>'
    )
    if icon_kind == "pin":
        doc.add(draw_pin_icon(11, 9.5, t["ink"]))
    elif icon_kind == "mail":
        doc.add(draw_mail_icon(11, 9.5, t["ink"]))
    elif icon_kind == "link":
        doc.add(draw_link_icon(11, 9.5, t["ink"]))
    doc.text("marker", label, 31, 21.5, 12.5, t["ink"])
    return doc.render()


def build_social_pill(fonts: FontEngine, theme_name: str, label: str, kind: str, seed: int) -> str:
    t = THEMES[theme_name]
    tw = fonts.measure("marker", label, 13)
    W = round(tw + 48)
    H = 36
    doc = SvgDoc(W, H, fonts, label)
    path = sketch_rect_path(2, 2, W - 4, H - 4, amp=0.65, seed=seed)
    doc.add(f'<path d="{path}" fill="{t["chip_bg"]}" stroke="{t["card_border"]}" stroke-width="1.35"/>')
    doc.add(draw_social_icon(kind, 13, 10.5, t))
    doc.text("marker", label, 35, 22.5, 13, t["ink"])
    return doc.render()


def build_stack(fonts: FontEngine, theme_name: str) -> str:
    t = THEMES[theme_name]
    dark = theme_name == "dark"
    W, H = 860, 404
    doc = SvgDoc(W, H, fonts, "01 Stack — The Toolbox")
    doc.add_graph_paper_bg(t, rx=10)

    # Header: `01 Stack`  +  `// the toolbox`
    doc.text("marker", "01", 40, 54, 12, t["accent"])
    doc.text("hand", "Stack", 64, 56, 34, t["ink"])
    doc.text("marker", "// the toolbox", W - 40, 54, 12, t["ink_soft"], align="right")

    categories = [
        ("// FRONTEND", ["ReactJS", "Next.js", "Vue.js", "Tailwind CSS", "TypeScript", "TanStack Query"]),
        ("// BACKEND", ["Express.js", "NestJS", "Serverless", "Node.js", "Docker", "GraphQL"]),
        ("// MOBILE", ["Flutter", "Dart", "GetX", "Bloc"]),
        ("// DATABASE", ["PostgreSQL", "MongoDB", "MySQL"]),
    ]

    cy = 96
    for cat_label, items in categories:
        doc.text("marker", cat_label, 42, cy, 10.5, t["ink_soft"], letter_spacing=1.3)
        cx = 42
        chip_y = cy + 12
        for item in items:
            lw = fonts.measure("marker", item, 12.5)
            cw = round(lw + 38)
            ch = 32
            doc.add(
                f'<rect x="{cx}" y="{chip_y}" width="{cw}" height="{ch}" rx="4" '
                f'fill="{t["chip_bg"]}" stroke="{t["chip_border"]}" stroke-width="1.05"/>'
            )
            doc.add(draw_tech_icon(item, cx + 10, chip_y + 8, t, dark))
            doc.text("marker", item, cx + 31, chip_y + 20.5, 12.5, t["ink"])
            cx += cw + 10
        cy += 76

    # Iconic bottom-right tilted vermilion red handwritten margin note (exact portfolio quote!)
    nx = 668
    doc.text("marker", "drag 'em onto a", nx, 336, 12, t["accent"], rotate=-3.2)
    doc.text("marker", "project,", nx + 2, 352, 12, t["accent"], rotate=-3.2)
    sw = doc.text("marker", "they actually ship", nx + 4, 368, 12, t["accent"], rotate=-3.2)
    doc.add(draw_spark(nx + 4 + sw + 10, 358, t["accent"], r=4.6))

    return doc.render()


def build_experience(fonts: FontEngine, theme_name: str) -> str:
    t = THEMES[theme_name]
    experiences = [
        {
            "badge": "dichi",
            "company": "Dichi Academy",
            "role": "Full Stack Developer",
            "dates": "Sep 2025 — Jun 2026",
            "bullets": [
                "Building a Learning Management System (LMS) with Node.js, TypeScript & NestJS",
                "Designing Vue.js interfaces, SQL database schemas & automated test suites",
            ],
        },
        {
            "badge": "cellcard",
            "company": "Cellcard (CamGSM PLC.)",
            "role": "Engineer, Mobile Development  (prev. Mobile App Trainee)",
            "dates": "May 2023 — Sep 2025",
            "bullets": [
                "Rewrote Cellcard Selfcare App (Flutter) & Website (Next.js, TanStack Query, Zod)",
                "Integrated Cellcard Payment Gateway (KHQR, ABA, WING, iPay) & Sales Force App",
            ],
        },
        {
            "badge": "pethstrey",
            "company": "PethStrey",
            "role": "Frontend Developer / Freelance",
            "dates": "Sep 2024 — Dec 2024",
            "bullets": [
                "Built a dynamic Next.js CMS for Cambodia's women's digital health platform",
            ],
        },
        {
            "badge": "prutteka",
            "company": "Prutteka",
            "role": "Co-Founder / Software Developer",
            "dates": "Sep 2022 — May 2023",
            "bullets": [
                "Co-founded a full-stack local events platform built with Next.js & Express.js",
            ],
        },
    ]

    # Compute exact dynamic height so every card fits with clean breathing room
    card_heights = [60 + len(e["bullets"]) * 21 + 10 for e in experiences]
    W = 860
    H = 82 + sum(card_heights) + (len(experiences) - 1) * 12 + 28
    doc = SvgDoc(W, H, fonts, "02 Work Experience")
    doc.add_graph_paper_bg(t, rx=10)

    # Section Header
    doc.text("marker", "02", 40, 54, 12, t["accent"])
    doc.text("hand", "Work Experience", 64, 56, 34, t["ink"])
    doc.text("marker", "// places i've shipped", W - 40, 54, 12, t["ink_soft"], align="right")

    cy = 80
    for exp, card_h in zip(experiences, card_heights):
        doc.add(
            f'<rect x="40" y="{cy}" width="{W - 80}" height="{card_h}" rx="4" '
            f'fill="{t["paper2"]}" stroke="{t["card_border"]}" stroke-width="1"/>'
        )
        doc.add(draw_company_badge(exp["badge"], 56, cy + 14, t))
        doc.text("hand", exp["company"], 104, cy + 30, 22, t["ink"])
        doc.text("marker", exp["role"], 104, cy + 48, 11.5, t["ink_soft"])
        doc.text("marker", exp["dates"], W - 56, cy + 29, 11, t["ink_soft"], align="right")

        by = cy + 71
        for b in exp["bullets"]:
            doc.text("marker", "-", 60, by, 12, t["accent"])
            doc.text("marker", b, 74, by, 11.5, t["ink_soft"])
            by += 21

        cy += card_h + 12

    return doc.render()


def build_footer_top(fonts: FontEngine, theme_name: str) -> str:
    t = THEMES[theme_name]
    W, H = 860, 128
    doc = SvgDoc(W, H, fonts, "Say hi — Let's connect")
    doc.add_graph_paper_bg(t, rx=10)
    doc.add_divider(40, 16, W - 40, t, seed=91)

    doc.text("marker", "// LET'S TALK", W / 2, 42, 10.5, t["ink_soft"], align="center", letter_spacing=1.5)

    # Centered `Say hi` + hand-drawn waving hand icon with clean gap
    hw = fonts.measure("hand", "Say hi", 44)
    gap = 12
    hand_size = 26
    sx = W / 2 - (hw + gap + hand_size) / 2
    doc.text("hand", "Say hi", sx, 85, 44, t["ink"])
    doc.add(draw_wave_hand(sx + hw + gap, 56, t["ink"], t["accent"], size=hand_size))

    doc.text("marker", "Always building something. Let's connect:", W / 2, 112, 13, t["ink_soft"], align="center")
    return doc.render()


def build_footer_note(fonts: FontEngine, theme_name: str) -> str:
    t = THEMES[theme_name]
    W, H = 860, 48
    doc = SvgDoc(W, H, fonts, "drawn by hand · built to click · lornsamnang.com")
    doc.add_graph_paper_bg(t, rx=8)
    doc.text(
        "marker",
        "drawn by hand  ·  built to click  ·  lornsamnang.com",
        W / 2,
        29,
        12,
        t["ink_faint"],
        align="center",
        rotate=-1.2,
    )
    return doc.render()


# ---------------------------------------------------------------------------
# Main Entrypoint
# ---------------------------------------------------------------------------
def main() -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    fonts = FontEngine()

    generated: List[Path] = []

    def save(name: str, svg_str: str) -> None:
        # Strict XML validation so no broken SVG can ever be emitted
        ET.fromstring(svg_str)
        out = ASSETS_DIR / name
        out.write_text(svg_str, encoding="utf-8")
        generated.append(out)

    for theme in ("light", "dark"):
        # Hero
        save(f"hero-{theme}.svg", build_hero(fonts, theme))

        # Action Buttons
        save(f"btn-work-{theme}.svg", build_button(fonts, theme, "see the work", True, "arrow_right", 11))
        save(f"btn-hi-{theme}.svg", build_button(fonts, theme, "say hi", False, "wave", 12))
        save(f"btn-blog-{theme}.svg", build_button(fonts, theme, "read the blog", False, "arrow_ne", 13))

        # Contact Strip Chips
        save(f"chip-location-{theme}.svg", build_contact_chip(fonts, theme, "Phnom Penh, KH", "pin"))
        save(f"chip-email-{theme}.svg", build_contact_chip(fonts, theme, "lorn.samnang.it@gmail.com", "mail"))
        save(f"chip-web-{theme}.svg", build_contact_chip(fonts, theme, "lornsamnang.com", "link"))

        # 01 Stack
        save(f"stack-{theme}.svg", build_stack(fonts, theme))

        # 02 Work Experience
        save(f"experience-{theme}.svg", build_experience(fonts, theme))

        # Footer & Social Pills
        save(f"footer-top-{theme}.svg", build_footer_top(fonts, theme))
        save(f"social-web-{theme}.svg", build_social_pill(fonts, theme, "lornsamnang.com", "web", 801))
        save(f"social-linkedin-{theme}.svg", build_social_pill(fonts, theme, "LinkedIn", "linkedin", 802))
        save(f"social-telegram-{theme}.svg", build_social_pill(fonts, theme, "Telegram", "telegram", 803))
        save(f"social-instagram-{theme}.svg", build_social_pill(fonts, theme, "Instagram", "instagram", 804))
        save(f"social-email-{theme}.svg", build_social_pill(fonts, theme, "Email", "email", 805))
        save(f"footer-note-{theme}.svg", build_footer_note(fonts, theme))

    total_kb = sum(p.stat().st_size for p in generated) / 1024
    print(f"Validated & generated {len(generated)} SVG assets in {ASSETS_DIR} (total {total_kb:.1f} KB)")
    for p in sorted(generated):
        if p.name.endswith("-light.svg"):
            print(f"  {p.name:34s} {p.stat().st_size / 1024:6.1f} KB")


if __name__ == "__main__":
    main()
