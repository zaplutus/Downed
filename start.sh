#!/bin/bash
cd "$(dirname "$0")"
source venv/bin/activate
pip install -U yt-dlp -q

gunicorn --workers 2 --threads 4 --timeout 300 -b 0.0.0.0:5000 app:app
