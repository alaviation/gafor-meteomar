# GAFOR & METEOMAR (Italia)

Script CLI che scarica e presenta **gli ultimi bollettini ufficiali** GAFOR e METEOMAR dell’Aeronautica Militare, con **codice colore** per leggere le condizioni a colpo d’occhio.

## Pubblicazione su GitHub Pages

Le pagine HTML sono generate da **GitHub Actions** (ogni 6 ore + a ogni push) e pubblicate su **GitHub Pages**: non serve shell sull’hosting.

Dopo il primo setup le URL tipiche sono:

- `https://TUO_UTENTE.github.io/NOME_REPO/`
- `https://TUO_UTENTE.github.io/NOME_REPO/gafor.html`
- `https://TUO_UTENTE.github.io/NOME_REPO/meteomar.html`

## Requisiti

- Python 3.8+ (solo libreria standard)
- Connessione a Internet (`cm.meteoam.it`)

## Uso

```bash
# Entrambi i bollettini (default, terminale)
python3 gafor_meteomar.py

# Solo GAFOR / solo METEOMAR
python3 gafor_meteomar.py --gafor
python3 gafor_meteomar.py --meteomar

# Tutto il Mediterraneo (non solo mari italiani)
python3 gafor_meteomar.py --meteomar --all-seas

# Testo grezzo / JSON
python3 gafor_meteomar.py --raw
python3 gafor_meteomar.py --json

# Pagine HTML statiche (con cartine colorate)
python3 gafor_meteomar.py --html --quiet
# → html/gafor.html  html/meteomar.html  html/index.html

# Aggiornamento automatico ogni 30 min (meta-refresh nel browser)
python3 gafor_meteomar.py --html --refresh 1800 --quiet

# Server sempre aggiornato (rigenera i dati a ogni visita)
python3 gafor_meteomar.py --serve --port 8080
# → http://127.0.0.1:8080/gafor.html
# → http://127.0.0.1:8080/meteomar.html
```

### Aggiornare le pagine HTML periodicamente (cron)

```bash
*/30 * * * * cd /percorso/Gafor && python3 gafor_meteomar.py --html --quiet
```

## Codice colore

### GAFOR (categorie ICAO / AM)

| Badge | Significato |
|-------|-------------|
| **O** verde | Favorevole (VFR agevole) |
| **D** giallo | Difficile (subcategoria k=1…5) |
| **M** arancio | Marginale |
| **X** rosso | Critico (IMC / VFR sconsigliato) |

### Zone GAFOR (13 MET zones – mappa ufficiale AM)

Nel bollettino compaiono **solo i numeri**. Le etichette geografiche nello script
derivano dalla cartina ufficiale *Istr. MET 38/87* (file `gafor_zone_map.png`):

| Zona | Area |
|------|------|
| 1 | Alpi settentrionali |
| 2 | Alpi NE / Triveneto |
| 3 | Padania est / alto Adriatico |
| 4 | Medio Adriatico / Appennino centro-nord |
| 5 | Puglia / basso Adriatico |
| 6 | Italia centrale (adriatico-appenninico) |
| 7 | Calabria / estremo Sud peninsulare |
| 8 | Mar Ionio |
| 9 | Sicilia |
| 10 | Tirreno meridionale / Sardegna est |
| 11 | Mar di Sardegna / Sardegna ovest |
| 12 | Tirreno centrale |
| 13 | Alpi occidentali / Piemonte–Liguria |

Mappa: [meteoam.it/it/gafor](https://www.meteoam.it/it/gafor) · `gafor_zone_map.png`

### METEOMAR

- **Mare** (scala Douglas): calmo → grosso (verde → rosso)
- **Vento** (Beaufort): 0–3 verde, 4 giallo, 5–6 arancio, ≥7 rosso
- **Visibilità**: ottima/buona → pessima
- **Avvisi** (temporali/burrasche): evidenziati; `NIL` in verde

## Fonti

Messaggi live dal content API di [meteoam.it](https://www.meteoam.it):

- GAFOR: canale Integration-Message `MESSAGGI/GAFOR/…`
- METEOMAR: `MESSAGGI/MSG4/FXIY61…` (CNMCA)

Uso informativo: verificare sempre i bollettini ufficiali prima di attività di volo o navigazione.
