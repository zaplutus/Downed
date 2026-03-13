FROM python:3.12-slim

# Installera ffmpeg och Tor
RUN apt-get update && apt-get install -y \
    ffmpeg \
    tor \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Kopiera och installera Python-beroenden
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kopiera appkoden
COPY app.py .

# Skapa mappar
RUN mkdir -p /app/static /app/data

# Tor-konfiguration
RUN echo "SocksPort 9050" >> /etc/tor/torrc

# Startskript som startar Tor + gunicorn
COPY docker-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 5000

ENTRYPOINT ["/entrypoint.sh"]
