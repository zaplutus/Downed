from flask import Flask, render_template_string, request, jsonify, send_file
import os, threading, re, yt_dlp, time, requests, shutil, subprocess, logging, json

app = Flask(__name__)
logging.basicConfig(level=logging.DEBUG)

# --- KONFIGURATION ---
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
COOKIES     = os.environ.get('COOKIES_PATH', os.path.join(BASE_DIR, 'cookies.txt'))
PROXY       = os.environ.get('PROXY', 'socks5://127.0.0.1:9050')
STATE_FILE  = os.environ.get('STATE_FILE', os.path.join(BASE_DIR, 'state.json'))
STATIC_DIR  = os.environ.get('STATIC_DIR', os.path.join(BASE_DIR, 'static'))
_lock       = threading.Lock()

# ----------------------------------------------------------------- STATE (disk) ---

def set_state(**kwargs):
    with _lock:
        try:
            with open(STATE_FILE, 'r') as f:
                s = json.load(f)
        except Exception:
            s = {}
        s.update(kwargs)
        with open(STATE_FILE, 'w') as f:
            json.dump(s, f)

def get_state():
    try:
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return {'progress': 0, 'download_filename': None,
                'download_complete': False, 'download_error': None}

# ----------------------------------------------------------------- HELPERS ---

def get_cookies():
    if os.path.isfile(COOKIES) and os.path.getsize(COOKIES) > 0:
        logging.info("Använder cookies.txt")
        return COOKIES
    logging.warning("Ingen cookies.txt – kör utan.")
    return None

def build_ydl_opts(outtmpl, use_proxy=False, extra=None):
    ua = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
          'AppleWebKit/537.36 (KHTML, like Gecko) '
          'Chrome/124.0.0.0 Safari/537.36')
    opts = {
        'nocheckcertificate': True,
        'outtmpl': outtmpl,
        'user_agent': ua,
        'http_headers': {'User-Agent': ua},
        'retries': 3,
        'progress_hooks': [progress_hook],
        # Välj H.264+AAC i första hand – fungerar på iPhone/Safari
        # Faller tillbaka på bästa tillgängliga om H.264 saknas
        'format': 'bestvideo[vcodec^=avc]+bestaudio[acodec^=mp4a]/bestvideo[vcodec^=avc]+bestaudio/bestvideo+bestaudio/best',        # Konvertera till H.264+AAC om källan är VP9/AV1/opus/etc
        'postprocessors': [{
            'key': 'FFmpegVideoConvertor',
            'preferedformat': 'mp4',
        }],
        # faststart flyttar moov-atomen till början -> Safari kan spela direkt
        'postprocessor_args': {
            'ffmpeg': ['-c:v', 'libx264', '-preset', 'fast', '-crf', '22',
                       '-c:a', 'aac', '-b:a', '128k',
                       '-pix_fmt', 'yuv420p',
                       '-movflags', '+faststart']
        },
    }
    c = get_cookies()
    if c:
        opts['cookiefile'] = c
    if use_proxy:
        opts['proxy'] = PROXY
    if extra:
        if 'http_headers' in extra:
            opts['http_headers'].update(extra.pop('http_headers'))
        # Låt inte extra skriva över format/postprocessors om de inte är explicit satta
        for k, v in extra.items():
            if k not in ('format', 'merge_output_format', 'postprocessors', 'postprocessor_args'):
                opts[k] = v
            else:
                opts[k] = v  # tillåt override om man verkligen vill
    return opts

def progress_hook(d):
    if d['status'] == 'downloading':
        total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
        dl    = d.get('downloaded_bytes', 0)
        if total:
            set_state(progress=int(dl / total * 90))
    elif d['status'] == 'finished':
        set_state(progress=90)

def clean_old_files():
    static_dir = os.path.join(BASE_DIR, 'static')
    now = time.time()
    if not os.path.exists(static_dir):
        return
    for fn in os.listdir(static_dir):
        fp = os.path.join(static_dir, fn)
        if os.path.isfile(fp) and not fn.startswith('.') and os.stat(fp).st_mtime < now - 3600:
            try: os.remove(fp)
            except: pass

def get_audio_duration(path):
    try:
        cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
               '-of', 'default=noprint_wrappers=1:nokey=1', path]
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        return float(r.stdout.strip())
    except:
        return 10.0

# ----------------------------------------------------------------- ROUTES ---

@app.route('/')
def index():
    return render_template_string(TEMPLATE)

@app.route('/start_download', methods=['POST'])
def start_download():
    url = request.form.get('url', '').strip()
    if not url:
        return jsonify({'status': 'error'})
    clean_old_files()
    set_state(progress=0, download_complete=False, download_error=None, download_filename=None)
    threading.Thread(target=process_download, args=(url,), daemon=True).start()
    return jsonify({'status': 'started'})

@app.route('/progress')
def progress_route():
    return jsonify(get_state())

@app.route('/download/<path:filename>')
def download_file(filename):
    path = os.path.join(BASE_DIR, 'static', filename)
    if not os.path.exists(path):
        return jsonify({'error': 'Fil saknas'}), 404
    return send_file(path, as_attachment=True)

# ---------------------------------------------------------- DOWNLOAD LOGIC ---

def process_download(url):
    temp_dir = None
    try:
        static_dir = os.path.join(BASE_DIR, 'static')
        os.makedirs(static_dir, exist_ok=True)

        # ---- TIKTOK ----
        if 'tiktok.com' in url or 'vm.tiktok.com' in url:
            logging.info(f"TikTok: {url}")
            try:
                r = requests.get(url, allow_redirects=True, timeout=15,
                                 headers={'User-Agent': 'Mozilla/5.0'},
                                 proxies={'http': PROXY, 'https': PROXY})
                final_url = r.url
            except Exception as e:
                logging.warning(f"Redirect-fel ({e}), använder original")
                final_url = url

            m = re.search(r'/video/(\d+)', final_url) or re.search(r'/(\d{15,25})', final_url)
            if not m:
                raise ValueError(f"Hittade inget TikTok video-ID i: {final_url}")
            video_id   = m.group(1)
            target_url = f"https://www.tiktok.com/@x/video/{video_id}"

            temp_dir = os.path.join(static_dir, f"tmp_{video_id}")
            shutil.rmtree(temp_dir, ignore_errors=True)
            os.makedirs(temp_dir)

            opts = build_ydl_opts(
                outtmpl=os.path.join(temp_dir, 'media.%(ext)s'),
                use_proxy=True,
                extra={'writethumbnails': True, 'write_all_thumbnails': True,}
            )
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.extract_info(target_url, download=True)

            all_f = [os.path.join(temp_dir, f) for f in os.listdir(temp_dir)]
            v_f   = [f for f in all_f if f.endswith(('.mp4','.mkv','.webm')) and 'media' in os.path.basename(f)]
            i_f   = sorted([f for f in all_f if f.lower().endswith(('.jpg','.jpeg','.webp','.png'))])
            a_f   = [f for f in all_f if f.endswith(('.m4a','.mp3')) and f not in v_f]

            if v_f and len(i_f) <= 1:
                name = f"tiktok_{video_id}.mp4"
                shutil.move(v_f[0], os.path.join(static_dir, name))
                set_state(download_filename=name)
            elif i_f:
                audio   = a_f[0] if a_f else None
                dur     = get_audio_duration(audio) if audio else 10.0
                img_dur = max(3.0, dur / len(i_f))
                cpath   = os.path.join(temp_dir, 'input.txt')
                with open(cpath, 'w') as f:
                    curr = 0.0
                    while curr < dur:
                        for img in i_f:
                            f.write(f"file '{img}'\nduration {img_dur}\n")
                            curr += img_dur
                            if curr >= dur: break
                    f.write(f"file '{i_f[-1]}'\n")
                name = f"tiktok_slides_{video_id}.mp4"
                out  = os.path.join(static_dir, name)
                cmd  = ['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', cpath]
                if audio: cmd += ['-i', audio]
                cmd += ['-c:v','libx264','-pix_fmt','yuv420p',
                        '-vf','scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2',
                        '-r','25']
                if audio: cmd += ['-c:a','aac','-shortest']
                cmd.append(out)
                subprocess.run(cmd, check=True)
                set_state(download_filename=name)
            else:
                raise ValueError("TikTok: inga filer efter nedladdning")
            shutil.rmtree(temp_dir, ignore_errors=True)

        # ---- INSTAGRAM ----
        elif 'instagram.com' in url:
            logging.info(f"Instagram: {url}")
            fid  = f"ig_{int(time.time())}"
            opts = build_ydl_opts(
                outtmpl=os.path.join(static_dir, f'{fid}.%(ext)s'),
                extra={                       'http_headers': {'Referer': 'https://www.instagram.com/',
                                        'X-IG-App-ID': '936619743392459'}}
            )
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.extract_info(url, download=True)
                set_state(download_filename=f'{fid}.mp4')

        # ---- FACEBOOK ----
        elif 'facebook.com' in url or 'fb.watch' in url:
            logging.info(f"Facebook: {url}")
            try:
                r   = requests.head(url, allow_redirects=True, timeout=10,
                                    proxies={'http': PROXY, 'https': PROXY},
                                    headers={'User-Agent': 'Mozilla/5.0'})
                url = r.url.split('?')[0].replace('www.facebook.com', 'm.facebook.com')
            except Exception as e:
                logging.warning(f"FB redirect-fel: {e}")
            fid  = f"fb_{int(time.time())}"
            opts = build_ydl_opts(
                outtmpl=os.path.join(static_dir, f'{fid}.%(ext)s'),
                use_proxy=True,
                extra={}
            )
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.extract_info(url, download=True)
                set_state(download_filename=f'{fid}.mp4')

        elif 'x.com' in url or 'twitter.com' in url:
            logging.info(f"X/Twitter: {url}")
            fid  = f"x_{int(time.time())}"
            opts = build_ydl_opts(
                outtmpl=os.path.join(static_dir, f'{fid}.%(ext)s'),
                extra={                       'http_headers': {'Referer': 'https://x.com/'}}
            )
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.extract_info(url, download=True)
                set_state(download_filename=f'{fid}.mp4')

        # ---- YOUTUBE + ALLT ANNAT ----
        else:
            logging.info(f"Generisk: {url}")
            fid  = f"video_{int(time.time())}"
            opts = build_ydl_opts(
                outtmpl=os.path.join(static_dir, f'{fid}.%(ext)s'),
                extra={}
            )
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.extract_info(url, download=True)
                set_state(download_filename=f'{fid}.mp4')

        set_state(progress=100, download_complete=True)
        logging.info(f"Klar: {get_state()['download_filename']}")

    except Exception as e:
        logging.error(f"FEL: {e}", exc_info=True)
        shutil.rmtree(temp_dir, ignore_errors=True) if temp_dir else None
        set_state(download_error=str(e), download_complete=True)

# ---------------------------------------------------------------- TEMPLATE ---

TEMPLATE = '''<!DOCTYPE html>
<html lang="sv">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
    <title>Video Downloader</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }

        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background: #121212;
            color: #fff;
            min-height: 100vh;
            min-height: 100dvh;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            padding: 20px;
            padding-bottom: 60px;
        }

        .card {
            background: #1e1e1e;
            padding: 2rem;
            border-radius: 20px;
            width: 100%;
            max-width: 420px;
            text-align: center;
            border: 2px solid #fe2c55;
            box-shadow: 0 10px 30px rgba(254,44,85,.2);
        }

        h2 {
            color: #fe2c55;
            font-size: clamp(1.4rem, 5vw, 1.8rem);
            margin-bottom: 6px;
        }

        .sub {
            font-size: 12px;
            color: #888;
            margin-bottom: 24px;
            letter-spacing: 0.5px;
        }

        input {
            width: 100%;
            padding: 14px;
            margin-bottom: 14px;
            border-radius: 10px;
            border: 1px solid #444;
            background: #2a2a2a;
            color: #fff;
            font-size: 16px; /* 16px hindrar Safari från att zooma in */
            -webkit-appearance: none;
        }

        input::placeholder { color: #666; }
        input:focus { outline: none; border-color: #fe2c55; }

        button {
            width: 100%;
            padding: 15px;
            background: #fe2c55;
            border: none;
            color: #fff;
            border-radius: 10px;
            font-weight: bold;
            font-size: 16px;
            cursor: pointer;
            transition: background .2s;
            -webkit-tap-highlight-color: transparent;
            touch-action: manipulation;
        }

        button:active { background: #c4203f; }
        button:hover:not(:disabled) { background: #e0244a; }
        button:disabled { opacity: .5; cursor: not-allowed; }

        #prog-bg {
            margin-top: 20px;
            display: none;
            background: #333;
            height: 8px;
            border-radius: 4px;
            overflow: hidden;
        }

        #bar {
            height: 100%;
            width: 0%;
            background: linear-gradient(90deg, #25f4ee, #00c9c4);
            transition: width .4s ease;
            border-radius: 4px;
        }

        #status {
            margin-top: 14px;
            font-size: 13px;
            color: #aaa;
            min-height: 18px;
            line-height: 1.4;
        }

        #status.err { color: #fe2c55; }

        .copy {
            position: fixed;
            bottom: 0; left: 0; right: 0;
            text-align: center;
            padding: 10px 0;
            padding-bottom: max(10px, env(safe-area-inset-bottom));
            font-size: 11px;
            color: #555;
            background: #121212;
            border-top: 1px solid #2a2a2a;
        }
    </style>
</head>
<body>
<div class="card">
    <h2>Video Downloader</h2>
    <p class="sub">TT &nbsp;·&nbsp; FB &nbsp;·&nbsp; X &nbsp;·&nbsp; IG &nbsp;·&nbsp; YT + mer</p>
    <input type="url" id="url-input" placeholder="Klistra in länk..." autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false">
    <button id="btn" onclick="startDownload()">Ladda ner</button>
    <div id="prog-bg"><div id="bar"></div></div>
    <p id="status"></p>
</div>
<div class="copy">Copyright DR_Dredd.</div>

<script>
let timer = null;

function startDownload() {
    const urlVal = document.getElementById('url-input').value.trim();
    if (!urlVal) return;
    const btn    = document.getElementById('btn');
    const status = document.getElementById('status');
    const bar    = document.getElementById('bar');

    btn.disabled = true;
    status.className = '';
    status.textContent = 'Startar...';
    document.getElementById('prog-bg').style.display = 'block';
    bar.style.width = '0%';
    if (timer) clearInterval(timer);

    fetch('/start_download', {
        method: 'POST',
        headers: {'Content-Type': 'application/x-www-form-urlencoded'},
        body: 'url=' + encodeURIComponent(urlVal)
    })
    .then(r => r.json())
    .then(d => {
        if (d.status !== 'started') {
            status.className = 'err';
            status.textContent = 'Kunde inte starta.';
            btn.disabled = false;
            return;
        }
        status.textContent = 'Laddar ner...';
        timer = setInterval(poll, 1000);
    })
    .catch(err => { status.className='err'; status.textContent='Fel: '+err; btn.disabled=false; });
}

function poll() {
    fetch('/progress')
    .then(r => r.json())
    .then(p => {
        const bar    = document.getElementById('bar');
        const status = document.getElementById('status');
        const btn    = document.getElementById('btn');

        bar.style.width = (p.progress || 0) + '%';

        if (!p.download_complete) return;

        clearInterval(timer);
        btn.disabled = false;

        if (p.download_error) {
            status.className = 'err';
            let msg = p.download_error;
            if (/cookie|login|Sign in/i.test(msg))          msg = 'Inloggning krävs – uppdatera cookies.txt';
            else if (/not found|404/i.test(msg))             msg = 'Video ej hittad (privat/borttagen?)';
            else if (/proxy|Connection refused/i.test(msg))  msg = 'Proxy-fel – är Tor igång?';
            status.textContent = '❌ ' + msg;
        } else {
            bar.style.width = '100%';
            status.textContent = '✅ Klar!';
            // Visa klickbar länk – fungerar på Safari/iPhone
            const old = document.getElementById('dl-link');
            if (old) old.remove();
            const a = document.createElement('a');
            a.id = 'dl-link';
            a.href = '/download/' + p.download_filename;
            a.download = p.download_filename;
            a.textContent = '⬇️ Tryck här för att spara filen';
            a.style.cssText = 'display:block;margin-top:15px;padding:12px;background:#25f4ee;color:#000;border-radius:8px;font-weight:bold;text-decoration:none;font-size:14px;';
            document.querySelector('.card').appendChild(a);
        }
    })
    .catch(() => {});
}

document.getElementById('url-input').addEventListener('keydown', e => {
    if (e.key === 'Enter') startDownload();
});
</script>
</body>
</html>'''

if __name__ == '__main__':
    os.makedirs(os.path.join(BASE_DIR, 'static'), exist_ok=True)
    app.run(host='0.0.0.0', port=5000, debug=False)
