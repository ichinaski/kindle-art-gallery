"""Wikimedia Commons helpers: search files, fetch a resized copy (Commons requires a
descriptive User-Agent)."""
import subprocess
import time

import requests

API = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "kindle-art-gallery/0.1 (personal e-ink art frame)"}


def search(query, limit=12, width=3840):
    r = requests.get(API, params=dict(action="query", format="json", generator="search",
                                      gsrnamespace=6, gsrsearch=query, gsrlimit=limit,
                                      prop="imageinfo", iiprop="url|size|mime",
                                      iiurlwidth=width), headers=UA, timeout=60).json()
    pages = sorted(r.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 0))
    return [dict(title=p["title"], width=p["imageinfo"][0]["width"], height=p["imageinfo"][0]["height"],
                 mime=p["imageinfo"][0]["mime"], url=p["imageinfo"][0].get("thumburl") or p["imageinfo"][0]["url"])
            for p in pages if p.get("imageinfo")]


def info(title, width=3840):
    r = requests.get(API, params=dict(action="query", format="json", titles=title, prop="imageinfo",
                                      iiprop="url|size|mime", iiurlwidth=width), headers=UA, timeout=60).json()
    p = next(iter(r["query"]["pages"].values()))
    ii = p["imageinfo"][0]
    return dict(title=p["title"], width=ii["width"], height=ii["height"], mime=ii["mime"],
                url=ii.get("thumburl") or ii["url"])


def download(title, full=False):
    """Fetch a standard-size thumbnail (Commons only allows fixed widths for scripts,
    https://w.wiki/GHai): 3840 px when the original is larger, otherwise 1920 px,
    which is still more than the 1448 px screen. Originals narrower than 1920 px
    have no thumbnail, so Commons serves the full file; it answers 429 to Python
    requests for those (client fingerprinting) but serves curl, so curl fetches them.
    full=True also fetches originals up to 3840 px whole (prints with big trims)."""
    i = info(title, 3840)
    if i["width"] <= 3840:
        i = info(title, 1920)
    if i["width"] <= 1920 or (full and i["width"] <= 3840):
        i = info(title, 99999) if full else i
        url = i["url"].split("?")[0]
        for attempt in range(3):
            p = subprocess.run(["curl", "-sf", "-A", UA["User-Agent"], url], capture_output=True, timeout=300)
            if p.returncode == 0:
                return p.stdout
            time.sleep(30 * (attempt + 1))
        raise RuntimeError(f"curl failed for {url}")
    for attempt in range(3):
        r = requests.get(i["url"], headers=UA, timeout=180)
        if r.status_code == 429:
            time.sleep(min(int(r.headers.get("Retry-After", 0) or 20), 60))
            continue
        r.raise_for_status()
        return r.content
    r.raise_for_status()
