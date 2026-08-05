#!/usr/bin/env python3
"""
Presentazione colorata degli ultimi bollettini GAFOR e METEOMAR (Italia).

Fonti ufficiali: Servizio Meteorologico Aeronautica Militare (meteoam.it / OCE CMS).
Solo stdlib Python 3.8+.

Uso:
  ./gafor_meteomar.py              # GAFOR (raw+decodifica) + METEOMAR
  ./gafor_meteomar.py --gafor      # solo GAFOR (include sempre il raw)
  ./gafor_meteomar.py --meteomar   # solo METEOMAR
  ./gafor_meteomar.py --raw        # solo testo grezzo ufficiale (entrambi)
  ./gafor_meteomar.py --no-color   # senza ANSI
  ./gafor_meteomar.py --json       # output JSON strutturato
  ./gafor_meteomar.py --html       # genera html/gafor.html e html/meteomar.html
  ./gafor_meteomar.py --serve      # server HTTP: pagine sempre aggiornate
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import textwrap
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

# ---------------------------------------------------------------------------
# API ufficiali (content published – canali meteoam)
# ---------------------------------------------------------------------------

API_BASE = "https://cm.meteoam.it/content/published/api/v1.1/items"
USER_AGENT = "GaforMeteomarViewer/1.0 (+https://www.meteoam.it; personal use)"

GAFOR_CHANNEL = "8f518df69fcf4a51962113b025440251"
GAFOR_QUERY = 'type eq "Integration-Message"'

METEOMAR_CHANNEL = "7449487744984981831df3b6b37e73c9"
METEOMAR_QUERY = 'type eq "Integration-Message" and name sw "MESSAGGI/MSG4/FXIY61"'

# Zone GAFOR Italia (13 MET zones – Istr. MET 38/87 / mappa ufficiale AM).
# Nel messaggio compaiono SOLO i numeri: le etichette sotto sono descrizioni
# geografiche ricavate dalla cartina ufficiale (PDF meteoam «Gafor – Istr. MET 38/87»),
# non nomi formali del bollettino. Vedi anche gafor_zone_map.png nel progetto.
#
#   1  arco alpino settentrionale
#   2  Alpi NE / Triveneto
#   3  pianura padana orientale / alto Adriatico
#   4  medio Adriatico / Appennino centro-nord
#   5  Puglia / basso Adriatico
#   6  Italia centrale (versante adriatico-appenninico)
#   7  Calabria / estremità meridionale peninsulare
#   8  Mar Ionio
#   9  Sicilia
#  10  Tirreno meridionale / Sardegna orientale
#  11  Mar di Sardegna / Sardegna occidentale
#  12  Tirreno centrale
#  13  Alpi occidentali / Piemonte–Liguria–VdA
#
# (Storicamente: CMR Milano 1-2-3-4-13 · CMR Roma 6-10-11-12 · CMR Brindisi 5-7-8-9;
#  oggi l’emissione nazionale è unificata su FBIY61 / 1° CMR.)
GAFOR_ZONE_NAMES: dict[str, str] = {
    "1": "Alpi settentrionali",
    "2": "Alpi NE / Triveneto",
    "3": "Padania est / alto Adriatico",
    "4": "Medio Adriatico / App. centro-nord",
    "5": "Puglia / basso Adriatico",
    "6": "Italia centrale (adriatico-app.)",
    "7": "Calabria / estremo Sud peninsulare",
    "8": "Mar Ionio",
    "9": "Sicilia",
    "10": "Tirreno merid. / Sardegna est",
    "11": "Mar di Sardegna / Sardegna ovest",
    "12": "Tirreno centrale",
    "13": "Alpi occidentali / Piemonte-Liguria",
}

SECTOR_NAMES = {
    "N": "N",
    "S": "S",
    "E": "E",
    "W": "O",
    "O": "O",  # Ovest nel codice italiano
    "NE": "NE",
    "NW": "NO",
    "SE": "SE",
    "SW": "SO",
    "NO": "NO",
    "SO": "SO",
}

# Categorie GAFOR (wg) – legenda ufficiale semplificata
GAFOR_CAT = {
    "O": ("Favorevole", "VFR agevole (base nubi e visibilità buone)"),
    "D": ("Difficile", "Condizioni intermedie (subcategoria k=1…5)"),
    "M": ("Marginale", "Condizioni marginali per VFR (subcategoria k=1…5)"),
    "X": ("Critico", "IMC / VFR sconsigliato (base bassa e/o vis. ridotta)"),
}

# Fenomeni meteo frequenti nei messaggi
WX_IT = {
    "TSRA": "temporale con pioggia",
    "SHRA": "rovesci di pioggia",
    "TS": "temporali",
    "RA": "pioggia",
    "FG": "nebbia",
    "BR": "foschia",
    "HZ": "caligine",
    "SN": "neve",
    "SHSN": "rovesci di neve",
    "DZ": "pioviggine",
    "GR": "grandine",
    "SQ": "groppi",
}

MOD_IT = {
    "LOC": "locale",
    "MON": "in montagna",
    "COT": "sulla costa",
    "CIT": "in città / aree urbane",
    "OCNL": "occasionale",
    "ISOL": "isolato",
    "FRQ": "frequente",
    "EMBD": "inglobato",
    "GRADU": "graduale",
    "RAPID": "rapido",
    "TEMPO": "temporaneo",
    "INTER": "intermittente",
    "LAN": "nell'entroterra",
    "MAR": "sul mare",
    "VAL": "in valle",
}

# Scala Douglas (stato del mare) – parole tipiche METEOMAR
SEA_STATE_ORDER = [
    (r"\bmolto\s+grosso\b", 8, "molto grosso"),
    (r"\bgrosso\b", 7, "grosso"),
    (r"\bmolto\s+agitato\b", 6, "molto agitato"),
    (r"\bagitato\b", 5, "agitato"),
    (r"\bmolto\s+mosso\b", 4, "molto mosso"),
    (r"\bmosso\b", 3, "mosso"),
    (r"\bpoco\s+mosso\b", 2, "poco mosso"),
    (r"\bquasi\s+calmo\b", 1, "quasi calmo"),
    (r"\bcalmo\b", 0, "calmo"),
]

VIS_ORDER = [
    (r"\bpessima\b", 0, "pessima"),
    (r"\bcattiva\b", 1, "cattiva"),
    (r"\bscarsa\b", 2, "scarsa"),
    (r"\bdiscreta\b", 3, "discreta"),
    (r"\bbuona\b", 4, "buona"),
    (r"\bmolto\s+buona\b", 5, "molto buona"),
    (r"\bottima\b", 6, "ottima"),
]


# ---------------------------------------------------------------------------
# Colori ANSI
# ---------------------------------------------------------------------------

class Colors:
    """Palette ANSI; disattivabile via NO_COLOR / --no-color / pipe non-TTY."""

    def __init__(self, enabled: Optional[bool] = None) -> None:
        if enabled is None:
            enabled = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
        self.enabled = enabled

    def _s(self, code: str, text: str) -> str:
        if not self.enabled:
            return text
        return f"\033[{code}m{text}\033[0m"

    def bold(self, t: str) -> str:
        return self._s("1", t)

    def dim(self, t: str) -> str:
        return self._s("2", t)

    def underline(self, t: str) -> str:
        return self._s("4", t)

    # semantici
    def ok(self, t: str) -> str:  # verde
        return self._s("1;32", t)

    def mild(self, t: str) -> str:  # ciano
        return self._s("1;36", t)

    def warn(self, t: str) -> str:  # giallo
        return self._s("1;33", t)

    def caution(self, t: str) -> str:  # arancio (256)
        return self._s("1;38;5;208", t)

    def bad(self, t: str) -> str:  # rosso
        return self._s("1;31", t)

    def critical(self, t: str) -> str:  # rosso intenso su sfondo
        return self._s("1;97;41", t)

    def header(self, t: str) -> str:
        return self._s("1;97;44", t)

    def section(self, t: str) -> str:
        return self._s("1;96", t)  # bright cyan – alto contrasto

    def zone(self, t: str) -> str:
        """Nome zona: bianco brillante bold (97), non grigio."""
        return self._s("1;97", t)

    def zone_id(self, t: str) -> str:
        """ID zona: nero su ciano brillante – massimo contrasto."""
        if not self.enabled:
            return f"[{t}]"
        return f"\033[1;38;5;16;48;5;51m {t} \033[0m"

    def zone_strip(self, t: str) -> str:
        """Etichetta geografica su fascia blu scura, testo bianco bold."""
        if not self.enabled:
            return t
        return f"\033[1;97;48;5;17m {t} \033[0m"

    def raw_block(self, t: str) -> str:
        """Testo grezzo: chiaro su sfondo scuro, una riga per messaggio."""
        # conserva il testo ufficiale ma senza righe vuote ripetute
        cleaned = [ln.rstrip() for ln in t.splitlines() if ln.strip()]
        if not cleaned:
            cleaned = ["(vuoto)"]
        if not self.enabled:
            return "\n".join(cleaned)
        out_lines = []
        width = max(len(ln) for ln in cleaned)
        width = max(width, 40)
        for ln in cleaned:
            pad = ln.ljust(width)
            out_lines.append(f"\033[1;38;5;230;48;5;236m {pad} \033[0m")
        return "\n".join(out_lines)

    def badge(self, bg: int, t: str) -> str:
        """Badge con sfondo 256-color (testo nero o bianco a contrasto)."""
        if not self.enabled:
            return f"[{t}]"
        # testo nero su gialli/verdi chiari, bianco su rossi/arancio scuri
        fg = 16 if bg in (46, 82, 118, 154, 190, 226, 220, 214, 51, 87) else 231
        return f"\033[1;38;5;{fg};48;5;{bg}m {t} \033[0m"

    def paint_gafor(self, cat: str, label: str) -> str:
        c = cat.upper()[:1]
        if c == "O":
            return self.badge(46, label)  # verde
        if c == "D":
            return self.badge(226, label)  # giallo
        if c == "M":
            return self.badge(208, label)  # arancio
        if c == "X":
            return self.badge(196, label)  # rosso
        return self.badge(250, label)

    def paint_sea(self, level: int, text: str) -> str:
        # 0-1 verde, 2 ciano, 3 giallo, 4 arancio, 5+ rosso
        if level <= 1:
            return self.ok(text)
        if level == 2:
            return self.mild(text)
        if level == 3:
            return self.warn(text)
        if level == 4:
            return self.caution(text)
        return self.bad(text)

    def paint_bf(self, bf: int, text: str) -> str:
        if bf <= 3:
            return self.ok(text)
        if bf == 4:
            return self.warn(text)
        if bf <= 6:
            return self.caution(text)
        return self.bad(text)

    def paint_vis(self, level: int, text: str) -> str:
        if level >= 4:
            return self.ok(text)
        if level == 3:
            return self.warn(text)
        if level == 2:
            return self.caution(text)
        return self.bad(text)


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch_latest_message(channel: str, query: str, timeout: float = 25.0) -> dict[str, Any]:
    params = {
        "channelToken": channel,
        "fields": "all",
        "q": query,
        "limit": "1",
        "orderBy": "fields.date:desc",
    }
    url = f"{API_BASE}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Errore HTTP {e.code} recuperando il bollettino: {e.reason}") from e
    except urllib.error.URLError as e:
        raise SystemExit(f"Errore di rete: {e.reason}") from e

    items = data.get("items") or []
    if not items:
        raise SystemExit("Nessun messaggio trovato sul canale richiesto.")
    item = items[0]
    body = (item.get("fields") or {}).get("body") or ""
    # normalizza fine riga
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    date = (item.get("fields") or {}).get("date") or {}
    return {
        "name": item.get("name"),
        "id": item.get("id"),
        "date": date.get("value"),
        "body": body.strip(),
        "raw_item": item,
    }


# ---------------------------------------------------------------------------
# GAFOR parser
# ---------------------------------------------------------------------------

@dataclass
class GaforEntry:
    zones: list[str]
    primary: str  # es. O, D2, M5, O/D2, X
    rest: str  # modificatori e fenomeni
    raw: str


@dataclass
class GaforBulletin:
    header: str
    origin: str
    validity: str  # es. 1824 → 18-24 UTC
    issued: Optional[str]
    entries: list[GaforEntry] = field(default_factory=list)
    raw: str = ""
    source_date: Optional[str] = None
    source_name: Optional[str] = None


_ZONE_TOKEN = re.compile(
    r"^(\d{1,2})([NSEWO]{0,2})(?:/(\d{1,2})([NSEWO]{0,2})?)?$"
)
_CAT_START = re.compile(r"^(?:[ODMX]\d*(?:/[ODMX]\d*)?|=)")


def _expand_zone_token(tok: str) -> list[str]:
    """Espande '6/9', '2', '8E', '2N/12S' in lista zone."""
    tok = tok.strip().rstrip(",").strip()
    if not tok:
        return []
    m = _ZONE_TOKEN.match(tok)
    if not m:
        return [tok]
    a, sa, b, sb = m.group(1), m.group(2) or "", m.group(3), m.group(4) or ""
    if b is None:
        return [f"{int(a)}{sa}"]
    start, end = int(a), int(b)
    if start > end:
        start, end = end, start
    out: list[str] = []
    for n in range(start, end + 1):
        sector = ""
        if n == int(a) and sa:
            sector = sa
        elif n == int(b) and sb:
            sector = sb
        out.append(f"{n}{sector}")
    return out


def _parse_zones_and_cond(rest: str) -> tuple[list[str], str]:
    """Separa elenco zone dal resto della riga GAFOR."""
    # Unisci token finché sembrano zone (numeri, range, settori)
    parts = rest.split()
    zones: list[str] = []
    i = 0
    while i < len(parts):
        p = parts[i].strip()
        # "1," "13" o "6/9," 
        cleaned = p.rstrip(",")
        if _ZONE_TOKEN.match(cleaned) or re.match(r"^\d{1,2}[NSEWO]{0,2}/\d{1,2}[NSEWO]{0,2}$", cleaned):
            zones.extend(_expand_zone_token(cleaned))
            i += 1
            continue
        # token tipo "1,13" senza spazi
        if "," in cleaned and all(
            _ZONE_TOKEN.match(x) or not x
            for x in cleaned.split(",")
        ):
            for x in cleaned.split(","):
                if x:
                    zones.extend(_expand_zone_token(x))
            i += 1
            continue
        break
    cond = " ".join(parts[i:]).strip()
    # rimuovi trailing '=' di fine messaggio
    cond = re.sub(r"=+\s*$", "", cond).strip()
    return zones, cond


def _primary_category(cond: str) -> tuple[str, str]:
    """Estrae la categoria primaria (O, D2, M5, O/D2, X) e il resto."""
    m = re.match(r"^([ODMX]\d*(?:/[ODMX]\d*)?)(?:\s+(.*))?$", cond.strip(), re.I)
    if not m:
        return "", cond
    return m.group(1).upper(), (m.group(2) or "").strip()


def parse_gafor(body: str, source_date: Optional[str] = None, source_name: Optional[str] = None) -> GaforBulletin:
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    header = lines[0] if lines else ""
    origin = ""
    validity = ""
    issued = None

    # FBIY61 LIIB 041700
    hm = re.match(r"^FBIY61\s+(\S+)\s+(\d{6})", header, re.I)
    if hm:
        origin = hm.group(1)
        issued = hm.group(2)  # GGHHMM UTC del giorno di emissione (testata)

    entries: list[GaforEntry] = []
    for ln in lines:
        if ln.upper().startswith("GAFOR"):
            # GAFOR LIIB  1824  oppure GAFOR LIIB 0223 0612
            gm = re.match(r"^GAFOR\s+(\S+)\s+(?:(\d{4})\s+)?(\d{4})\s*$", ln, re.I)
            if gm:
                origin = origin or gm.group(1)
                validity = gm.group(3)
            continue
        if re.match(r"^(AAAA|BBBB)\b", ln, re.I):
            rest = re.sub(r"^(AAAA|BBBB)\s+", "", ln, flags=re.I)
            zones, cond = _parse_zones_and_cond(rest)
            primary, tail = _primary_category(cond)
            entries.append(GaforEntry(zones=zones, primary=primary or cond, rest=tail, raw=ln))

    return GaforBulletin(
        header=header,
        origin=origin,
        validity=validity,
        issued=issued,
        entries=entries,
        raw=body,
        source_date=source_date,
        source_name=source_name,
    )


def format_validity(v: str) -> str:
    if len(v) == 4 and v.isdigit():
        return f"{v[0:2]}–{v[2:4]} UTC"
    return v


def zone_parts(z: str) -> tuple[str, str]:
    """Ritorna (id_compatto, nome_geografico) per rendering ad alto contrasto."""
    m = re.match(r"^(\d{1,2})([A-Za-z]*)$", z)
    if not m:
        return z, z
    num, sec = m.group(1), m.group(2).upper()
    name = GAFOR_ZONE_NAMES.get(str(int(num)), f"Zona {num}")
    if sec:
        sec_it = SECTOR_NAMES.get(sec, sec)
        zid = f"Z{int(num):02d}{sec_it}"
        geo = f"{name}  ·  settore {sec_it}"
    else:
        zid = f"Z{int(num):02d}"
        geo = name
    return zid, geo


def zone_label(z: str) -> str:
    zid, geo = zone_parts(z)
    return f"{zid} · {geo}"


def describe_gafor_cond(primary: str, rest: str) -> str:
    parts: list[str] = []
    # categorie eventualmente composite O/D2
    cats = primary.split("/") if primary else []
    for c in cats:
        m = re.match(r"^([ODMX])(\d?)$", c.upper())
        if not m:
            continue
        letter, k = m.group(1), m.group(2)
        title, desc = GAFOR_CAT.get(letter, (letter, ""))
        if k:
            parts.append(f"{title} (k={k})")
        else:
            parts.append(title)
    if len(parts) > 1:
        cat_txt = " → ".join(parts)
    else:
        cat_txt = parts[0] if parts else primary

    mods: list[str] = []
    wx: list[str] = []
    for tok in rest.split():
        u = tok.upper().rstrip(".,;")
        # sotto-categoria locale tipo D3, M4 dopo LOC/MON
        if re.match(r"^[ODMX]\d$", u):
            letter, k = u[0], u[1]
            title, _ = GAFOR_CAT.get(letter, (letter, ""))
            mods.append(f"{title} k={k}")
            continue
        if u in MOD_IT:
            mods.append(MOD_IT[u])
            continue
        if u in WX_IT:
            wx.append(WX_IT[u])
            continue
        # numeri isolati spesso legati a fenomeni (es. 10BR → già splittato male)
        if re.match(r"^\d{2}[A-Z]{2,}$", u):
            code = u[2:]
            wx.append(WX_IT.get(code, code.lower()))
            continue
        if u and u not in {"=", "/"}:
            mods.append(tok.lower())

    bits = [cat_txt]
    if mods:
        bits.append(" · ".join(mods))
    if wx:
        bits.append("fenomeni: " + ", ".join(wx))
    return " — ".join(bits)


# ---------------------------------------------------------------------------
# METEOMAR parser
# ---------------------------------------------------------------------------

@dataclass
class SeaForecast:
    area: str
    text: str
    wind_dir: Optional[str] = None
    wind_bf: Optional[int] = None
    sea_level: Optional[int] = None
    sea_label: Optional[str] = None
    vis_level: Optional[int] = None
    vis_label: Optional[str] = None
    has_storm: bool = False
    has_rain: bool = False
    has_fog: bool = False
    trend: Optional[str] = None


@dataclass
class MeteomarBulletin:
    header: str
    issued_line: str
    valid_until: str
    warnings: list[str] = field(default_factory=list)
    situation: str = ""
    areas: list[SeaForecast] = field(default_factory=list)
    extended: list[str] = field(default_factory=list)
    raw: str = ""
    source_date: Optional[str] = None
    source_name: Optional[str] = None
    italy_only_count: int = 0


ITALIAN_SEAS = {
    "MAR LIGURE",
    "MAR DI CORSICA",
    "MAR DI SARDEGNA",
    "CANALE DI SARDEGNA",
    "TIRRENO SETTENTRIONALE",
    "TIRRENO CENTRALE OVEST",
    "TIRRENO CENTRALE EST",
    "TIRRENO MERIDIONALE OVEST",
    "TIRRENO MERIDIONALE EST",
    "STRETTO DI SICILIA",
    "IONIO MERIDIONALE",
    "IONIO SETTENTRIONALE",
    "ADRIATICO MERIDIONALE",
    "ADRIATICO CENTRALE",
    "ADRIATICO SETTENTRIONALE",
}

# Direzioni vento in italiano (token grezzi del bollettino)
WIND_DIRS = [
    "NORDOVEST", "NORDEST", "SUDOVEST", "SUDEST",
    "NORD", "SUD", "EST", "OVEST", "VARIABILE",
]


def _detect_sea(text: str) -> tuple[Optional[int], Optional[str]]:
    low = text.lower()
    # frasi composte prima (poco/molto mosso prima di mosso)
    ordered = sorted(SEA_STATE_ORDER, key=lambda x: -len(x[0]))
    for pat, level, label in ordered:
        if re.search(pat, low):
            return level, label
    # codifica "MARE 3" nella sezione 4
    m = re.search(r"\bMARE\s+(\d)\b", text, re.I)
    if m:
        lvl = int(m.group(1))
        labels = {
            0: "calmo",
            1: "quasi calmo",
            2: "poco mosso",
            3: "mosso",
            4: "molto mosso",
            5: "agitato",
            6: "molto agitato",
            7: "grosso",
            8: "molto grosso",
            9: "tempestoso",
        }
        return lvl, labels.get(lvl, f"mare {lvl}")
    return None, None


def _detect_vis(text: str) -> tuple[Optional[int], Optional[str]]:
    low = text.lower()
    # match non sovrapposti, frasi più lunghe prima (molto buona prima di buona)
    ordered = sorted(VIS_ORDER, key=lambda x: -len(x[2]))
    spans: list[tuple[int, int, int, str]] = []
    for pat, level, label in ordered:
        for m in re.finditer(pat, low):
            a, b = m.start(), m.end()
            if any(a < eb and b > ea for ea, eb, _, _ in spans):
                continue
            spans.append((a, b, level, label))
    if not spans:
        return None, None
    # peggiore (livello più basso) per colore di allerta
    spans.sort(key=lambda x: x[2])
    return spans[0][2], spans[0][3]


def _detect_wind(text: str) -> tuple[Optional[str], Optional[int]]:
    # es. "NORDOVEST 3", "SUDEST 4 IN INTENSIFICAZIONE", "VARIABILE 2"
    for d in WIND_DIRS:
        m = re.search(rf"\b{d}\s+(\d{{1,2}})\b", text, re.I)
        if m:
            return d.title().replace("Nordovest", "Nord-ovest").replace("Nordest", "Nord-est") \
                .replace("Sudovest", "Sud-ovest").replace("Sudest", "Sud-est"), int(m.group(1))
    # solo forza numerica rara
    m = re.search(r"\bVENTO\s+(\d{1,2})\b", text, re.I)
    if m:
        return None, int(m.group(1))
    return None, None


def _colorize_meteomar_text(c: Colors, text: str) -> str:
    """Colora termini chiave dentro un pezzo di testo METEOMAR."""
    if not c.enabled:
        return text

    def sea_sub(m: re.Match[str]) -> str:
        raw = m.group(0)
        lvl, _ = _detect_sea(raw)
        if lvl is None:
            return raw
        return c.paint_sea(lvl, raw)

    def vis_sub(m: re.Match[str]) -> str:
        raw = m.group(0)
        lvl, _ = _detect_vis(raw)
        if lvl is None:
            return raw
        return c.paint_vis(lvl, raw)

    def wind_sub(m: re.Match[str]) -> str:
        bf = int(m.group(2))
        return f"{m.group(1)}{c.paint_bf(bf, m.group(2))}"

    out = text
    # mare: frasi più lunghe prima, per non colorare "mosso" dentro "poco mosso"
    for pat, _, _ in sorted(SEA_STATE_ORDER, key=lambda x: -len(x[0])):
        out = re.sub(pat, sea_sub, out, flags=re.I)
    for pat, _, _ in sorted(VIS_ORDER, key=lambda x: -len(x[2])):
        out = re.sub(pat, vis_sub, out, flags=re.I)
    for d in WIND_DIRS:
        out = re.sub(rf"\b({d}\s+)(\d{{1,2}})\b", wind_sub, out, flags=re.I)

    # fenomeni pericolosi
    for bad in (r"\bTEMPORALI?\b", r"\bBURRASCHE?\b", r"\bTEMPORALE\b", r"\bGROPPI\b"):
        out = re.sub(bad, lambda m: c.bad(m.group(0)), out, flags=re.I)
    for rain in (r"\bPIOGGE?\b", r"\bROVESCI\b", r"\bNUBI\b"):
        out = re.sub(rain, lambda m: c.warn(m.group(0)), out, flags=re.I)
    for fog in (r"\bNEBBIA\b", r"\bFOSCHIA\b"):
        out = re.sub(fog, lambda m: c.caution(m.group(0)), out, flags=re.I)
    out = re.sub(r"\bNIL\b", lambda m: c.ok(m.group(0)), out, flags=re.I)
    return out


def parse_meteomar(
    body: str,
    source_date: Optional[str] = None,
    source_name: Optional[str] = None,
    italy_only: bool = True,
) -> MeteomarBulletin:
    # unisci righe spezzate del bollettino ufficiale
    text = body.replace("\r", "")
    # normalizza spazi multipli ma conserva struttura sezioni
    lines = [ln.strip() for ln in text.split("\n")]
    # ricomponi: le righe non-vuote consecutive formano paragrafi; i "-AREA:" iniziano blocchi
    joined = " ".join(ln for ln in lines if ln)
    joined = re.sub(r"\s+", " ", joined)

    header_m = re.search(r"(METEOMAR\s+\d{8}\s*-\s*\d{4}Z)", joined, re.I)
    header = header_m.group(1) if header_m else (lines[0] if lines else "METEOMAR")

    issued_m = re.search(
        r"EMESSO ALLE ORE\s+([0-9]{2}:[0-9]{2}/UTC)\s+DEL GIORNO\s+(.+?)\s+E\s+VALIDO",
        joined,
        re.I,
    )
    if not issued_m:
        issued_m = re.search(
            r"EMESSO ALLE ORE\s+([0-9:]+/UTC)\s+DEL GIORNO\s+([^.]+?)\.",
            joined,
            re.I,
        )
    issued_line = (
        f"{issued_m.group(2).strip()} · {issued_m.group(1)}"
        if issued_m
        else ""
    )

    valid_m = re.search(r"VALIDO FINO ALLE\s+([0-9]{2}:[0-9]{2}/UTC[^.]*)\.", joined, re.I)
    valid_until = valid_m.group(1).strip() if valid_m else ""

    # 1. AVVISI
    warnings: list[str] = []
    wm = re.search(r"1\.\s*AVVISI:\s*(.*?)\s*2\.\s*SITUAZIONE:", joined, re.I | re.S)
    if wm:
        block = wm.group(1)
        for part in re.split(r"(?=(?:TEMPORALI|BURRASCHE)\s)", block, flags=re.I):
            part = part.strip(" .;")
            if part:
                warnings.append(re.sub(r"\s+", " ", part))

    # 2. SITUAZIONE
    situation = ""
    sm = re.search(r"2\.\s*SITUAZIONE:\s*(.*?)\s*3\.\s*PREVISIONE", joined, re.I | re.S)
    if sm:
        situation = re.sub(r"\s+", " ", sm.group(1)).strip()

    # 3. PREVISIONE per area: spezza su "-NOME:"
    areas: list[SeaForecast] = []
    pm = re.search(
        r"3\.\s*PREVISIONE\s+VALIDA.*?:\s*(.*?)\s*4\.\s*VENTO E MOTO ONDOSO",
        joined,
        re.I | re.S,
    )
    if not pm:
        pm = re.search(r"3\.\s*PREVISIONE.*?:\s*(.*?)(?:4\.|FINE METEOMAR)", joined, re.I | re.S)

    forecast_block = pm.group(1) if pm else ""
    # Split solo su vere aree marine (evita di spezzare su "-POCO MOSSO / TENDENZA:")
    area_split = re.compile(
        r"\s*-\s*(?="
        r"(?:MAR|MARE|CANALE|TIRRENO|STRETTO|IONIO|ADRIATICO|GOLFO)\b"
        r"[A-ZÀ-Ù' /]*:)",
        re.I,
    )
    chunks = area_split.split(forecast_block)
    for ch in chunks:
        ch = ch.strip(" -")
        if not ch or ":" not in ch:
            continue
        area, _, body_txt = ch.partition(":")
        area = area.strip().upper()
        body_txt = body_txt.strip(" .")
        if not area or len(area) < 3:
            continue

        if italy_only and area not in ITALIAN_SEAS:
            # escludi Alboran, Egeo, Levante, ecc.
            continue

        # separa tendenza (può contenere altri "-")
        trend = None
        tm = re.search(r"/\s*TENDENZA:\s*(.*)$", body_txt, re.I)
        if tm:
            trend = tm.group(1).strip(" .")
            main = body_txt[: tm.start()].strip(" .")
        else:
            main = body_txt

        wind_dir, wind_bf = _detect_wind(main)
        sea_level, sea_label = _detect_sea(main)
        vis_level, vis_label = _detect_vis(main)
        low = main.lower()

        areas.append(
            SeaForecast(
                area=area.title().replace(" Di ", " di ").replace(" Del ", " del "),
                text=main,
                wind_dir=wind_dir,
                wind_bf=wind_bf,
                sea_level=sea_level,
                sea_label=sea_label,
                vis_level=vis_level,
                vis_label=vis_label,
                has_storm=bool(re.search(r"temporal", low)),
                has_rain=bool(re.search(r"piogg", low)),
                has_fog=bool(re.search(r"nebbia|foschia", low)),
                trend=trend,
            )
        )

    # 4. estensione 12h (riassunto grezzo per mari italiani)
    extended: list[str] = []
    em = re.search(r"4\.\s*VENTO E MOTO ONDOSO(.*?)\s*FINE METEOMAR", joined, re.I | re.S)
    if em:
        eblock = em.group(1)
        for ch in area_split.split(eblock):
            ch = ch.strip(" .")
            if not ch or ":" not in ch:
                continue
            area, _, body_txt = ch.partition(":")
            area_u = area.strip().upper()
            if italy_only:
                ok = any(area_u == s or area_u in s or s in area_u for s in ITALIAN_SEAS)
                if not ok:
                    continue
            extended.append(f"{area.strip()}: {body_txt.strip()}")

    return MeteomarBulletin(
        header=header,
        issued_line=issued_line,
        valid_until=valid_until,
        warnings=warnings,
        situation=situation,
        areas=areas,
        extended=extended,
        raw=body,
        source_date=source_date,
        source_name=source_name,
        italy_only_count=len(areas),
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def rule(c: Colors, char: str = "─", width: int = 72) -> str:
    return c.dim(char * width)


def wrap(text: str, indent: int = 0, width: int = 72) -> str:
    return textwrap.fill(
        text,
        width=width,
        initial_indent=" " * indent,
        subsequent_indent=" " * indent,
    )


def worst_gafor_cat(entries: Iterable[GaforEntry]) -> str:
    order = {"O": 0, "D": 1, "M": 2, "X": 3}
    worst = "O"
    for e in entries:
        for part in re.findall(r"[ODMX]", e.primary.upper()):
            if order.get(part, 0) > order.get(worst, 0):
                worst = part
    return worst


def render_gafor(b: GaforBulletin, c: Colors) -> str:
    lines: list[str] = []
    title = " GAFOR · General Aviation Forecast (Italia) "
    lines.append(c.header(title.center(72)))
    lines.append(rule(c))

    meta = []
    if b.source_date:
        meta.append(f"pubblicato: {b.source_date}")
    if b.origin:
        meta.append(f"centro: {b.origin}")
    if b.validity:
        meta.append(f"validità: {format_validity(b.validity)}")
    if b.issued:
        meta.append(f"testata: {b.issued}")
    if meta:
        lines.append(c.dim(" · ".join(meta)))
        lines.append("")

    # --- RAW ufficiale (sempre, prima della decodifica) ---
    lines.append(c.section("▸ TESTO UFFICIALE (RAW)"))
    if b.source_name:
        lines.append(c.dim(f"  file: {b.source_name}"))
    raw_txt = b.raw.strip() if b.raw else "(vuoto)"
    lines.append(c.raw_block(raw_txt))
    lines.append("")

    # legenda mini
    lines.append(c.section("▸ DECODIFICA PER ZONA"))
    lines.append(
        c.dim("Legenda: ")
        + c.paint_gafor("O", "O Favorevole")
        + " "
        + c.paint_gafor("D", "D Difficile")
        + " "
        + c.paint_gafor("M", "M Marginale")
        + " "
        + c.paint_gafor("X", "X Critico")
    )
    lines.append(c.dim("          k=1…5 = subcategoria (peggiora al crescere di k)"))
    lines.append(
        c.dim(
            "          Nomi geografici = aiuto lettura dalla mappa ufficiale AM "
            "(Istr. MET 38/87); nel raw contano solo i numeri di zona."
        )
    )
    lines.append("")

    if not b.entries:
        lines.append(c.warn("Nessuna riga di previsione decodificata."))
        lines.append(rule(c))
        lines.append(c.dim("Fonte: Servizio Meteorologico Aeronautica Militare · meteoam.it/it/gafor"))
        return "\n".join(lines)

    # mappa zona → entry (ultima vince se duplicate)
    zone_map: dict[str, GaforEntry] = {}
    for e in b.entries:
        for z in e.zones:
            zone_map[z] = e

    # riepilogo peggiore
    w = worst_gafor_cat(b.entries)
    wtitle = GAFOR_CAT.get(w, (w, ""))[0]
    lines.append(
        f"Condizione più severa nel bollettino: {c.paint_gafor(w, f'{w} {wtitle}')}"
    )
    lines.append(rule(c))

    # ordina zone numericamente
    def zkey(z: str) -> tuple[int, str]:
        m = re.match(r"(\d+)", z)
        return (int(m.group(1)) if m else 99, z)

    for z in sorted(zone_map.keys(), key=zkey):
        e = zone_map[z]
        badge = c.paint_gafor(e.primary[:1] if e.primary else "?", e.primary or "?")
        zid, geo = zone_parts(z)
        desc = describe_gafor_cond(e.primary, e.rest)

        # riga zona ad alto contrasto: [cat] [Znn] nome su fascia scura
        lines.append(f"{badge} {c.zone_id(zid)} {c.zone_strip(geo)}")
        lines.append(wrap(desc, indent=4, width=72))
        # evidenzia fenomeni nel resto
        if e.rest:
            colored_rest = e.rest
            if c.enabled:
                for code, _ in WX_IT.items():
                    colored_rest = re.sub(
                        rf"\b{code}\b",
                        lambda m, code=code: c.bad(m.group(0))
                        if code in {"TSRA", "TS", "SQ", "GR", "FG"}
                        else c.warn(m.group(0)),
                        colored_rest,
                        flags=re.I,
                    )
            lines.append(c.dim("    codici: ") + c.zone(colored_rest))
        lines.append("")

    # zone non citate esplicitamente? (a volte O= su range copre tutto)
    covered_nums = {re.match(r"(\d+)", z).group(1) for z in zone_map if re.match(r"(\d+)", z)}  # type: ignore
    missing = [n for n in map(str, range(1, 14)) if n not in covered_nums]
    if missing:
        lines.append(c.dim(f"(zone non esplicitate nel messaggio: {', '.join(missing)})"))

    lines.append(rule(c))
    lines.append(c.dim("Fonte: Servizio Meteorologico Aeronautica Militare · meteoam.it/it/gafor"))
    return "\n".join(lines)


def _area_severity(a: SeaForecast) -> int:
    score = 0
    if a.sea_level is not None:
        score = max(score, a.sea_level)
    if a.wind_bf is not None:
        # mappa bf→scala simile
        score = max(score, {0: 0, 1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 7: 6}.get(a.wind_bf, 6))
    if a.has_storm:
        score = max(score, 5)
    if a.vis_level is not None and a.vis_level <= 1:
        score = max(score, 4)
    return score


def render_meteomar(b: MeteomarBulletin, c: Colors) -> str:
    lines: list[str] = []
    title = " METEOMAR · Bollettino del tempo sul Mediterraneo "
    lines.append(c.header(title.center(72)))
    lines.append(rule(c))

    meta = []
    if b.source_date:
        meta.append(f"pubblicato: {b.source_date}")
    if b.header:
        meta.append(b.header)
    if b.issued_line:
        meta.append(f"emesso: {b.issued_line}")
    if b.valid_until:
        meta.append(f"valido fino: {b.valid_until}")
    for m in meta:
        lines.append(c.dim(m))
    lines.append("")

    # Avvisi
    lines.append(c.section("▸ AVVISI"))
    if not b.warnings:
        lines.append("  " + c.ok("Nessun avviso decodificato"))
    else:
        for w in b.warnings:
            if re.search(r"\bNIL\b", w, re.I):
                lines.append("  " + _colorize_meteomar_text(c, w))
            else:
                lines.append("  " + c.bad("⚠ ") + _colorize_meteomar_text(c, w))
    lines.append("")

    # Situazione
    if b.situation:
        lines.append(c.section("▸ SITUAZIONE SINOTTICA"))
        lines.append(wrap(b.situation, indent=2, width=72))
        lines.append("")

    # Mari italiani
    lines.append(c.section("▸ PREVISIONE MARI ITALIANI"))
    lines.append(
        c.dim("  Colori: mare/vento/visibilità  ")
        + c.ok("buono")
        + c.dim(" · ")
        + c.warn("attenzione")
        + c.dim(" · ")
        + c.caution("difficile")
        + c.dim(" · ")
        + c.bad("severo")
    )
    lines.append("")

    if not b.areas:
        lines.append(c.warn("  Nessuna area italiana decodificata (provare --all-seas)."))
    else:
        for a in sorted(b.areas, key=lambda x: (-_area_severity(x), x.area)):
            sev = _area_severity(a)
            if sev >= 5:
                mark = c.bad("●")
            elif sev >= 3:
                mark = c.caution("●")
            elif sev >= 2:
                mark = c.warn("●")
            else:
                mark = c.ok("●")

            chips: list[str] = []
            if a.wind_bf is not None:
                wtxt = f"{a.wind_dir or 'Vento'} {a.wind_bf} Bft"
                chips.append(c.paint_bf(a.wind_bf, wtxt))
            if a.sea_label and a.sea_level is not None:
                chips.append(c.paint_sea(a.sea_level, a.sea_label))
            if a.vis_label and a.vis_level is not None:
                chips.append(c.paint_vis(a.vis_level, f"vis. {a.vis_label}"))
            if a.has_storm:
                chips.append(c.bad("temporali"))
            elif a.has_rain:
                chips.append(c.warn("pioggia"))
            if a.has_fog:
                chips.append(c.caution("nebbia/foschia"))

            lines.append(f"  {mark} {c.bold(a.area)}")
            if chips:
                lines.append("      " + "  ".join(chips))
            lines.append(wrap(_colorize_meteomar_text(c, a.text), indent=6, width=72))
            if a.trend:
                lines.append(
                    c.dim("      tendenza: ")
                    + _colorize_meteomar_text(c, a.trend)
                )
            lines.append("")

    if b.extended:
        lines.append(c.section("▸ TENDENZA VENTO/MARE (intervalli 12 h successivi)"))
        for e in b.extended:
            lines.append(wrap(_colorize_meteomar_text(c, e), indent=2, width=72))
        lines.append("")

    lines.append(rule(c))
    lines.append(c.dim("Fonte: CNMCA / Servizio Meteorologico AM · meteoam.it/it/messaggio-meteomar"))
    return "\n".join(lines)


def bulletin_to_json(gafor: Optional[GaforBulletin], meteo: Optional[MeteomarBulletin]) -> str:
    def entry_dict(e: GaforEntry) -> dict:
        return {
            "zones": e.zones,
            "zones_labels": [zone_label(z) for z in e.zones],
            "category": e.primary,
            "detail": e.rest,
            "description": describe_gafor_cond(e.primary, e.rest),
            "raw": e.raw,
        }

    out: dict[str, Any] = {"generated_at": datetime.now(timezone.utc).isoformat()}
    if gafor:
        out["gafor"] = {
            "source_date": gafor.source_date,
            "source_name": gafor.source_name,
            "origin": gafor.origin,
            "validity": gafor.validity,
            "validity_label": format_validity(gafor.validity) if gafor.validity else None,
            "entries": [entry_dict(e) for e in gafor.entries],
            "raw": gafor.raw,
        }
    if meteo:
        out["meteomar"] = {
            "source_date": meteo.source_date,
            "source_name": meteo.source_name,
            "header": meteo.header,
            "issued": meteo.issued_line,
            "valid_until": meteo.valid_until,
            "warnings": meteo.warnings,
            "situation": meteo.situation,
            "areas": [asdict(a) for a in meteo.areas],
            "extended": meteo.extended,
            "raw": meteo.raw,
        }
    return json.dumps(out, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def load_bulletins(
    *,
    show_gafor: bool = True,
    show_meteomar: bool = True,
    italy_only: bool = True,
    timeout: float = 25.0,
) -> tuple[Optional[GaforBulletin], Optional[MeteomarBulletin]]:
    gafor_b: Optional[GaforBulletin] = None
    meteo_b: Optional[MeteomarBulletin] = None
    if show_gafor:
        msg = fetch_latest_message(GAFOR_CHANNEL, GAFOR_QUERY, timeout=timeout)
        gafor_b = parse_gafor(msg["body"], msg.get("date"), msg.get("name"))
    if show_meteomar:
        msg = fetch_latest_message(METEOMAR_CHANNEL, METEOMAR_QUERY, timeout=timeout)
        meteo_b = parse_meteomar(
            msg["body"],
            msg.get("date"),
            msg.get("name"),
            italy_only=italy_only,
        )
    return gafor_b, meteo_b


def serve_html(
    host: str,
    port: int,
    *,
    italy_only: bool = True,
    timeout: float = 25.0,
    refresh_seconds: int = 0,
) -> None:
    """HTTP server che rigenera le pagine a ogni richiesta (sempre aggiornate)."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from maps_and_html import (
        render_gafor_html,
        render_index_html,
        render_meteomar_html,
    )

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                kind = "index"
            elif path in ("/gafor.html", "/gafor"):
                kind = "gafor"
            elif path in ("/meteomar.html", "/meteomar"):
                kind = "meteomar"
            else:
                self.send_error(404, "Not found")
                return
            try:
                need_g = kind in ("index", "gafor")
                need_m = kind in ("index", "meteomar")
                gafor_b, meteo_b = load_bulletins(
                    show_gafor=need_g or kind == "index",
                    show_meteomar=need_m or kind == "index",
                    italy_only=italy_only,
                    timeout=timeout,
                )
                if kind == "gafor":
                    assert gafor_b is not None
                    body = render_gafor_html(gafor_b, refresh_seconds=refresh_seconds)
                elif kind == "meteomar":
                    assert meteo_b is not None
                    body = render_meteomar_html(meteo_b, refresh_seconds=refresh_seconds)
                else:
                    body = render_index_html(gafor_b, meteo_b, refresh_seconds=refresh_seconds)
                data = body.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
            except Exception as e:
                err = f"<h1>Errore</h1><pre>{e}</pre>".encode("utf-8")
                self.send_response(502)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(err)))
                self.end_headers()
                self.wfile.write(err)

    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"Server bollettini su http://{host}:{port}/  (Ctrl+C per uscire)", file=sys.stderr)
    print(f"  GAFOR     → http://{host}:{port}/gafor.html", file=sys.stderr)
    print(f"  METEOMAR  → http://{host}:{port}/meteomar.html", file=sys.stderr)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStop.", file=sys.stderr)
    finally:
        httpd.server_close()


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Ultimi bollettini GAFOR e METEOMAR per l'Italia, con codice colore.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """\
            Esempi:
              %(prog)s
              %(prog)s --gafor
              %(prog)s --meteomar --all-seas
              %(prog)s --raw
              %(prog)s --json > bollettini.json
              %(prog)s --html
              %(prog)s --html --html-dir ./pub --refresh 1800
              %(prog)s --serve --port 8080
            """
        ),
    )
    p.add_argument("--gafor", action="store_true", help="mostra solo GAFOR")
    p.add_argument("--meteomar", action="store_true", help="mostra solo METEOMAR")
    p.add_argument("--raw", action="store_true", help="stampa il testo grezzo ufficiale")
    p.add_argument("--json", action="store_true", help="output JSON strutturato")
    p.add_argument("--no-color", action="store_true", help="disabilita colori ANSI")
    p.add_argument(
        "--html",
        action="store_true",
        help="genera pagine HTML statiche (gafor.html, meteomar.html, index.html)",
    )
    p.add_argument(
        "--html-dir",
        default="html",
        help="directory output HTML (default: ./html)",
    )
    p.add_argument(
        "--refresh",
        type=int,
        default=0,
        metavar="SEC",
        help="meta-refresh nelle pagine HTML (secondi; 0=disattivo)",
    )
    p.add_argument(
        "--serve",
        action="store_true",
        help="avvia server HTTP che rigenera le pagine a ogni richiesta",
    )
    p.add_argument("--host", default="127.0.0.1", help="host per --serve (default 127.0.0.1)")
    p.add_argument("--port", type=int, default=8080, help="porta per --serve (default 8080)")
    p.add_argument(
        "--all-seas",
        action="store_true",
        help="METEOMAR: includi tutti i mari del Mediterraneo (non solo Italia)",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=25.0,
        help="timeout rete in secondi (default 25)",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="con --html non stampare anche il report a terminale",
    )
    args = p.parse_args(argv)

    if args.serve:
        serve_html(
            args.host,
            args.port,
            italy_only=not args.all_seas,
            timeout=args.timeout,
            refresh_seconds=args.refresh,
        )
        return 0

    show_gafor = args.gafor or not args.meteomar
    show_meteomar = args.meteomar or not args.gafor
    # se entrambi flag assenti → entrambi True; se uno solo → solo quello
    if args.gafor and not args.meteomar:
        show_meteomar = False
    if args.meteomar and not args.gafor:
        show_gafor = False

    # HTML richiede sempre entrambi se non specificato un solo bollettino
    if args.html and not args.gafor and not args.meteomar:
        show_gafor = True
        show_meteomar = True

    c = Colors(enabled=False if args.no_color else None)

    gafor_b, meteo_b = load_bulletins(
        show_gafor=show_gafor,
        show_meteomar=show_meteomar,
        italy_only=not args.all_seas,
        timeout=args.timeout,
    )

    if args.json:
        print(bulletin_to_json(gafor_b, meteo_b))
        return 0

    if args.raw:
        if gafor_b:
            print("===== GAFOR =====")
            print(gafor_b.raw)
            print()
        if meteo_b:
            print("===== METEOMAR =====")
            print(meteo_b.raw)
        return 0

    if args.html:
        from maps_and_html import write_html_pages

        out = Path(args.html_dir)
        written = write_html_pages(
            out,
            gafor_b,
            meteo_b,
            refresh_seconds=args.refresh,
        )
        for path in written:
            print(f"Scritto: {path.resolve()}", file=sys.stderr)
        if args.quiet:
            return 0

    blocks: list[str] = []
    if gafor_b:
        blocks.append(render_gafor(gafor_b, c))
    if meteo_b:
        blocks.append(render_meteomar(meteo_b, c))
    if blocks and not (args.html and args.quiet):
        print("\n\n".join(blocks))
    return 0


if __name__ == "__main__":
    sys.exit(main())
