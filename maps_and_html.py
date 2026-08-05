#!/usr/bin/env python3
"""
Mappe SVG e pagine HTML statiche per GAFOR e METEOMAR.
Le pagine incorporano i dati al momento della generazione;
con --serve vengono rigenerate a ogni richiesta (sempre aggiornate).
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from gafor_meteomar import GaforBulletin, GaforEntry, MeteomarBulletin, SeaForecast

# ---------------------------------------------------------------------------
# Colori
# ---------------------------------------------------------------------------

GAFOR_COLORS = {
    "O": ("#16a34a", "#052e16", "Favorevole"),
    "D": ("#ca8a04", "#422006", "Difficile"),
    "M": ("#ea580c", "#431407", "Marginale"),
    "X": ("#dc2626", "#450a0a", "Critico"),
    "?": ("#64748b", "#0f172a", "N/D"),
}

# severità mare 0..8 → colore
SEA_PALETTE = [
    "#0ea5e9",  # 0 calmo
    "#22c55e",  # 1 quasi calmo
    "#84cc16",  # 2 poco mosso
    "#eab308",  # 3 mosso
    "#f97316",  # 4 molto mosso
    "#ef4444",  # 5 agitato
    "#b91c1c",  # 6+
    "#7f1d1d",
    "#450a0a",
]


def gafor_cat_color(primary: str) -> tuple[str, str, str]:
    m = re.match(r"^([ODMX])", (primary or "?").upper())
    letter = m.group(1) if m else "?"
    return GAFOR_COLORS.get(letter, GAFOR_COLORS["?"])


def sea_color(level: Optional[int], severity: int = 0) -> str:
    if level is not None:
        idx = max(0, min(level, len(SEA_PALETTE) - 1))
        return SEA_PALETTE[idx]
    idx = max(0, min(severity, len(SEA_PALETTE) - 1))
    return SEA_PALETTE[idx]


# ---------------------------------------------------------------------------
# SVG – silhouette Italia + zone GAFOR (schematiche da mappa ufficiale AM)
# viewBox 0 0 420 620  (N↑)
# ---------------------------------------------------------------------------

# Poligoni zone (coordinate schematiche allineate alla cartina Istr. MET 38/87)
GAFOR_ZONE_POLYS: dict[str, str] = {
    # 1 Alpi settentrionali
    "1": "150,35 210,30 255,55 240,95 185,105 145,80",
    # 2 Alpi NE / Triveneto
    "2": "255,55 310,70 320,120 275,140 240,95",
    # 3 Padania est / alto Adriatico
    "3": "240,95 275,140 290,175 245,185 210,150 185,105",
    # 4 Medio Adriatico / App. centro-nord
    "4": "210,150 245,185 260,230 215,245 185,200",
    # 5 Puglia / basso Adriatico
    "5": "275,250 350,255 365,310 330,350 285,340 260,290",
    # 6 Italia centrale adriatico-app.
    "6": "215,245 260,230 275,250 260,290 220,300 190,270",
    # 7 Calabria / estremo Sud
    "7": "285,340 330,350 320,410 275,430 255,390 260,340",
    # 8 Mar Ionio
    "8": "220,360 255,390 275,430 250,470 200,455 185,400",
    # 9 Sicilia
    "9": "175,480 255,470 280,510 240,555 165,545 150,505",
    # 10 Tirreno merid. / Sardegna est
    "10": "95,320 160,310 185,370 170,440 120,450 85,390",
    # 11 Mar di Sardegna / Sardegna ovest
    "11": "20,250 95,240 95,320 85,390 40,380 15,310",
    # 12 Tirreno centrale
    "12": "145,150 185,145 190,230 185,300 145,310 115,250 120,180",
    # 13 Alpi occidentali / Piemonte-Liguria
    "13": "70,70 150,35 145,80 185,105 145,150 115,160 75,130 55,95",
}

# Etichette centro zona
GAFOR_ZONE_LABELS: dict[str, tuple[float, float]] = {
    "1": (200, 65),
    "2": (280, 95),
    "3": (245, 145),
    "4": (230, 195),
    "5": (315, 300),
    "6": (235, 265),
    "7": (295, 385),
    "8": (230, 415),
    "9": (210, 515),
    "10": (130, 375),
    "11": (55, 310),
    "12": (155, 230),
    "13": (110, 100),
}

# Outline Italia grezza (solo sfondo)
ITALY_LAND = (
    "M 80,90 L 130,40 L 200,30 L 280,50 L 320,90 L 300,150 L 280,200 "
    "L 260,250 L 270,300 L 300,340 L 310,400 L 280,440 L 250,430 "
    "L 230,380 L 200,340 L 180,300 L 170,250 L 160,180 L 130,150 "
    "L 100,140 L 75,110 Z "
    "M 55,280 L 100,260 L 110,340 L 95,400 L 60,390 L 45,330 Z "  # Sardegna
    "M 165,490 L 250,480 L 270,520 L 230,550 L 160,540 Z"  # Sicilia
)


def svg_gafor_map(zone_cats: dict[str, str], title: str = "Zone GAFOR") -> str:
    """zone_cats: '1' -> 'O' | 'D2' | 'M5' | 'X' | ''."""
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 420 600" '
        'class="map-svg" role="img" aria-label="Cartina zone GAFOR Italia">',
        f'<title>{html.escape(title)}</title>',
        '<rect width="420" height="600" fill="#0b1220"/>',
        # mare
        '<rect x="0" y="0" width="420" height="600" fill="#0c4a6e" opacity="0.35"/>',
        # terra di sfondo
        f'<path d="{ITALY_LAND}" fill="#1e293b" stroke="#334155" stroke-width="1.2"/>',
    ]
    for zid, poly in GAFOR_ZONE_POLYS.items():
        cat = zone_cats.get(zid, zone_cats.get(str(int(zid)), ""))
        fill, stroke, _ = gafor_cat_color(cat or "?")
        label = (cat or "—")[:3]
        parts.append(
            f'<polygon points="{poly}" fill="{fill}" fill-opacity="0.82" '
            f'stroke="#f8fafc" stroke-width="1.5" class="zone z{zid}">'
            f"<title>Zona {zid}: {html.escape(cat or 'N/D')}</title></polygon>"
        )
        lx, ly = GAFOR_ZONE_LABELS[zid]
        parts.append(
            f'<circle cx="{lx}" cy="{ly}" r="14" fill="#0f172a" stroke="#f8fafc" stroke-width="1.5"/>'
            f'<text x="{lx}" y="{ly + 1}" text-anchor="middle" dominant-baseline="middle" '
            f'font-family="system-ui,sans-serif" font-size="12" font-weight="700" fill="#f8fafc">{zid}</text>'
        )
        # mini badge categoria sotto
        parts.append(
            f'<text x="{lx}" y="{ly + 26}" text-anchor="middle" '
            f'font-family="system-ui,sans-serif" font-size="10" font-weight="700" fill="{fill}">'
            f"{html.escape(label)}</text>"
        )
    # legenda
    parts.append('<g transform="translate(12,540)">')
    parts.append(
        '<text x="0" y="0" fill="#94a3b8" font-size="11" font-family="system-ui,sans-serif">'
        "Legenda categorie</text>"
    )
    x = 0
    for letter in ("O", "D", "M", "X"):
        fill, _, name = GAFOR_COLORS[letter]
        parts.append(
            f'<rect x="{x}" y="8" width="14" height="14" rx="3" fill="{fill}"/>'
            f'<text x="{x + 18}" y="19" fill="#e2e8f0" font-size="11" '
            f'font-family="system-ui,sans-serif">{letter} {name}</text>'
        )
        x += 95
    parts.append("</g>")
    parts.append("</svg>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# SVG – mari italiani METEOMAR (schematici)
# viewBox 0 0 480 620
# ---------------------------------------------------------------------------

# Chiavi = nome area normalizzato come in SeaForecast.area (title case)
SEA_POLYS: dict[str, tuple[str, tuple[float, float], str]] = {
    # name_key: (polygon points, label xy, short label)
    "Mar Ligure": (
        "130,95 200,90 210,130 160,145 120,130",
        (160, 115),
        "Ligure",
    ),
    "Mar Di Corsica": (
        "70,120 120,115 130,180 95,210 55,180",
        (90, 155),
        "Corsica",
    ),
    "Mar Di Sardegna": (
        "15,200 70,195 80,280 50,320 10,290",
        (45, 250),
        "Sardegna",
    ),
    "Canale Di Sardegna": (
        "50,320 95,310 110,370 80,400 45,380",
        (75, 350),
        "Can.Sard.",
    ),
    "Tirreno Settentrionale": (
        "160,145 220,140 230,195 185,210 155,185",
        (190, 170),
        "Tirr.N",
    ),
    "Tirreno Centrale Ovest": (
        "100,210 155,200 165,270 120,290 90,250",
        (125, 245),
        "Tirr.CO",
    ),
    "Tirreno Centrale Est": (
        "165,200 220,195 230,270 180,290 160,250",
        (195, 245),
        "Tirr.CE",
    ),
    "Tirreno Meridionale Ovest": (
        "110,290 165,280 175,360 130,380 100,340",
        (140, 330),
        "Tirr.MO",
    ),
    "Tirreno Meridionale Est": (
        "175,290 230,285 240,370 190,385 170,340",
        (205, 335),
        "Tirr.ME",
    ),
    "Stretto Di Sicilia": (
        "130,400 200,395 220,445 160,460 120,435",
        (165, 425),
        "Str.Sic.",
    ),
    "Ionio Meridionale": (
        "230,400 300,395 320,470 260,490 220,450",
        (265, 440),
        "Ionio M",
    ),
    "Ionio Settentrionale": (
        "240,330 300,320 315,390 265,400 235,370",
        (275, 360),
        "Ionio N",
    ),
    "Adriatico Meridionale": (
        "300,280 370,275 380,340 330,360 295,330",
        (340, 310),
        "Adr.M",
    ),
    "Adriatico Centrale": (
        "280,200 350,195 365,265 310,280 275,245",
        (320, 235),
        "Adr.C",
    ),
    "Adriatico Settentrionale": (
        "250,120 330,115 345,185 290,200 245,165",
        (295, 155),
        "Adr.N",
    ),
}

# Alias per match flessibile sul nome area del parser
SEA_ALIASES: dict[str, str] = {
    "MAR LIGURE": "Mar Ligure",
    "MAR DI CORSICA": "Mar Di Corsica",
    "MAR DI SARDEGNA": "Mar Di Sardegna",
    "CANALE DI SARDEGNA": "Canale Di Sardegna",
    "TIRRENO SETTENTRIONALE": "Tirreno Settentrionale",
    "TIRRENO CENTRALE OVEST": "Tirreno Centrale Ovest",
    "TIRRENO CENTRALE EST": "Tirreno Centrale Est",
    "TIRRENO MERIDIONALE OVEST": "Tirreno Meridionale Ovest",
    "TIRRENO MERIDIONALE EST": "Tirreno Meridionale Est",
    "STRETTO DI SICILIA": "Stretto Di Sicilia",
    "IONIO MERIDIONALE": "Ionio Meridionale",
    "IONIO SETTENTRIONALE": "Ionio Settentrionale",
    "ADRIATICO MERIDIONALE": "Adriatico Meridionale",
    "ADRIATICO CENTRALE": "Adriatico Centrale",
    "ADRIATICO SETTENTRIONALE": "Adriatico Settentrionale",
}


def _norm_sea_name(name: str) -> str:
    u = re.sub(r"\s+", " ", name.strip().upper())
    if u in SEA_ALIASES:
        return SEA_ALIASES[u]
    # title-case match
    for k in SEA_POLYS:
        if k.upper() == u:
            return k
    return name


def svg_seas_map(
    area_info: dict[str, tuple[Optional[int], int, str]],
    title: str = "Mari italiani – METEOMAR",
) -> str:
    """area_info: canonical name -> (sea_level, severity, tooltip)."""
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 420 560" '
        'class="map-svg" role="img" aria-label="Cartina mari italiani METEOMAR">',
        f'<title>{html.escape(title)}</title>',
        '<rect width="420" height="560" fill="#0b1220"/>',
        '<rect width="420" height="560" fill="#0c4a6e" opacity="0.4"/>',
        f'<path d="{ITALY_LAND}" fill="#1e293b" stroke="#475569" stroke-width="1.5"/>',
    ]
    for key, (poly, (lx, ly), short) in SEA_POLYS.items():
        level, sev, tip = area_info.get(key, (None, 0, key))
        fill = sea_color(level, sev)
        parts.append(
            f'<polygon points="{poly}" fill="{fill}" fill-opacity="0.8" '
            f'stroke="#f8fafc" stroke-width="1.2">'
            f"<title>{html.escape(tip)}</title></polygon>"
        )
        parts.append(
            f'<text x="{lx}" y="{ly}" text-anchor="middle" dominant-baseline="middle" '
            f'font-family="system-ui,sans-serif" font-size="9" font-weight="700" '
            f'fill="#0f172a" stroke="#f8fafc" stroke-width="0.35" paint-order="stroke">'
            f"{html.escape(short)}</text>"
        )
    # legenda stato del mare
    parts.append('<g transform="translate(12,500)">')
    parts.append(
        '<text x="0" y="0" fill="#94a3b8" font-size="11" font-family="system-ui,sans-serif">'
        "Stato del mare (Douglas)</text>"
    )
    labels = ["calmo", "q.calmo", "p.mosso", "mosso", "m.mosso", "agitato"]
    for i, lab in enumerate(labels):
        x = i * 66
        parts.append(
            f'<rect x="{x}" y="8" width="14" height="14" rx="3" fill="{SEA_PALETTE[i]}"/>'
            f'<text x="{x + 18}" y="19" fill="#e2e8f0" font-size="10" '
            f'font-family="system-ui,sans-serif">{lab}</text>'
        )
    parts.append("</g>")
    parts.append("</svg>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# CSS / shell HTML
# ---------------------------------------------------------------------------

CSS = """
:root {
  --bg: #0b1220;
  --panel: #111827;
  --panel2: #1e293b;
  --text: #e2e8f0;
  --muted: #94a3b8;
  --border: #334155;
  --accent: #38bdf8;
  --ok: #16a34a;
  --warn: #ca8a04;
  --caution: #ea580c;
  --bad: #dc2626;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  font-family: "Segoe UI", system-ui, -apple-system, sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.45;
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
header {
  background: linear-gradient(135deg, #0c4a6e 0%, #111827 60%);
  border-bottom: 1px solid var(--border);
  padding: 1rem 1.25rem;
  position: sticky; top: 0; z-index: 10;
}
header .row { display: flex; flex-wrap: wrap; gap: .75rem 1.25rem; align-items: center; justify-content: space-between; }
header h1 { margin: 0; font-size: 1.25rem; letter-spacing: .02em; }
header .meta { color: var(--muted); font-size: .9rem; }
header .meta strong { color: #fde68a; font-weight: 700; }
.stamp {
  display: grid; gap: .25rem;
  background: #0f172a; border: 1px solid var(--border);
  border-radius: 8px; padding: .65rem .85rem; margin: 0 0 1rem;
  font-size: .9rem;
}
.stamp .k { color: var(--muted); }
.stamp .v { color: #f8fafc; font-weight: 600; }
nav { display: flex; gap: .75rem; flex-wrap: wrap; }
nav a {
  background: var(--panel2);
  border: 1px solid var(--border);
  padding: .35rem .75rem;
  border-radius: 999px;
  color: var(--text);
  font-size: .9rem;
}
nav a.active { border-color: var(--accent); color: var(--accent); }
main {
  max-width: 1100px;
  margin: 0 auto;
  padding: 1.25rem;
  display: grid;
  gap: 1.25rem;
}
.grid-2 {
  display: grid;
  grid-template-columns: 1.1fr 1fr;
  gap: 1.25rem;
}
@media (max-width: 860px) {
  .grid-2 { grid-template-columns: 1fr; }
}
.card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 1rem 1.1rem;
  box-shadow: 0 8px 24px rgba(0,0,0,.25);
}
.card h2 {
  margin: 0 0 .75rem;
  font-size: 1.05rem;
  color: #f8fafc;
  border-bottom: 1px solid var(--border);
  padding-bottom: .5rem;
}
.map-wrap { background: #0b1220; border-radius: 10px; overflow: hidden; border: 1px solid var(--border); }
.map-svg { width: 100%; height: auto; display: block; }
.legend-inline { display: flex; flex-wrap: wrap; gap: .4rem; margin: .5rem 0 0; }
.badge {
  display: inline-flex; align-items: center; gap: .3rem;
  padding: .15rem .55rem; border-radius: 999px;
  font-size: .8rem; font-weight: 700; color: #0f172a;
}
.badge.o { background: #16a34a; color: #fff; }
.badge.d { background: #eab308; }
.badge.m { background: #ea580c; color: #fff; }
.badge.x { background: #dc2626; color: #fff; }
.badge.sea { color: #0f172a; }
.zone-list, .sea-list { list-style: none; margin: 0; padding: 0; }
.zone-list li, .sea-list li {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: .5rem .75rem;
  padding: .65rem 0;
  border-bottom: 1px solid #1f2937;
  align-items: start;
}
.zone-list li:last-child, .sea-list li:last-child { border-bottom: 0; }
.zid {
  display: inline-block;
  min-width: 2.4rem; text-align: center;
  background: #0891b2; color: #041016;
  font-weight: 800; border-radius: 6px; padding: .2rem .35rem;
  font-size: .85rem;
}
.zname { font-weight: 700; color: #f8fafc; }
.zdesc { color: var(--muted); font-size: .9rem; margin-top: .15rem; }
.codes { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .85rem; color: #fde68a; }
pre.raw {
  margin: 0;
  background: #0f172a;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: .85rem 1rem;
  overflow: auto;
  color: #fef3c7;
  font-size: .88rem;
  line-height: 1.4;
  white-space: pre-wrap;
}
.chips { display: flex; flex-wrap: wrap; gap: .35rem; margin: .25rem 0 .35rem; }
.chip {
  font-size: .78rem; font-weight: 700;
  padding: .12rem .5rem; border-radius: 999px;
  background: #334155; color: #f1f5f9;
}
.chip.ok { background: #166534; }
.chip.warn { background: #854d0e; }
.chip.caution { background: #9a3412; }
.chip.bad { background: #991b1b; }
.warn-box {
  border-left: 4px solid var(--ok);
  background: #052e16;
  padding: .6rem .85rem;
  border-radius: 0 8px 8px 0;
  margin: .35rem 0;
  font-size: .92rem;
}
.warn-box.alert {
  border-left-color: var(--bad);
  background: #450a0a;
}
footer {
  max-width: 1100px; margin: 0 auto 2rem;
  padding: 0 1.25rem;
  color: var(--muted); font-size: .85rem;
}
.dot { width: .7rem; height: .7rem; border-radius: 50%; display: inline-block; }
"""


def _esc(s: str) -> str:
    return html.escape(s or "", quote=True)


def _page_shell(
    title: str,
    active: str,
    body: str,
    generated: str,
    source_date: str = "",
    refresh_seconds: int = 0,
) -> str:
    meta_refresh = ""
    if refresh_seconds and refresh_seconds > 0:
        meta_refresh = f'<meta http-equiv="refresh" content="{int(refresh_seconds)}">'
    nav = f"""
    <nav>
      <a href="gafor.html" class="{'active' if active == 'gafor' else ''}">GAFOR</a>
      <a href="meteomar.html" class="{'active' if active == 'meteomar' else ''}">METEOMAR</a>
      <a href="index.html">Indice</a>
    </nav>"""
    return f"""<!DOCTYPE html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="{_esc(title)} – bollettino Aeronautica Militare">
  {meta_refresh}
  <title>{_esc(title)}</title>
  <style>{CSS}</style>
</head>
<body>
  <header>
    <div class="row">
      <div>
        <h1>{_esc(title)}</h1>
        <div class="meta">
          Generato: {_esc(generated)}
          {f'· Fonte bollettino: {_esc(source_date)}' if source_date else ''}
          · dati live da meteoam.it
        </div>
      </div>
      {nav}
    </div>
  </header>
  <main>
    {body}
  </main>
  <footer>
    Fonte: Servizio Meteorologico Aeronautica Militare (meteoam.it).
    Uso informativo — verificare sempre i bollettini ufficiali prima di volo o navigazione.
    Pagine statiche regenerate dallo script <code>gafor_meteomar.py --html</code>
    (o sempre fresche con <code>--serve</code>).
  </footer>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# GAFOR HTML
# ---------------------------------------------------------------------------

def build_gafor_zone_cats(b: "GaforBulletin") -> dict[str, str]:
    """Mappa numero zona (senza settore) → categoria primaria peggiore."""
    order = {"O": 0, "D": 1, "M": 2, "X": 3}
    out: dict[str, str] = {}
    scores: dict[str, int] = {}
    for e in b.entries:
        letter_m = re.match(r"^([ODMX])", (e.primary or "").upper())
        letter = letter_m.group(1) if letter_m else "?"
        sc = order.get(letter, -1)
        for z in e.zones:
            m = re.match(r"(\d+)", z)
            if not m:
                continue
            num = str(int(m.group(1)))
            if sc >= scores.get(num, -1):
                scores[num] = sc
                out[num] = e.primary or letter
    return out


def render_gafor_html(
    b: "GaforBulletin",
    *,
    refresh_seconds: int = 0,
) -> str:
    from gafor_meteomar import (
        GAFOR_ZONE_NAMES,
        describe_gafor_cond,
        format_validity,
        zone_parts,
        worst_gafor_cat,
    )

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    zone_cats = build_gafor_zone_cats(b)
    svg = svg_gafor_map(zone_cats)

    # lista zone 1-13
    zone_map: dict[str, "GaforEntry"] = {}
    for e in b.entries:
        for z in e.zones:
            zone_map[z] = e

    # preferisci chiave numerica base
    by_num: dict[str, list[tuple[str, "GaforEntry"]]] = {}
    for z, e in zone_map.items():
        m = re.match(r"(\d+)", z)
        num = str(int(m.group(1))) if m else z
        by_num.setdefault(num, []).append((z, e))

    items = []
    for num in map(str, range(1, 14)):
        name = GAFOR_ZONE_NAMES.get(num, f"Zona {num}")
        entries = by_num.get(num, [])
        if not entries:
            items.append(
                f'<li><span class="zid">Z{int(num):02d}</span>'
                f'<div><div class="zname">{_esc(name)}</div>'
                f'<div class="zdesc">Non esplicitata nel messaggio (coperta da range)</div></div></li>'
            )
            continue
        # unifica se stessa entry
        seen = set()
        for z, e in sorted(entries, key=lambda t: t[0]):
            if id(e) in seen and z == num:
                continue
            seen.add(id(e))
            zid, geo = zone_parts(z)
            letter = (e.primary or "?")[:1].upper()
            cls = letter.lower() if letter in "ODMX" else "o"
            desc = describe_gafor_cond(e.primary, e.rest)
            codes = f'<div class="codes">{_esc(e.rest)}</div>' if e.rest else ""
            items.append(
                f'<li><span class="zid">{_esc(zid)}</span>'
                f'<div>'
                f'<div class="zname">{_esc(geo)} '
                f'<span class="badge {cls}">{_esc(e.primary or "?")}</span></div>'
                f'<div class="zdesc">{_esc(desc)}</div>{codes}'
                f"</div></li>"
            )

    worst = worst_gafor_cat(b.entries)
    wfill, _, wname = gafor_cat_color(worst)
    meta_bits = []
    if b.origin:
        meta_bits.append(f"centro { _esc(b.origin) }")
    if b.validity:
        meta_bits.append(f"validità { _esc(format_validity(b.validity)) }")
    meta = " · ".join(meta_bits)

    body = f"""
    <div class="card">
      <h2>Sintesi</h2>
      <p style="margin:0">{meta}</p>
      <p>Condizione più severa:
        <span class="badge" style="background:{wfill};color:#fff">{_esc(worst)} {_esc(wname)}</span>
      </p>
      <div class="legend-inline">
        <span class="badge o">O Favorevole</span>
        <span class="badge d">D Difficile</span>
        <span class="badge m">M Marginale</span>
        <span class="badge x">X Critico</span>
      </div>
    </div>

    <div class="grid-2">
      <div class="card">
        <h2>Cartina zone GAFOR</h2>
        <div class="map-wrap">{svg}</div>
        <p style="color:var(--muted);font-size:.85rem;margin:.6rem 0 0">
          Poligoni schematici dalla mappa ufficiale AM (Istr. MET 38/87).
          Colore = categoria prevalente della zona.
        </p>
      </div>
      <div class="card">
        <h2>Decodifica per zona</h2>
        <ul class="zone-list">
          {''.join(items)}
        </ul>
      </div>
    </div>

    <div class="card">
      <h2>Testo ufficiale (RAW)</h2>
      <p style="color:var(--muted);font-size:.85rem;margin-top:0">{_esc(b.source_name or '')}</p>
      <pre class="raw">{_esc(b.raw.strip())}</pre>
    </div>
    """
    return _page_shell(
        "GAFOR · Italia",
        "gafor",
        body,
        generated,
        source_date=b.source_date or "",
        refresh_seconds=refresh_seconds,
    )


# ---------------------------------------------------------------------------
# METEOMAR HTML
# ---------------------------------------------------------------------------

def render_meteomar_html(
    b: "MeteomarBulletin",
    *,
    refresh_seconds: int = 0,
) -> str:
    from gafor_meteomar import _area_severity

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    area_info: dict[str, tuple[Optional[int], int, str]] = {}
    for a in b.areas:
        key = _norm_sea_name(a.area)
        sev = _area_severity(a)
        tip = f"{a.area}: {a.sea_label or '—'} · vento {a.wind_dir or ''} {a.wind_bf or '—'} Bft"
        area_info[key] = (a.sea_level, sev, tip)

    svg = svg_seas_map(area_info)

    warns = []
    for w in b.warnings:
        alert = not re.search(r"\bNIL\b", w, re.I)
        cls = "warn-box alert" if alert else "warn-box"
        warns.append(f'<div class="{cls}">{_esc(w)}</div>')
    if not warns:
        warns.append('<div class="warn-box">Nessun avviso decodificato</div>')

    def chip_class(kind: str) -> str:
        return {"ok": "ok", "warn": "warn", "caution": "caution", "bad": "bad"}.get(kind, "")

    items = []
    for a in sorted(b.areas, key=lambda x: (-_area_severity(x), x.area)):
        sev = _area_severity(a)
        if sev >= 5:
            dot = "var(--bad)"
        elif sev >= 3:
            dot = "var(--caution)"
        elif sev >= 2:
            dot = "var(--warn)"
        else:
            dot = "var(--ok)"
        chips = []
        if a.wind_bf is not None:
            k = "ok" if a.wind_bf <= 3 else ("warn" if a.wind_bf == 4 else ("caution" if a.wind_bf <= 6 else "bad"))
            chips.append(
                f'<span class="chip {k}">{_esc((a.wind_dir or "Vento") + " " + str(a.wind_bf) + " Bft")}</span>'
            )
        if a.sea_label:
            k = "ok" if (a.sea_level or 0) <= 2 else ("warn" if (a.sea_level or 0) == 3 else "caution")
            if (a.sea_level or 0) >= 5:
                k = "bad"
            chips.append(f'<span class="chip {k}">{_esc(a.sea_label)}</span>')
        if a.vis_label:
            k = "ok" if (a.vis_level or 0) >= 4 else ("warn" if (a.vis_level or 0) == 3 else "bad")
            chips.append(f'<span class="chip {k}">vis. {_esc(a.vis_label)}</span>')
        if a.has_storm:
            chips.append('<span class="chip bad">temporali</span>')
        elif a.has_rain:
            chips.append('<span class="chip warn">pioggia</span>')
        if a.has_fog:
            chips.append('<span class="chip caution">nebbia/foschia</span>')
        trend = (
            f'<div class="zdesc"><strong>Tendenza:</strong> {_esc(a.trend)}</div>'
            if a.trend
            else ""
        )
        items.append(
            f'<li><span class="dot" style="background:{dot};margin-top:.45rem"></span>'
            f'<div><div class="zname">{_esc(a.area)}</div>'
            f'<div class="chips">{"".join(chips)}</div>'
            f'<div class="zdesc">{_esc(a.text)}</div>{trend}</div></li>'
        )

    extended = ""
    if b.extended:
        lis = "".join(f"<li style='margin:.35rem 0'>{_esc(e)}</li>" for e in b.extended)
        extended = f"""
        <div class="card">
          <h2>Tendenza vento/mare (12 h successive)</h2>
          <ul style="padding-left:1.1rem;color:var(--muted)">{lis}</ul>
        </div>"""

    body = f"""
    <div class="card">
      <h2>Sintesi</h2>
      <p style="margin:0 0 .35rem"><strong>{_esc(b.header)}</strong></p>
      <p style="margin:0;color:var(--muted)">
        {_esc(b.issued_line)}
        {f' · valido fino a {_esc(b.valid_until)}' if b.valid_until else ''}
      </p>
    </div>

    <div class="card">
      <h2>Avvisi</h2>
      {''.join(warns)}
    </div>

    {f'<div class="card"><h2>Situazione sinottica</h2><p style="margin:0">{_esc(b.situation)}</p></div>' if b.situation else ''}

    <div class="grid-2">
      <div class="card">
        <h2>Cartina mari italiani</h2>
        <div class="map-wrap">{svg}</div>
        <p style="color:var(--muted);font-size:.85rem;margin:.6rem 0 0">
          Aree marine METEOMAR (schema). Colore ≈ stato del mare / severità.
        </p>
      </div>
      <div class="card">
        <h2>Previsione per mare</h2>
        <ul class="sea-list">
          {''.join(items) if items else '<li>Nessuna area decodificata</li>'}
        </ul>
      </div>
    </div>

    {extended}

    <div class="card">
      <h2>Testo ufficiale (RAW)</h2>
      <p style="color:var(--muted);font-size:.85rem;margin-top:0">{_esc(b.source_name or '')}</p>
      <pre class="raw">{_esc(b.raw.strip())}</pre>
    </div>
    """
    return _page_shell(
        "METEOMAR · Mari Italia",
        "meteomar",
        body,
        generated,
        source_date=b.source_date or "",
        refresh_seconds=refresh_seconds,
    )


def render_index_html(
    gafor: Optional["GaforBulletin"],
    meteo: Optional["MeteomarBulletin"],
    *,
    refresh_seconds: int = 0,
) -> str:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    g_meta = (gafor.source_date if gafor else "—")
    m_meta = (meteo.source_date if meteo else "—")
    body = f"""
    <div class="card">
      <h2>Bollettini Aeronautica Militare</h2>
      <p>Pagine statiche generate dai messaggi ufficiali GAFOR e METEOMAR.</p>
      <ul>
        <li><a href="gafor.html"><strong>GAFOR</strong></a> — aviazione generale (zone 1–13)
          <span style="color:var(--muted)"> · aggiornato { _esc(str(g_meta)) }</span></li>
        <li><a href="meteomar.html"><strong>METEOMAR</strong></a> — mari e venti
          <span style="color:var(--muted)"> · aggiornato { _esc(str(m_meta)) }</span></li>
      </ul>
      <p style="color:var(--muted);font-size:.9rem">
        Per tenerle sempre aggiornate: esegui periodicamente
        <code>python3 gafor_meteomar.py --html</code>
        oppure avvia <code>python3 gafor_meteomar.py --serve</code>
        (rigenera i dati a ogni visita).
      </p>
    </div>
    """
    return _page_shell(
        "Bollettini GAFOR & METEOMAR",
        "index",
        body,
        generated,
        refresh_seconds=refresh_seconds,
    )


def write_html_pages(
    out_dir: Path,
    gafor: Optional["GaforBulletin"],
    meteo: Optional["MeteomarBulletin"],
    *,
    refresh_seconds: int = 0,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    if gafor is not None:
        p = out_dir / "gafor.html"
        p.write_text(render_gafor_html(gafor, refresh_seconds=refresh_seconds), encoding="utf-8")
        written.append(p)
    if meteo is not None:
        p = out_dir / "meteomar.html"
        p.write_text(render_meteomar_html(meteo, refresh_seconds=refresh_seconds), encoding="utf-8")
        written.append(p)
    p = out_dir / "index.html"
    p.write_text(render_index_html(gafor, meteo, refresh_seconds=refresh_seconds), encoding="utf-8")
    written.append(p)
    return written
