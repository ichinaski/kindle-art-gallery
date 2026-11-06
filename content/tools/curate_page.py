"""Write content/review/curate.html: every approved work as the Kindle shows it, next to
the colour original, with a checkbox to drop it. Ticks are kept in the browser
(localStorage); "Exportar" downloads drops.json with the ids to remove.

    uv run --with pillow --with numpy --with requests --with fonttools python content/tools/curate_page.py
"""
import html, json, os, sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import build  # noqa: E402

ratings = {}
path = os.path.join(HERE, "blind-ratings.tsv")
if os.path.exists(path):
    for line in open(path):
        if not line.startswith("#"):
            f = line.rstrip("\n").split("\t")
            ratings[f[0]] = f[6]

sections, total = [], 0
for cid, name, _ in build.load_collections():
    works = [w for w in json.load(open(os.path.join(HERE, "works", f"{cid}.json"))) if w["status"] == "approved"]
    cards = []
    for w in works:
        i = html.escape(w["id"])
        cards.append(f"""<div class="card" id="c-{i}">
  <label class="drop"><input type="checkbox" data-id="{i}"> quitar</label>
  <div class="head"><b>{html.escape(w['title'])}</b> · {html.escape(w['artist'])}, {html.escape(w['date'])}
    <span class="id">{i} · panel ciego {ratings.get(w['id'], '?')}</span></div>
  <div class="imgs">
    <a href="../panels/{cid}/{i}.png" target="_blank"><img class="panel" loading="lazy" src="../panels/{cid}/{i}.png"></a>
    <img class="thumb" loading="lazy" src="thumbs/{i}.jpg">
  </div>
</div>""")
    total += len(works)
    sections.append(f'<h2 id="s-{cid}">{html.escape(name)} <small>({len(works)})</small></h2>' + "".join(cards))

nav = " · ".join(f'<a href="#s-{c}">{html.escape(n)}</a>' for c, n, _ in build.load_collections())
page = f"""<!doctype html><meta charset="utf-8"><title>Revisión final</title>
<style>
body{{font:14px -apple-system,sans-serif;margin:0;background:#e8e8e8}}
header{{position:sticky;top:0;background:#222;color:#eee;padding:10px 20px;z-index:2;display:flex;gap:18px;align-items:center;flex-wrap:wrap}}
header a{{color:#9cf}} header button{{font-size:14px;padding:4px 12px}}
main{{padding:16px 20px}} h2{{margin:28px 0 10px}}
.card{{background:#fff;margin:0 0 16px;padding:10px 12px;border-radius:6px;max-width:1240px;position:relative}}
.card.dropped{{background:#f6d6d6;opacity:.55}}
.drop{{position:absolute;right:12px;bottom:10px;font-size:16px;font-weight:bold;cursor:pointer}}
.drop input{{transform:scale(1.6);margin-right:8px}}
.head{{margin-bottom:8px}} .id{{color:#888;margin-left:8px;font-size:12px}}
.imgs{{display:flex;gap:12px;align-items:flex-start}}
.panel{{width:724px;height:536px;display:block}}
body.eink .panel{{filter:contrast(.647)}}
.thumb{{max-width:460px;max-height:536px}}
</style>
<header>
  <b>{total} obras</b> <span>a quitar: <b id="n">0</b></span>
  <label><input type="checkbox" id="eink" checked> simular pantalla</label>
  <button id="export">Exportar drops.json</button> <button id="clear">Desmarcar todo</button>
  <span>{nav}</span>
</header>
<main>
<p>Izquierda: el panel tal como se envía al Kindle (con «simular pantalla», el rango de grises
aproximado de la tinta electrónica). Derecha: el original en color. Marca «quitar» en las que
no quieras; las demás se quedan. Las marcas se guardan en este navegador. Al terminar, pulsa
«Exportar» y dime dónde quedó el archivo.</p>
{''.join(sections)}
</main>
<script>
const KEY = "kag-drops";
const drops = new Set(JSON.parse(localStorage.getItem(KEY) || "[]"));
const n = document.getElementById("n");
function sync() {{
  localStorage.setItem(KEY, JSON.stringify([...drops]));
  n.textContent = drops.size;
}}
document.querySelectorAll("input[data-id]").forEach(cb => {{
  const id = cb.dataset.id, card = document.getElementById("c-" + id);
  cb.checked = drops.has(id); card.classList.toggle("dropped", cb.checked);
  cb.addEventListener("change", () => {{
    cb.checked ? drops.add(id) : drops.delete(id);
    card.classList.toggle("dropped", cb.checked); sync();
  }});
}});
const eink = document.getElementById("eink");
const setEink = () => document.body.classList.toggle("eink", eink.checked);
eink.addEventListener("change", setEink); setEink();
document.getElementById("export").onclick = () => {{
  const blob = new Blob([JSON.stringify([...drops].sort(), null, 1)], {{type: "application/json"}});
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "drops.json"; a.click();
}};
document.getElementById("clear").onclick = () => {{
  if (!confirm("¿Desmarcar todas?")) return;
  drops.clear(); document.querySelectorAll("input[data-id]").forEach(cb => {{ cb.checked = false;
    document.getElementById("c-" + cb.dataset.id).classList.remove("dropped"); }}); sync();
}};
sync();
</script>"""
out = os.path.join(HERE, "review", "curate.html")
open(out, "w").write(page)
print(f"{out}: {total} works")
