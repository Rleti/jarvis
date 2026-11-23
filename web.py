"""Веб-интерфейс: чат с Джарвисом с телефона (или любого браузера) в домашней сети.

Адрес со своим ключом пишется в лог при запуске и открывается из меню в трее
(«Веб-интерфейс (для телефона)» — там же QR-код). Без ключа сервер ничего не отвечает:
через Джарвиса можно управлять компьютером, поэтому чужим в сети вход закрыт.
"""
import io
import json
import logging
import os
import queue
import secrets
import socket
import threading
import time
import uuid
import wave
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import config

log = logging.getLogger("jarvis.web")
HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(HERE, "web_token.txt")
LOCAL_CONNECT_URL = ""
PHONE_URL = ""

_assistant = None
_jobs = {}
_jobs_lock = threading.Lock()
_ask_lock = threading.Lock()


def _token():
    tok = getattr(config, "WEB_TOKEN", "") or ""
    if tok:
        return tok
    try:
        with open(TOKEN_FILE, encoding="utf-8") as f:
            tok = f.read().strip()
    except OSError:
        tok = ""
    if len(tok) < 8:
        tok = secrets.token_urlsafe(9)
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(tok)
    return tok


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))          # пакет не отправляется — так узнаём свой адрес в сети
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def _wav_bytes(audio, sr):
    import numpy as np
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


# ---------- задания: вопрос -> предложения ответа (+ звук для телефона) ----------
class Job:
    def __init__(self, text, voice):
        self.id = uuid.uuid4().hex[:12]
        self.text, self.voice = text, voice      # voice: pc / phone / none
        self.parts, self.audio = [], []          # готовые предложения и их звук (для телефона)
        self.done = False
        self.created = time.time()


def _run_job(job):
    a = _assistant
    synth_q = queue.Queue()

    def synth_worker():
        import tts as tts_mod
        while True:
            part = synth_q.get()
            if part is None:
                return
            try:
                audio = a.tts.synth(part)
                if audio is not None:
                    job.audio.append(_wav_bytes(audio, tts_mod.SR))
                else:
                    job.audio.append(b"")
            except Exception:
                log.exception("Синтез для телефона")
                job.audio.append(b"")

    worker = None
    if job.voice == "phone":
        worker = threading.Thread(target=synth_worker, daemon=True)
        worker.start()

    def on_part(part):
        job.parts.append(part)
        if worker:
            synth_q.put(part)

    with _ask_lock:
        try:
            log.info("Веб: %s", job.text)
            a.answer(job.text, mode="pc" if job.voice == "pc" else "quiet", on_part=on_part, src="web")
        except Exception:
            log.exception("Веб: ошибка ответа")
            on_part("Что-то пошло не так, подробности в логе.")
        finally:
            if worker:
                synth_q.put(None)
                worker.join(timeout=120)
            job.done = True
    with _jobs_lock:                             # старые задания чистим
        for k in [k for k, j in _jobs.items() if time.time() - j.created > 600]:
            _jobs.pop(k, None)


# ---------- HTTP ----------
class Handler(BaseHTTPRequestHandler):
    server_version = "Jarvis"

    def log_message(self, fmt, *args):            # не засорять лог каждым запросом
        pass

    # --- доступ ---
    def _authed(self):
        q = parse_qs(urlparse(self.path).query)
        if q.get("t", [""])[0] == TOKEN:
            return "url"
        c = SimpleCookie(self.headers.get("Cookie", ""))
        if "jt" in c and c["jt"].value == TOKEN:
            return "cookie"
        if self.headers.get("X-Token") == TOKEN:
            return "header"
        return None

    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _deny(self):
        self._send(403, "<h3>Нет доступа.</h3><p>Открой ссылку с ключом из меню Джарвиса в трее.</p>",
                   "text/html; charset=utf-8")

    def do_GET(self):
        url = urlparse(self.path)
        auth = self._authed()
        if url.path == "/connect" and self.client_address[0] in ("127.0.0.1", "::1"):
            return self._send(200, _connect_page(), "text/html; charset=utf-8")
        if not auth:
            return self._deny()
        if url.path == "/":
            extra = {}
            if auth == "url":                        # запомнить ключ в браузере и убрать его из адреса
                extra["Set-Cookie"] = f"jt={TOKEN}; Max-Age=31536000; Path=/; SameSite=Strict; HttpOnly"
            return self._send(200, PAGE.replace("{{NAME}}", getattr(config, "FACE_NAME", "Джарвис")),
                              "text/html; charset=utf-8", extra)
        if url.path == "/api/state":
            a = _assistant
            since = float(parse_qs(url.query).get("since", ["0"])[0] or 0)
            chat = [m for m in list(a.chat) if m["ts"] > since]
            return self._send(200, {"status": a.status, "paused": a.paused.is_set(), "chat": chat,
                                    "name": getattr(config, "FACE_NAME", "Джарвис")})
        if url.path.startswith("/api/job/"):
            job = _jobs.get(url.path.rsplit("/", 1)[-1])
            if not job:
                return self._send(404, {"error": "нет такого задания"})
            return self._send(200, {"parts": job.parts, "audio": len(job.audio), "done": job.done,
                                    "voice": job.voice})
        if url.path.startswith("/api/audio/"):
            parts = url.path.split("/")              # /api/audio/<задание>/<номер>
            job = _jobs.get(parts[3]) if len(parts) > 4 else None
            idx = parts[4] if len(parts) > 4 else ""
            try:
                data = job.audio[int(idx)]
            except Exception:
                return self._send(404, {"error": "нет звука"})
            return self._send(200, data, "audio/wav")
        return self._send(404, {"error": "не найдено"})

    def do_POST(self):
        if not self._authed():
            return self._deny()
        url = urlparse(self.path)
        try:
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(min(n, 20000)) or b"{}")
        except Exception:
            return self._send(400, {"error": "плохой запрос"})
        if url.path == "/api/ask":
            text = str(data.get("text", "")).strip()[:1000]
            voice = data.get("voice", "pc")
            if voice not in ("pc", "phone", "none"):
                voice = "pc"
            if not text:
                return self._send(400, {"error": "пусто"})
            if not _assistant.ready.is_set():
                return self._send(503, {"error": "Джарвис ещё загружается"})
            job = Job(text, voice)
            with _jobs_lock:
                _jobs[job.id] = job
            threading.Thread(target=_run_job, args=(job,), daemon=True).start()
            return self._send(200, {"job": job.id})
        if url.path == "/api/pause":
            a = _assistant
            if a.paused.is_set():
                a.paused.clear()
            else:
                a.paused.set()
            return self._send(200, {"paused": a.paused.is_set()})
        return self._send(404, {"error": "не найдено"})


def _qr_svg(text):
    try:
        import qrcode
        import qrcode.image.svg
        img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=12, border=2)
        buf = io.BytesIO()
        img.save(buf)
        return buf.getvalue().decode("utf-8")
    except Exception:
        return ""


def _connect_page():
    qr = _qr_svg(PHONE_URL)
    try:
        import telegram_bot
        tg = (f'<p>Код привязки Telegram-бота: <b style="font-size:24px;color:#46c8be">{telegram_bot.PAIR_CODE}</b></p>'
              if telegram_bot.PAIR_CODE else "")
    except Exception:
        tg = ""
    qr_html = (f'<div class="qr">{qr}</div><p>Наведи камеру телефона на код.</p>' if qr else
               '<p class="dim">QR-код появится после установки пакета: '
               '<code>.venv\\Scripts\\pip install qrcode</code></p>')
    return f"""<!doctype html><html lang="ru"><meta charset="utf-8"><title>Джарвис — подключить телефон</title>
<style>body{{background:#0b080d;color:#d8e4e2;font:16px system-ui,sans-serif;display:grid;place-items:center;
min-height:100vh;margin:0}}.card{{border:2px solid #96162a;border-radius:14px;padding:28px 32px;max-width:520px;
background:#140c12;text-align:center}}h2{{color:#46c8be;margin-top:0}}a{{color:#ff6f86;word-break:break-all;font-size:18px}}
.qr svg{{width:260px;height:260px;background:#fff;border-radius:8px;padding:6px}}.dim{{color:#8a8a90}}
code{{background:#000;padding:2px 6px;border-radius:4px}}</style>
<div class="card"><h2>Открой на телефоне</h2>{qr_html}{tg}
<p><a href="{PHONE_URL}">{PHONE_URL}</a></p>
<p class="dim">Телефон должен быть в той же Wi-Fi сети, что и компьютер.<br>
Ссылка содержит ключ доступа — не отправляй её посторонним.</p></div></html>"""


TOKEN = ""


def start(assistant):
    """Запускает сервер в фоне. -> адрес для телефона."""
    global _assistant, TOKEN, LOCAL_CONNECT_URL, PHONE_URL
    _assistant = assistant
    TOKEN = _token()
    port = int(getattr(config, "WEB_PORT", 8765))
    host = "0.0.0.0" if getattr(config, "WEB_LAN", True) else "127.0.0.1"
    srv = ThreadingHTTPServer((host, port), Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True, name="web").start()
    ip = lan_ip() if host == "0.0.0.0" else "127.0.0.1"
    PHONE_URL = f"http://{ip}:{port}/?t={TOKEN}"
    LOCAL_CONNECT_URL = f"http://127.0.0.1:{port}/connect"
    log.info("Веб-интерфейс: %s  (QR-код: меню в трее → «Веб-интерфейс»)", PHONE_URL)
    return PHONE_URL


PAGE = r"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0b080d">
<title>{{NAME}}</title>
<style>
:root{--bg:#0b080d;--panel:#140c12;--red:#96162a;--red2:#ff5a74;--teal:#46c8be;--teal2:#1a5254;--txt:#d8e4e2;--dim:#7d7680}
*{box-sizing:border-box}html,body{height:100%;margin:0}
body{background:radial-gradient(120% 80% at 0% 0%,#2a0a14 0%,var(--bg) 55%) fixed;color:var(--txt);
 font:16px/1.4 system-ui,-apple-system,"Segoe UI",sans-serif;display:flex;flex-direction:column}
header{display:flex;align-items:center;gap:10px;padding:12px 14px calc(10px);padding-top:max(12px,env(safe-area-inset-top));
 border-bottom:1px solid #2a1a22;background:rgba(11,8,13,.85);backdrop-filter:blur(6px);position:sticky;top:0;z-index:2}
.dot{width:10px;height:10px;border-radius:50%;background:var(--dim);box-shadow:0 0 8px currentColor;flex:none}
.dot.idle{background:var(--teal);color:var(--teal)}.dot.think{background:#e0a040;color:#e0a040;animation:pulse 1s infinite}
.dot.talk{background:var(--red2);color:var(--red2);animation:pulse .5s infinite}.dot.listen{background:#7fd0ff;color:#7fd0ff}
@keyframes pulse{50%{opacity:.35}}
h1{font-size:17px;margin:0;font-weight:600;letter-spacing:.3px}
#st{font-size:13px;color:var(--dim);margin-left:auto}
#pause{background:none;border:1px solid #3a2830;color:var(--dim);border-radius:8px;padding:5px 9px;font-size:13px}
main{flex:1;overflow-y:auto;padding:14px 12px 8px;display:flex;flex-direction:column;gap:10px}
.msg{max-width:86%;padding:9px 12px;border-radius:14px;white-space:pre-wrap;word-wrap:break-word;animation:in .18s ease-out}
@keyframes in{from{opacity:0;transform:translateY(4px)}}
.user{align-self:flex-end;background:#2a1018;border:1px solid #4a1a28;border-bottom-right-radius:4px}
.jarvis{align-self:flex-start;background:var(--panel);border:1px solid var(--red);border-bottom-left-radius:4px;
 box-shadow:0 0 0 1px rgba(150,22,42,.25),0 4px 18px rgba(0,0,0,.35)}
.jarvis .who{color:var(--red2);font-size:12px;font-weight:600;display:block;margin-bottom:2px}
.src{font-size:11px;color:var(--dim);margin-top:3px;display:block;text-align:right}
.typing:after{content:"▍";color:var(--teal);animation:pulse .8s infinite}
.chips{display:flex;gap:8px;overflow-x:auto;padding:6px 12px 2px;scrollbar-width:none}
.chips::-webkit-scrollbar{display:none}
.chip{flex:none;background:#170f15;border:1px solid var(--teal2);color:var(--teal);border-radius:16px;padding:6px 12px;font-size:14px}
footer{padding:8px 10px;padding-bottom:max(10px,env(safe-area-inset-bottom));background:rgba(11,8,13,.9);border-top:1px solid #2a1a22}
.seg{display:flex;gap:4px;margin-bottom:8px;background:#120b10;border-radius:10px;padding:3px}
.seg button{flex:1;border:0;background:none;color:var(--dim);padding:6px 4px;border-radius:8px;font-size:13px}
.seg button.on{background:var(--teal2);color:#dffaf6}
form{display:flex;gap:8px}
textarea{flex:1;resize:none;background:#120b10;color:var(--txt);border:1px solid #3a2830;border-radius:12px;
 padding:10px 12px;font:inherit;max-height:120px;outline:none}
textarea:focus{border-color:var(--teal2)}
#send{background:var(--red);border:0;color:#fff;border-radius:12px;width:52px;font-size:20px}
#send:disabled{opacity:.4}
.empty{color:var(--dim);text-align:center;margin:auto;font-size:15px}
</style></head><body>
<header><span class="dot" id="dot"></span><h1>{{NAME}}</h1><span id="st">…</span><button id="pause">пауза</button></header>
<main id="log"><div class="empty" id="empty">Напиши что-нибудь — можно надиктовать с клавиатуры телефона 🎤</div></main>
<div class="chips" id="chips"></div>
<footer>
 <div class="seg" id="seg"><button data-v="pc">🔊 На ПК</button><button data-v="phone">📱 На телефоне</button><button data-v="none">🔇 Без звука</button></div>
 <form id="f"><textarea id="t" rows="1" placeholder="Сообщение…" enterkeyhint="send"></textarea><button id="send">➤</button></form>
</footer>
<script>
const $=s=>document.querySelector(s), log=$('#log');
const ST={idle:'на связи',think:'думает…',talk:'говорит',listen:'слушает',loading:'загружается'};
const CHIPS=['Какая погода?','Который час?','Что у меня на экране?','Поставь таймер на 10 минут','Пауза музыки','Громкость на 30'];
let voice=(()=>{try{return localStorage.voice}catch(e){}})()||'pc', last=0, busy=false, seen=new Set(), first=true;
function setVoice(v){voice=v;try{localStorage.voice=v}catch(e){}document.querySelectorAll('#seg button').forEach(b=>b.classList.toggle('on',b.dataset.v==v))}
setVoice(voice);
document.querySelectorAll('#seg button').forEach(b=>b.onclick=()=>setVoice(b.dataset.v));
CHIPS.forEach(c=>{const b=document.createElement('button');b.className='chip';b.textContent=c;b.onclick=()=>send(c);$('#chips').append(b)});
function bubble(who,text,src){$('#empty')?.remove();const d=document.createElement('div');d.className='msg '+who;
 if(who=='jarvis'){const n=document.createElement('span');n.className='who';n.textContent='{{NAME}}';d.append(n)}
 const b=document.createElement('span');b.className='body';b.textContent=text;d.append(b);
 if(src=='voice'){const s=document.createElement('span');s.className='src';s.textContent='голосом';d.append(s)}
 log.append(d);log.scrollTop=log.scrollHeight;return d}
async function api(path,body){const r=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});
 if(!r.ok)throw new Error((await r.json().catch(()=>({}))).error||r.status);return r.json()}
async function poll(){try{const s=await api('/api/state?since='+last);
  $('#dot').className='dot '+s.status;$('#st').textContent=s.paused?'на паузе':(ST[s.status]||s.status);
  $('#pause').textContent=s.paused?'продолжить':'пауза';
  for(const m of s.chat){last=Math.max(last,m.ts);const key=m.ts+m.who;if(seen.has(key))continue;seen.add(key);
   if(m.src=='web'&&!first)continue; bubble(m.who,m.text,m.src)}
  first=false;
 }catch(e){$('#st').textContent='нет связи';$('#dot').className='dot'}}
setInterval(poll,1500);poll();
const audioQ=[];let playing=false;
function playNext(){if(playing||!audioQ.length)return;playing=true;const a=new Audio(audioQ.shift());a.onended=a.onerror=()=>{playing=false;playNext()};a.play().catch(()=>{playing=false})}
async function send(text){text=(text||'').trim();if(!text||busy)return;busy=true;$('#send').disabled=true;
 bubble('user',text);$('#t').value='';grow();
 const d=bubble('jarvis','');const body=d.querySelector('.body');body.classList.add('typing');
 try{const {job}=await api('/api/ask',{text,voice});let shown=0,played=0;
  if(voice=='phone'){new Audio().play().catch(()=>{})}
  while(true){await new Promise(r=>setTimeout(r,350));const j=await api('/api/job/'+job);
   if(j.parts.length>shown){body.textContent=j.parts.join(' ');shown=j.parts.length;log.scrollTop=log.scrollHeight}
   while(played<j.audio){audioQ.push('/api/audio/'+job+'/'+played);played++;playNext()}
   if(j.done&&(voice!='phone'||played>=j.parts.length))break}
  if(!body.textContent)body.textContent='…';
 }catch(e){body.textContent='Ошибка: '+e.message}
 body.classList.remove('typing');busy=false;$('#send').disabled=false}
$('#f').onsubmit=e=>{e.preventDefault();send($('#t').value)};
const t=$('#t');function grow(){t.style.height='auto';t.style.height=Math.min(t.scrollHeight,120)+'px'}
t.oninput=grow;t.onkeydown=e=>{if(e.key=='Enter'&&!e.shiftKey&&matchMedia('(pointer:fine)').matches){e.preventDefault();send(t.value)}};
$('#pause').onclick=()=>api('/api/pause',{}).then(poll);
</script></body></html>"""
