#!/bin/bash
set -e

echo "Startar Tor..."
tor --RunAsDaemon 1 --SocksPort 9050

# Vänta tills Tor är redo
echo "Väntar på Tor..."
for i in $(seq 1 30); do
    if curl -s --socks5 127.0.0.1:9050 https://check.torproject.org/api/ip 2>/dev/null | grep -q '"IsTor":true'; then
        echo "Tor är redo!"
        break
    fi
    sleep 2
done

echo "Startar gunicorn..."
exec gunicorn \
    --workers 2 \
    --threads 4 \
    --timeout 300 \
    --bind 0.0.0.0:5000 \
    app:app
