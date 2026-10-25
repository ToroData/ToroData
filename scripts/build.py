#!/usr/bin/env python3
"""Build the generated parts of raigada-garcia.dev from the files in data/.

    python scripts/build.py                     rebuild from data/ only (no network)
    python scripts/build.py --fetch             query arXiv, update data/arxiv_cache.json, rebuild
    python scripts/build.py --fixture FILE.xml  same as --fetch, reading an Atom file instead of arXiv

Only the Python standard library is used, so it runs as-is in GitHub Actions.
The output depends only on data/, so running it twice produces no diff.
When new arXiv papers are found, a summary is written to .sync-report.md.
"""
import argparse
import html
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV = "{http://arxiv.org/schemas/atom}"
USER_AGENT = "raigada-garcia.dev publication sync (https://raigada-garcia.dev)"
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


# ---------------------------------------------------------------- helpers

def load(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def save_json(name, obj):
    text = json.dumps(obj, ensure_ascii=False, indent=2) + "\n"
    write_if_changed(DATA / name, text)


def write_if_changed(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.write_text(text, encoding="utf-8")
    print(f"  wrote {path.relative_to(ROOT)}")
    return True


def esc(s):
    return html.escape(str(s), quote=True)


def norm(s):
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def clean_text(s):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s.replace("---", "—").replace("--", "–")


def is_me(name, cfg):
    m = cfg["author_match"]
    n = norm(name)
    tokens = re.split(r"[\s\-.,]+", n)
    return m["surname_token"] in tokens and n.startswith(m["given_initial"])


def month_label(iso):
    d = date.fromisoformat(iso[:10])
    return f"{MONTHS[d.month - 1][:3]} {d.year}"


# ---------------------------------------------------------------- arXiv

def parse_atom(raw):
    root = ET.fromstring(raw)
    out = []
    for e in root.findall(f"{ATOM}entry"):
        id_url = (e.findtext(f"{ATOM}id") or "").strip()
        m = re.search(r"arxiv\.org/abs/([^v\s]+)(v\d+)?$", id_url)
        if not m:
            continue
        cat = e.find(f"{ARXIV}primary_category")
        out.append({
            "id": m.group(1),
            "version": m.group(2) or "v1",
            "title": clean_text(e.findtext(f"{ATOM}title")),
            "abstract": clean_text(e.findtext(f"{ATOM}summary")),
            "authors": [clean_text(a.findtext(f"{ATOM}name")) for a in e.findall(f"{ATOM}author")],
            "published": (e.findtext(f"{ATOM}published") or "")[:10],
            "updated": (e.findtext(f"{ATOM}updated") or "")[:10],
            "category": cat.get("term") if cat is not None else "",
            "journal_ref": clean_text(e.findtext(f"{ARXIV}journal_ref")),
            "doi": clean_text(e.findtext(f"{ARXIV}doi")),
        })
    return out


def http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read()
        except urllib.error.HTTPError as ex:
            if ex.code == 404:
                return None
            err = ex
        except urllib.error.URLError as ex:
            err = ex
        time.sleep(5 * (attempt + 1))
    print(f"  warning: could not fetch {url}: {err}", file=sys.stderr)
    return None


def fetch_arxiv(cfg):
    """ORCID-linked arXiv feed first (no homonyms), then a name query as a safety net."""
    records = []
    urls = [f"https://arxiv.org/a/{cfg['orcid']}.atom2"]
    if cfg.get("include_arxiv_ids"):
        # papers listed by id are always fetched, whatever the name search returns
        urls.append("https://export.arxiv.org/api/query?" + urllib.parse.urlencode(
            {"id_list": ",".join(cfg["include_arxiv_ids"]), "max_results": len(cfg["include_arxiv_ids"])}))
    for q in cfg["arxiv_name_queries"]:
        urls.append("https://export.arxiv.org/api/query?" + urllib.parse.urlencode(
            {"search_query": q, "start": 0, "max_results": 100,
             "sortBy": "submittedDate", "sortOrder": "descending"}))
    for i, url in enumerate(urls):
        if i:
            time.sleep(3)  # arXiv asks for one request every 3 seconds
        raw = http_get(url)
        if raw:
            got = parse_atom(raw)
            print(f"  {len(got)} entries from {url.split('?')[0]}")
            records += got
    return records


def update_cache(records, cfg, cache):
    known = {r["id"]: r for r in cache["papers"]}
    excluded = set(cfg["exclude_arxiv_ids"])
    forced = set(cfg["include_arxiv_ids"])
    new, changed = [], []
    for r in records:
        if r["id"] in excluded:
            continue
        if r["id"] not in forced and not any(is_me(a, cfg) for a in r["authors"]):
            continue
        old = known.get(r["id"])
        if old is None:
            new.append(r)
        elif any(old.get(k) != r[k] for k in ("version", "journal_ref", "doi", "title", "abstract", "authors")):
            changed.append(r)
        else:
            continue
        known[r["id"]] = r
    cache["papers"] = sorted(known.values(), key=lambda r: r["published"], reverse=True)
    return new, changed


# ---------------------------------------------------------------- model

def build_publications(cfg, cache, pubs):
    out = []
    excluded = set(cfg["exclude_arxiv_ids"])
    for r in cache["papers"]:
        if r["id"] in excluded:
            continue
        o = pubs["overrides"].get(r["id"], {})
        peer = bool(r["journal_ref"] or r["doi"])
        links = [{"label": "arXiv", "url": f"https://arxiv.org/abs/{r['id']}"},
                 {"label": "PDF", "url": f"https://arxiv.org/pdf/{r['id']}"}]
        if r["doi"]:
            links.append({"label": "DOI", "url": f"https://doi.org/{r['doi']}"})
        if o.get("explainer"):
            links.append({"label": "Interactive explainer", "url": o["explainer"]})
        links += o.get("links", [])
        out.append({
            "key": r["id"], "arxiv": r["id"], "group": o.get("group", "peer" if peer else "preprint"),
            "type": "article" if peer else "misc",
            "year": int(r["published"][:4]), "date": r["published"], "updated": r["updated"],
            "title": o.get("title", r["title"]), "authors": r["authors"],
            "venue": o.get("venue", r["journal_ref"] or f"arXiv:{r['id']} [{r['category']}]"),
            "summary": o.get("summary", ""), "abstract": r["abstract"],
            "category": r["category"], "doi": r["doi"], "links": links,
            "page": f"papers/{r['id']}.html",
        })
    for m in pubs["manual"]:
        links = []
        if m.get("doi"):
            links.append({"label": "DOI", "url": f"https://doi.org/{m['doi']}"})
        links += m.get("links", [])
        out.append({**m, "key": m["id"], "arxiv": None, "links": links, "page": None,
                    "summary": m.get("summary", ""), "abstract": m.get("abstract", "")})
    return out


CFG = {}


def bib_name(n):
    if CFG and is_me(n, CFG):
        return CFG["bib_name"]  # two Spanish surnames: never split them
    parts = n.split()
    return n if len(parts) < 2 else f"{parts[-1]}, {' '.join(parts[:-1])}"


def bib_key(p):
    first = bib_name(p["authors"][0]).split(",")[0] if p["authors"] else "anon"
    first = re.sub(r"[^a-z]", "", norm(first))
    words = [w for w in re.findall(r"[a-z]+", norm(p["title"])) if w not in {"a", "an", "the", "on", "of", "for"}]
    return f"{first}{p['year']}{words[0] if words else ''}"


def bibtex(p):
    f = [("title", "{" + p["title"] + "}"), ("author", " and ".join(bib_name(a) for a in p["authors"])),
         ("year", str(p["year"]))]
    if p["arxiv"]:
        kind = "article" if p["type"] == "article" else "misc"
        if p["type"] == "article" and p["venue"]:
            f.append(("journal", p["venue"]))
        f += [("eprint", p["arxiv"]), ("archivePrefix", "arXiv"), ("primaryClass", p["category"])]
        if p["doi"]:
            f.append(("doi", p["doi"]))
        f.append(("url", f"https://arxiv.org/abs/{p['arxiv']}"))
    else:
        kind = p["type"]
        for k in ("school", "institution", "publisher"):
            if p.get(k):
                f.append((k, p[k]))
        if p.get("doi"):
            f += [("doi", p["doi"]), ("url", f"https://doi.org/{p['doi']}")]
    body = ",\n".join(f"  {k} = {{{v.replace('–', '--').replace('—', '---')}}}" for k, v in f)
    return f"@{kind}{{{bib_key(p)},\n{body}\n}}"


# ---------------------------------------------------------------- HTML

def authors_html(authors, cfg):
    return ", ".join(f'<span class="me">{esc(a)}</span>' if is_me(a, cfg) else esc(a) for a in authors)


def pub_item(p, cfg, prefix=""):
    anchor = "pub-" + re.sub(r"[^a-z0-9]+", "-", p["key"].lower())
    title = esc(p["title"])
    if p["page"]:
        title = f'<a href="{prefix}{p["page"]}">{title}</a>'
    text = p["summary"] or ""
    links = "\n".join(
        f'              <a href="{esc(prefix + l["url"] if not re.match(r"^[a-z]+:", l["url"]) else l["url"])}">'
        f'{esc(l["label"])}<span class="sr-only">: {esc(p["title"])}</span></a>' for l in p["links"])
    bib = esc(bibtex(p))
    return f"""        <li class="pub" id="{anchor}">
          <span class="year">{p['year']}</span>
          <div>
            <p class="pub-title">{title}</p>
            <p class="pub-authors">{authors_html(p['authors'], cfg)}</p>
            <p class="pub-venue">{esc(p['venue'])}</p>
{f'            <p class="pub-abstract">{esc(text)}</p>' + chr(10) if text else ''}            <p class="pub-links">
{links}
            </p>
            <details class="cite">
              <summary>Cite</summary>
              <pre id="bib-{anchor}">{bib}</pre>
              <button type="button" class="copy" data-copy="bib-{anchor}">Copy BibTeX</button>
            </details>
          </div>
        </li>"""


GROUPS = [("peer", "Peer-reviewed"), ("preprint", "Preprints"), ("other", "Theses, reports &amp; other works")]


def publications_html(pubs, cfg):
    parts = ['      <p class="note">Updated automatically from arXiv. Full list on '
             '<a href="https://orcid.org/{0}">ORCID</a> · <a href="publications.bib">all as BibTeX</a>.</p>'.format(cfg["orcid"])]
    for g, label in GROUPS:
        items = [p for p in pubs if p["group"] == g]
        if not items:
            continue
        items.sort(key=lambda p: (p["year"], p.get("date") or ""), reverse=True)
        parts.append(f"\n      <h3>{label}</h3>\n      <ol class=\"pubs\">")
        parts += [pub_item(p, cfg) for p in items]
        parts.append("      </ol>")
    return "\n".join(parts)


def news_items(news, cache):
    by_id = {r["id"]: r for r in cache["papers"]}
    items = []
    for n in news["items"]:
        d = n.get("date") or (by_id.get(n.get("arxiv"), {}).get("published"))
        if d:
            items.append({**n, "date": d})
    return sorted(items, key=lambda n: n["date"], reverse=True)


def news_html(items, limit=6):
    li = "\n".join(
        f'        <li><time datetime="{n["date"]}">{month_label(n["date"])}</time>'
        f'<span>{esc(n["text"])}'
        + (f' <a href="{esc(n["url"])}">Read more<span class="sr-only">: {esc(n["text"])}</span></a>' if n.get("url") else "")
        + "</span></li>" for n in items[:limit])
    return f'      <ul class="news">\n{li}\n      </ul>\n      <p class="note"><a href="feed.xml">Follow updates by RSS/Atom</a></p>'


def ld_publications(pubs, cfg):
    graph = []
    for p in pubs:
        if not p["arxiv"]:
            continue
        graph.append({
            "@type": "ScholarlyArticle",
            "@id": f"{cfg['site_url']}/{p['page']}#article",
            "headline": p["title"], "datePublished": p["date"], "url": f"{cfg['site_url']}/{p['page']}",
            "sameAs": [f"https://arxiv.org/abs/{p['arxiv']}"] + ([f"https://doi.org/{p['doi']}"] if p["doi"] else []),
            "author": [{"@id": f"{cfg['site_url']}/#person"} if is_me(a, cfg) else {"@type": "Person", "name": a}
                       for a in p["authors"]],
        })
    body = json.dumps({"@context": "https://schema.org", "@graph": graph}, ensure_ascii=False, indent=2)
    return f'  <script type="application/ld+json">\n{body}\n  </script>'


def paper_page(p, cfg):
    url = f"{cfg['site_url']}/{p['page']}"
    meta_authors = "\n".join(f'  <meta name="citation_author" content="{esc(a)}">' for a in p["authors"])
    d = p["date"].replace("-", "/")
    ld = json.dumps({
        "@context": "https://schema.org", "@type": "ScholarlyArticle", "headline": p["title"],
        "abstract": p["abstract"], "datePublished": p["date"], "url": url,
        "sameAs": [f"https://arxiv.org/abs/{p['arxiv']}"],
        "author": [{"@type": "Person", "name": a, **({"url": cfg["site_url"] + "/"} if is_me(a, cfg) else {})}
                   for a in p["authors"]],
    }, ensure_ascii=False, indent=2)
    links = " ".join(f'<a href="{esc(l["url"] if re.match(r"^[a-z]+:", l["url"]) else "../" + l["url"])}">{esc(l["label"])}</a>'
                     for l in p["links"])
    desc = p["summary"] or p["abstract"]
    desc = desc[:157] + "…" if len(desc) > 160 else desc
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(p['title'])} · {esc(cfg['display_name'])}</title>
  <meta name="description" content="{esc(desc)}">
  <link rel="canonical" href="{url}">
  <!-- Highwire Press tags, read by Google Scholar and reference managers -->
  <meta name="citation_title" content="{esc(p['title'])}">
{meta_authors}
  <meta name="citation_publication_date" content="{d}">
  <meta name="citation_online_date" content="{d}">
  <meta name="citation_pdf_url" content="https://arxiv.org/pdf/{p['arxiv']}">
  <meta name="citation_abstract_html_url" content="{url}">
  <meta property="og:type" content="article">
  <meta property="og:url" content="{url}">
  <meta property="og:title" content="{esc(p['title'])}">
  <meta property="og:description" content="{esc(desc)}">
  <meta property="og:image" content="{cfg['site_url']}/assets/img/og-card.jpg">
  <meta name="twitter:card" content="summary_large_image">
  <link rel="icon" type="image/png" sizes="48x48" href="../assets/img/favicon-48.png">
  <link rel="alternate" type="application/atom+xml" title="Updates" href="../feed.xml">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Source+Serif+4:opsz,wght@8..60,500;8..60,600&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="../style.css?v=3">
  <script type="application/ld+json">
{ld}
  </script>
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>
<header class="topbar">
  <a class="brand" href="../index.html">R. S. Raigada-García</a>
  <nav class="nav" aria-label="Site">
    <a href="../index.html#research">Research</a>
    <a href="../index.html#publications">Publications</a>
    <a href="../research-map.html">Research map</a>
    <a href="../index.html#contact">Contact</a>
  </nav>
</header>
<main class="paper" id="main">
  <p class="paper-kind">{'Article' if p['group'] == 'peer' else 'Preprint'} · {esc(p['venue'])} · {month_label(p['date'])}</p>
  <h1>{esc(p['title'])}</h1>
  <p class="pub-authors">{authors_html(p['authors'], cfg)}</p>
  <p class="pub-links">{links}</p>
  <h2>Abstract</h2>
  <p class="paper-abstract">{esc(p['abstract'])}</p>
  <h2>Cite</h2>
  <pre id="bib">{esc(bibtex(p))}</pre>
  <button type="button" class="copy" data-copy="bib">Copy BibTeX</button>
  <p class="paper-back"><a href="../index.html#publications">All publications</a></p>
</main>
<script src="../site.js" defer></script>
</body>
</html>
"""


def readme_publications(pubs, cfg):
    out = []
    for g, label in GROUPS:
        items = sorted([p for p in pubs if p["group"] == g], key=lambda p: (p["year"], p.get("date") or ""), reverse=True)
        if not items:
            continue
        out.append(f"### {html.unescape(label)}\n")
        for p in items:
            authors = ", ".join(f"***{a}***" if is_me(a, cfg) else a for a in p["authors"])
            links = " · ".join(f"[{l['label']}]({l['url'] if re.match(r'^[a-z]+:', l['url']) else cfg['site_url'] + '/' + l['url']})"
                               for l in p["links"])
            out.append(f"- **{p['year']}** — **{p['title']}**  \n  {authors}  \n  *{p['venue']}*  \n  {links}\n")
    return "\n".join(out)


def feed_xml(items, cfg, updated):
    def entry(n):
        link = n.get("url") or ""
        link = link if re.match(r"^[a-z]+:", link) else f"{cfg['site_url']}/{link}" if link else cfg["site_url"] + "/"
        slug = re.sub(r"[^a-z0-9]+", "-", norm(n["text"]))[:60].strip("-")
        return f"""  <entry>
    <title>{esc(n['text'])}</title>
    <id>tag:raigada-garcia.dev,{n['date']}:{slug}</id>
    <link href="{esc(link)}"/>
    <updated>{n['date']}T00:00:00Z</updated>
  </entry>"""
    entries = "\n".join(entry(n) for n in items[:30])
    return f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>{esc(cfg['display_name'])} · updates</title>
  <link href="{cfg['site_url']}/feed.xml" rel="self"/>
  <link href="{cfg['site_url']}/"/>
  <id>{cfg['site_url']}/</id>
  <updated>{updated}T00:00:00Z</updated>
  <author><name>{esc(cfg['display_name'])}</name></author>
{entries}
</feed>
"""


def sitemap(cfg, pubs, updated):
    urls = [("", updated)] + [(s["path"], s["lastmod"]) for s in cfg.get("static_pages", [])]
    urls += [(p["page"], p["updated"] or p["date"]) for p in pubs if p["page"]]
    body = "\n".join(f"  <url>\n    <loc>{cfg['site_url']}/{u}</loc>\n    <lastmod>{d}</lastmod>\n  </url>" for u, d in urls)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{body}\n</urlset>\n'


def replace_block(text, name, content):
    pat = re.compile(rf"(<!-- BUILD:{name} -->)(.*?)(<!-- /BUILD:{name} -->)", re.S)
    if not pat.search(text):
        raise SystemExit(f"marker BUILD:{name} not found")
    return pat.sub(lambda m: f"{m.group(1)}\n{content}\n{m.group(3)}", text)


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--fixture")
    args = ap.parse_args()

    cfg, pubs_data, news = load("config.json"), load("publications.json"), load("news.json")
    CFG.update(cfg)
    cache_path = DATA / "arxiv_cache.json"
    cache = load("arxiv_cache.json") if cache_path.exists() else {"papers": []}

    new, changed = [], []
    if args.fetch or args.fixture:
        records = parse_atom(Path(args.fixture).read_bytes()) if args.fixture else fetch_arxiv(cfg)
        new, changed = update_cache(records, cfg, cache)
        save_json("arxiv_cache.json", cache)
        listed = {n.get("arxiv") for n in news["items"]}
        for r in new:
            if r["id"] not in listed:
                news["items"].append({"text": f"{'New paper' if r['journal_ref'] or r['doi'] else 'New preprint'}: {r['title']}.", "url": f"papers/{r['id']}.html",
                                      "auto": True, "arxiv": r["id"]})
        save_json("news.json", news)

    pubs = build_publications(cfg, cache, pubs_data)
    items = news_items(news, cache)
    dates = [n["date"] for n in items] + [p["updated"] or p["date"] for p in pubs if p.get("date")]
    dates += [s["lastmod"] for s in cfg.get("static_pages", [])]
    updated = max(dates) if dates else date.today().isoformat()
    d = date.fromisoformat(updated)

    index_path = ROOT / "index.html"
    index = index_path.read_text(encoding="utf-8")
    index = replace_block(index, "NEWS", news_html(items))
    index = replace_block(index, "PUBLICATIONS", publications_html(pubs, cfg))
    index = replace_block(index, "LD-PUBLICATIONS", ld_publications(pubs, cfg))
    index = replace_block(index, "UPDATED", f"{MONTHS[d.month - 1]} {d.year}")
    write_if_changed(index_path, index)

    readme_path = ROOT / "README.md"
    readme = replace_block(readme_path.read_text(encoding="utf-8"), "README-PUBLICATIONS", readme_publications(pubs, cfg))
    write_if_changed(readme_path, readme)

    for p in pubs:
        if p["page"]:
            write_if_changed(ROOT / p["page"], paper_page(p, cfg))
    write_if_changed(ROOT / "publications.bib", "\n\n".join(bibtex(p) for p in pubs) + "\n")
    write_if_changed(ROOT / "feed.xml", feed_xml(items, cfg, updated))
    write_if_changed(ROOT / "sitemap.xml", sitemap(cfg, pubs, updated))

    if new or changed:
        lines = ["## arXiv sync", ""]
        if new:
            lines += ["New papers found. Check that each one is yours before merging; "
                      "add homonyms to `exclude_arxiv_ids` in `data/config.json`.", ""]
            lines += [f"- [{r['id']}](https://arxiv.org/abs/{r['id']}) {r['title']} — {', '.join(r['authors'])}" for r in new]
        if changed:
            lines += ["", "Updated records (new version, journal reference or DOI):", ""]
            lines += [f"- [{r['id']}](https://arxiv.org/abs/{r['id']}) {r['version']} {r['journal_ref']}" for r in changed]
        (ROOT / ".sync-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"done: {len(pubs)} publications, {len(new)} new, {len(changed)} updated")


if __name__ == "__main__":
    main()
