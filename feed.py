#!/usr/bin/env python3
"""Publica en Discord (webhook) los vídeos y Shorts nuevos de un canal de YouTube, vía RSS. Solo stdlib.

Entorno: DISCORD_WEBHOOK, YOUTUBE_CHANNEL_ID, ROLE_ID (opcional), AVATAR_URL (opcional).
Estado: state.json {"seen": [ids]}. Si no existe, se marca todo como visto sin publicar.
Opciones: --dry-run (imprime el JSON, no envía ni guarda)
"""
import json, os, re, sys, time, urllib.error, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

STATE = Path(__file__).with_name("state.json")
UA = {"User-Agent": "Mozilla/5.0 (lownoise-feed)", "Accept-Language": "es", "Cookie": "SOCS=CAI; CONSENT=YES+1"}
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
      "m": "http://search.yahoo.com/mrss/"}
VERMILION, BONE = 0xE34234, 0xE8E2D4


def open_url(req, timeout=20, retries=3):
    for i in range(retries):
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and i < retries - 1:
                time.sleep(2 ** i * 2)
                continue
            raise


def fetch(url):
    with open_url(urllib.request.Request(url, headers=UA)) as r:
        return r.read()


def entries(cid):
    root = ET.fromstring(fetch(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}"))
    out = []
    for e in root.findall("a:entry", NS):
        out.append({"id": e.findtext("yt:videoId", namespaces=NS), "title": e.findtext("a:title", namespaces=NS),
                    "published": e.findtext("a:published", namespaces=NS),
                    "desc": e.findtext("m:group/m:description", default="", namespaces=NS),
                    "views": (e.find("m:group/m:community/m:statistics", NS) is not None
                              and e.find("m:group/m:community/m:statistics", NS).get("views"))})
    return sorted(out, key=lambda x: x["published"])


def is_short(vid):
    """/shorts/ID responde 200 solo si es un Short; si no, redirige. Ante cualquier duda: vídeo normal."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    try:
        urllib.request.build_opener(NoRedirect).open(
            urllib.request.Request(f"https://www.youtube.com/shorts/{vid}", headers=UA, method="HEAD"), timeout=15)
        return True
    except OSError:
        return False


def thumb(vid):
    for q in ("maxresdefault", "hqdefault"):
        url = f"https://i.ytimg.com/vi/{vid}/{q}.jpg"
        try:
            urllib.request.urlopen(urllib.request.Request(url, method="HEAD", headers=UA), timeout=10).close()
            return url
        except OSError:
            continue
    return f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"


def clean_desc(text, limit=220):
    lines = [l.strip() for l in text.splitlines() if l.strip() and not re.match(r"^(https?://|#|[-=_*]{3,})", l.strip())]
    out = " ".join(lines)
    out = re.sub(r"https?://\S+", "", out).strip()
    return (out[: limit - 1].rsplit(" ", 1)[0] + "…") if len(out) > limit else out


def payload(v, short, role, avatar):
    url = f"https://www.youtube.com/{'shorts/' if short else 'watch?v='}{v['id']}"
    desc = clean_desc(v["desc"])
    kind = "📱 NUEVO SHORT" if short else "🎬 NUEVO VÍDEO"
    body = (f"{desc}\n\n" if desc else "") + f"**[▶ Ver ahora en YouTube]({url})**"
    e = {"author": {"name": f"LOW NOISE  ·  {kind}"},
         "title": v["title"][:256], "url": url, "description": body,
         "color": BONE if short else VERMILION, "image": {"url": thumb(v["id"])},
         "footer": {"text": "RUST · HACK · BUILD  —  programar sin ruido"},
         "timestamp": datetime.fromisoformat(v["published"]).isoformat()}
    p = {"username": "Low Noise", "embeds": [e], "allowed_mentions": {"roles": [role] if role else []}}
    if role:
        p["content"] = f"<@&{role}> ¡Hay {'Short' if short else 'vídeo'} nuevo!"
    if avatar:
        p["avatar_url"] = avatar
    return p


def post(webhook, data):
    req = urllib.request.Request(webhook + "?wait=true", data=json.dumps(data).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "lownoise-feed"})
    for _ in range(4):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            if e.code == 429:
                time.sleep(float(json.loads(body).get("retry_after", 1)) + 0.5)
                continue
            sys.exit(f"Discord respondió {e.code}: {body[:300]}")
    sys.exit("Demasiados 429 de Discord")


def main():
    dry = "--dry-run" in sys.argv
    cid = os.environ["YOUTUBE_CHANNEL_ID"]
    items = entries(cid)
    if not STATE.exists():
        print(f"Primera ejecución: {len(items)} vídeos marcados como vistos.")
        if not dry:
            STATE.write_text(json.dumps({"seen": [i["id"] for i in items]}, indent=1) + "\n")
        return
    state = json.loads(STATE.read_text())
    new = [i for i in items if i["id"] not in state["seen"]]
    if not new:
        print("Sin novedades.")
        return
    for v in new:
        data = payload(v, is_short(v["id"]), os.environ.get("ROLE_ID"), os.environ.get("AVATAR_URL"))
        if dry:
            print(json.dumps(data, ensure_ascii=False, indent=1))
            continue
        post(os.environ["DISCORD_WEBHOOK"], data)
        print("Publicado:", v["title"])
        state["seen"].append(v["id"])
        STATE.write_text(json.dumps(state, indent=1) + "\n")


if __name__ == "__main__":
    main()
