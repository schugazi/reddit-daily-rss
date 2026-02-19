import datetime as dt
import glob
import os
import time
from xml.etree.ElementTree import Element, SubElement, tostring
import urllib.request
import xml.etree.ElementTree as ET

USER_AGENT = "Mozilla/5.0 (compatible; reddit-rss-daily-bot/1.0; +https://github.com/)"
BASE = "https://www.reddit.com/r/{sub}/top/.rss?sort=top&t=day&limit=5"
REDLIB = "http://127.0.0.1:8080"
PAGES_URL = "https://nmschuster.github.io/reddit-daily-rss"

def fetch_xml(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")

def parse_atom_entries(atom_xml: str):
    # Reddit .rss is Atom
    ns = {"a": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(atom_xml)
    entries = []
    for e in root.findall("a:entry", ns):
        title = (e.findtext("a:title", default="", namespaces=ns) or "").strip()
        link_el = e.find("a:link", ns)
        link = link_el.attrib.get("href", "") if link_el is not None else ""
        updated = (e.findtext("a:updated", default="", namespaces=ns) or "").strip()
        id_ = (e.findtext("a:id", default="", namespaces=ns) or "").strip()
        entries.append({"title": title, "link": link, "updated": updated, "id": id_})
    return entries

def atom_time_to_rfc822(s: str) -> str:
    # Example: 2026-02-16T01:23:45+00:00
    try:
        t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        t = dt.datetime.now(dt.timezone.utc)
    return t.strftime("%a, %d %b %Y %H:%M:%S %z")

def build_rss(sub: str, items):
    rss = Element("rss", version="2.0")
    channel = SubElement(rss, "channel")
    SubElement(channel, "title").text = f"Reddit: r/{sub} Daily Top 5"
    SubElement(channel, "link").text = f"{REDLIB}/r/{sub}"
    SubElement(channel, "description").text = f"Daily top 5 posts from r/{sub}."
    SubElement(channel, "lastBuildDate").text = dt.datetime.now(dt.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")

    for it in items:
        item = SubElement(channel, "item")
        SubElement(item, "title").text = it["title"]
        SubElement(item, "link").text = it["link"]
        SubElement(item, "guid", isPermaLink="false").text = it["guid"]
        SubElement(item, "pubDate").text = it["pubDate"]
    return rss

def build_opml(subs):
    opml = Element("opml", version="2.0")
    head = SubElement(opml, "head")
    SubElement(head, "title").text = "Reddit Daily Top 5 Feeds"
    SubElement(head, "dateCreated").text = dt.datetime.now(dt.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
    body = SubElement(opml, "body")
    for sub in subs:
        SubElement(body, "outline",
                   type="rss",
                   text=f"r/{sub}",
                   title=f"Reddit: r/{sub} Daily Top 5",
                   xmlUrl=f"{PAGES_URL}/{sub}.xml",
                   htmlUrl=f"https://www.reddit.com/r/{sub}")
    return opml

def cleanup_stale_feeds(out_dir: str, current_subs: list[str]):
    valid_files = {f"{sub}.xml" for sub in current_subs}
    for path in glob.glob(os.path.join(out_dir, "*.xml")):
        fname = os.path.basename(path)
        if fname not in valid_files:
            os.remove(path)

def main():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    subs_path = os.path.join(root_dir, "subreddits.txt")
    out_dir = os.path.join(root_dir, "docs")
    os.makedirs(out_dir, exist_ok=True)

    with open(subs_path, "r", encoding="utf-8") as f:
        subs = [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]

    for sub in subs:
        url = BASE.format(sub=sub)
        xml = fetch_xml(url)
        entries = parse_atom_entries(xml)

        items = []
        for e in entries:
            link = e["link"].replace("https://www.reddit.com", REDLIB)
            items.append({
                "title": f"[r/{sub}] {e['title']}",
                "link": link,
                "guid": e["id"] or f"{sub}:{e['link']}",
                "pubDate": atom_time_to_rfc822(e["updated"]),
                "updated_raw": e["updated"],
            })

        items.sort(key=lambda x: x["updated_raw"], reverse=True)

        rss = build_rss(sub, items)
        rss_bytes = tostring(rss, encoding="utf-8", xml_declaration=True)

        feed_path = os.path.join(out_dir, f"{sub}.xml")
        with open(feed_path, "wb") as f:
            f.write(rss_bytes)

        time.sleep(1)  # be polite

    # Generate OPML
    opml = build_opml(subs)
    opml_bytes = tostring(opml, encoding="utf-8", xml_declaration=True)
    with open(os.path.join(out_dir, "feeds.opml"), "wb") as f:
        f.write(opml_bytes)

    # Remove stale feed files
    cleanup_stale_feeds(out_dir, subs)

    # Index page
    feed_links = "\n    ".join(
        f'<li><a href="{s}.xml">r/{s}</a></li>' for s in subs
    )
    idx = f"""<!doctype html>
<html>
<head><meta charset="utf-8"><title>Reddit Daily Top 5 Feeds</title></head>
<body>
  <h1>Reddit Daily Top 5 Feeds</h1>
  <p><a href="feeds.opml">Import all feeds (OPML)</a></p>
  <h2>Individual Feeds</h2>
  <ul>
    {feed_links}
  </ul>
  <p>Last built: {dt.datetime.now(dt.timezone.utc).isoformat()}</p>
</body>
</html>
"""
    with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(idx)

if __name__ == "__main__":
    main()
