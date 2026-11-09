"""Turn any scraper dataset JSON into a self-contained HTML report and open it.

Usage:
    python tools/export_html_report.py .tmp/<dataset>.json [--no-open]

One file, no internet needed (inline CSS/JS): summary cards at the top, run details,
blank-value counts, then a table with a search box, click-to-sort headers
(numbers sort as numbers, blanks last) and clickable links. Light/dark mode follows the OS.
"""

import html
import json
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import dataset  # noqa: E402

TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#f6f7fb;--card:#fff;--text:#1b2333;--muted:#5d6880;--line:#dfe4ee;--head:#1f3864;--headtext:#fff;--stripe:#f3f6fb;--link:#0b5cd6;--accent:#1f3864;--warn:#a15c00}
@media (prefers-color-scheme:dark){:root{--bg:#11151d;--card:#1a202b;--text:#e6e9f0;--muted:#9aa4b8;--line:#2c3443;--head:#25324a;--headtext:#e6e9f0;--stripe:#1e2531;--link:#79b0ff;--accent:#9cc0ff;--warn:#f0b35a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1400px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:22px;margin:0 0 4px}.sub{color:var(--muted);margin:0 0 20px;word-break:break-all}
.sub a{color:var(--link)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.card .n{font-size:24px;font-weight:700;color:var(--accent)}.card .l{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.04em}
details{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px;margin-bottom:16px}
summary{cursor:pointer;font-weight:600}
dl{display:grid;grid-template-columns:max-content 1fr;gap:4px 16px;margin:10px 0 0}dt{color:var(--muted)}dd{margin:0;word-break:break-word}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}.chip{border:1px solid var(--line);border-radius:999px;padding:2px 10px;font-size:12px}
.chip b{color:var(--warn)}
.bar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:8px 0 10px}
input[type=search]{flex:1;min-width:200px;max-width:460px;padding:9px 12px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--text);font-size:14px}
.count{color:var(--muted)}
.tbl{overflow:auto;border:1px solid var(--line);border-radius:10px;background:var(--card);max-height:75vh}
table{border-collapse:collapse;width:100%}
th{position:sticky;top:0;background:var(--head);color:var(--headtext);text-align:left;padding:9px 10px;cursor:pointer;white-space:nowrap;user-select:none;font-weight:600}
th .arr{opacity:.5;margin-left:4px}th.sorted .arr{opacity:1}
td{padding:7px 10px;border-top:1px solid var(--line);vertical-align:top}
tr:nth-child(even) td{background:var(--stripe)}
td.num{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
td.blank{color:var(--muted)}
td.text{min-width:220px;max-width:520px}
a{color:var(--link)}
</style></head><body><div class="wrap">
<h1>__TITLE__</h1>
<p class="sub" id="sub"></p>
<div class="cards" id="cards"></div>
<details><summary>Run details</summary><dl id="details"></dl></details>
<details open><summary>Blank values per column <span class="count">(missing on the site - left empty, never guessed)</span></summary><div class="chips" id="blanks"></div></details>
<div class="bar"><input type="search" id="q" placeholder="Search all columns…" autofocus><span class="count" id="shown"></span></div>
<div class="tbl"><table><thead><tr id="hdr"></tr></thead><tbody id="body"></tbody></table></div>
</div>
<script id="data" type="application/json">__DATA__</script>
<script>
const D=JSON.parse(document.getElementById('data').textContent);
const M=D.meta,C=D.columns,I=D.items;
const NUM=new Set(['number','money','rating','percent']);
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const blank=v=>v===null||v===undefined||v===''||(Array.isArray(v)&&!v.length);
const safeUrl=u=>/^https?:\/\//i.test(u||'')?u:null;
const fmtNum=(v,t)=>{if(typeof v!=='number')return esc(v);const s=v.toLocaleString(undefined,{maximumFractionDigits:2});return t==='percent'?s+'%':s};
const urlKey=(C.find(c=>c.type==='url')||{}).key, firstText=(C.find(c=>c.type==='text')||{}).key;
function show(v,c,row){
  if(blank(v))return '<td class="blank">—</td>';
  if(c.type==='url'){const u=safeUrl(v);if(!u)return '<td>'+esc(v)+'</td>';const s=u.replace(/^https?:\/\/(www\.)?/,'');return '<td><a href="'+esc(u)+'" target="_blank" rel="noopener">'+esc(s.length>48?s.slice(0,47)+'…':s)+'</a></td>'}
  if(NUM.has(c.type))return '<td class="num">'+fmtNum(v,c.type)+'</td>';
  if(c.type==='bool'||typeof v==='boolean')return '<td>'+(v?'Yes':'No')+'</td>';
  const t=Array.isArray(v)?v.join(', '):v;
  if(c.key===firstText&&urlKey&&safeUrl(row[urlKey]))return '<td class="text"><a href="'+esc(row[urlKey])+'" target="_blank" rel="noopener">'+esc(t)+'</a></td>';
  return '<td class="'+(c.type==='text'?'text':'')+'">'+esc(t)+'</td>';
}
// header text
document.getElementById('sub').innerHTML=(M.description?'<b>'+esc(M.description)+'</b> — ':'')+'<a href="'+esc(safeUrl(M.source_url)||'#')+'" target="_blank" rel="noopener">'+esc(M.source_url)+'</a> · scraped '+esc((M.scraped_at||'').replace('T',' '));
const filtered=Object.values(M.filtered_out||{}).reduce((a,b)=>a+b,0);
const blanksTotal=Object.values(M.missing_values||{}).reduce((a,b)=>a+b,0);
const cards=[[I.length,'Rows'],[M.items_seen,'Items seen'],[M.duplicates_removed,'Duplicates removed'],[filtered,'Removed by filters'],[blanksTotal,'Blank cells'],[M.pages_fetched,'Pages fetched']];
document.getElementById('cards').innerHTML=cards.map(([n,l])=>'<div class="card"><div class="n">'+(typeof n==='number'?n.toLocaleString():esc(n??'—'))+'</div><div class="l">'+l+'</div></div>').join('');
const det=[['Stopped because',M.stopped_because],['Fetch method',M.method],['Extractor',M.extractor],['Dedupe key',Array.isArray(M.dedupe_key)?M.dedupe_key.join(' + '):M.dedupe_key],['Max items',M.max_items],['Filters',M.filters&&Object.keys(M.filters).length?JSON.stringify(M.filters):'none'],['Removed by filter',Object.entries(M.filtered_out||{}).map(([k,v])=>k+': '+v).join(' · ')||'none'],['Requests / cache hits',(M.requests_made??'?')+' / '+(M.cache_hits??'?')],['Firecrawl credits used',M.firecrawl_credits_used||0],['Time',(M.seconds??'?')+' s'],['User-Agent',M.user_agent],['Notes',(M.notes||[]).join(' | ')||'—']];
document.getElementById('details').innerHTML=det.map(([k,v])=>'<dt>'+k+'</dt><dd>'+esc(v??'—')+'</dd>').join('');
document.getElementById('blanks').innerHTML=C.map(c=>{const n=(M.missing_values||{})[c.key]||0;return '<span class="chip">'+esc(c.label)+': '+(n?'<b>'+n+'</b>':'0')+'</span>'}).join('');
// table
let sortKey=null,sortDir=1;
const hdr=document.getElementById('hdr');
hdr.innerHTML='<th data-k="#">#</th>'+C.map(c=>'<th data-k="'+esc(c.key)+'">'+esc(c.label)+'<span class="arr">↕</span></th>').join('');
const rows=I.map((r,i)=>({i:i+1,r,txt:C.map(c=>blank(r[c.key])?'':Array.isArray(r[c.key])?r[c.key].join(' '):String(r[c.key])).join(' \u0001 ').toLowerCase()}));
function render(){
  const q=document.getElementById('q').value.trim().toLowerCase();
  let list=q?rows.filter(x=>q.split(/\s+/).every(w=>x.txt.includes(w))):rows.slice();
  if(sortKey){const c=C.find(c=>c.key===sortKey);list.sort((a,b)=>{const x=a.r[sortKey],y=b.r[sortKey];if(blank(x)&&blank(y))return 0;if(blank(x))return 1;if(blank(y))return -1;
    if(typeof x==='number'&&typeof y==='number')return (x-y)*sortDir;return String(Array.isArray(x)?x.join(','):x).localeCompare(String(Array.isArray(y)?y.join(','):y),undefined,{numeric:true,sensitivity:'base'})*sortDir})}
  else if(sortDir===-1)list.reverse();
  document.getElementById('body').innerHTML=list.map(x=>'<tr><td class="num">'+x.i+'</td>'+C.map(c=>show(x.r[c.key],c,x.r)).join('')+'</tr>').join('');
  document.getElementById('shown').textContent='Showing '+list.length.toLocaleString()+' of '+rows.length.toLocaleString();
  hdr.querySelectorAll('th').forEach(th=>{const on=th.dataset.k===(sortKey||'#');th.classList.toggle('sorted',on&&(sortKey||sortDir===-1));const a=th.querySelector('.arr');if(a)a.textContent=on&&sortKey?(sortDir>0?'▲':'▼'):'↕'});
}
hdr.addEventListener('click',e=>{const th=e.target.closest('th');if(!th)return;const k=th.dataset.k==='#'?null:th.dataset.k;if(k===sortKey)sortDir=-sortDir;else{sortKey=k;sortDir=1}render()});
document.getElementById('q').addEventListener('input',render);
render();
</script></body></html>
"""


def export(src, open_browser=True) -> Path:
    src = Path(src)
    data = dataset.read(src)
    meta = data["meta"]
    title = f"{meta.get('site', 'Scrape')} — {len(data['items']):,} rows"
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    out = src.with_suffix(".html")
    out.write_text(TEMPLATE.replace("__TITLE__", html.escape(title)).replace("__DATA__", payload), encoding="utf-8")
    if open_browser:
        webbrowser.open(out.resolve().as_uri())
    return out


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        sys.exit("Usage: python tools/export_html_report.py <dataset.json> [--no-open]")
    print(f"HTML: {export(args[0], open_browser='--no-open' not in sys.argv)}")


if __name__ == "__main__":
    main()
