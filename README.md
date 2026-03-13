# 🎬 Video Downloader

En självhostad videodownloader med webbgränssnitt som stödjer TikTok, Instagram, Facebook, X/Twitter, YouTube och mer.

## ✨ Funktioner

- 📱 Fungerar på mobil (iPhone/Safari) och PC
- 🎥 Laddar ner i bästa tillgängliga kvalitet (H.264 + AAC)
- 🔄 Realtids-progressbar
- 🧅 Tor-proxy för TikTok och Facebook
- 🍪 Cookie-stöd för inloggningsskyddade videos
- 🐳 Docker-stöd

## 📦 Plattformar som stöds

| Plattform | Fungerar | Kräver cookies |
|-----------|----------|----------------|
| TikTok | ✅ | Nej |
| Instagram | ✅ | Nej* |
| Facebook | ✅ | Nej* |
| X / Twitter | ✅ | Rekommenderas |
| YouTube | ✅ | Nej |
| Övriga | ✅ | Beror på sajt |

*Privata videos kräver cookies

## 🚀 Kom igång med Docker

### Krav
- [Docker](https://docs.docker.com/get-docker/)
- [Docker Compose](https://docs.docker.com/compose/install/)

### Installation

```bash
# Klona repot
git clone https://github.com/zaplutus/Downed.git
cd Downed

# Bygg och starta
docker compose up -d

# Följ loggar
docker compose logs -f
```

Öppna sedan **http://localhost:5000** i webbläsaren.

### Cookies (valfritt men rekommenderas för X/Twitter)

1. Installera tillägget **"Get cookies.txt LOCALLY"** i Chrome eller Firefox
2. Logga in på den sajt du vill ladda ner från
3. Exportera cookies och spara som `cookies.txt` i projektmappen
4. Avkommentera cookies-raden i `docker-compose.yml`:
   ```yaml
   - ./cookies.txt:/app/cookies.txt:ro
   ```
5. Starta om: `docker compose restart`

## 🛠️ Manuell installation (utan Docker)

### Krav
- Python 3.12+
- ffmpeg
- Tor

```bash
# Klona repot
git clone https://github.com/zaplutus/Downed.git
cd Downed

# Skapa virtuell miljö
python3 -m venv venv
source venv/bin/activate

# Installera beroenden
pip install -r requirements.txt

# Starta
./start.sh
```

## 📁 Projektstruktur

```
videodownloader/
├── app.py                  # Flask-applikation
├── requirements.txt        # Python-beroenden
├── Dockerfile
├── docker-compose.yml
├── docker-entrypoint.sh    # Startar Tor + gunicorn
├── start.sh                # Manuell start utan Docker
├── static/                 # Nedladdade filer (skapas automatiskt)
└── cookies.txt             # Din cookies-fil (lägg till själv, committas ej)
```

## ⚙️ Konfiguration

Miljövariabler som kan sättas i `docker-compose.yml`:

| Variabel | Standard | Beskrivning |
|----------|----------|-------------|
| `PROXY` | `socks5://127.0.0.1:9050` | Tor-proxy-adress |
| `COOKIES_PATH` | `/app/cookies.txt` | Sökväg till cookies-fil |
| `STATE_FILE` | `/app/state.json` | Sökväg till state-fil |
| `STATIC_DIR` | `/app/static` | Mapp för nedladdade filer |

## 🔒 Säkerhet

- Kör bakom en reverse proxy (t.ex. nginx) om du exponerar den mot internet
- Sätt upp lösenordsskydd om appen är publik
- `cookies.txt` committas aldrig till git

## 📄 Licens

MIT License – se [LICENSE](LICENSE)
