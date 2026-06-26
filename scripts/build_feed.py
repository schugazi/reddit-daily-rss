import datetime as dt
import glob
import os
import random
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from xml.etree.ElementTree import Element, SubElement, tostring
import urllib.request
import xml.etree.ElementTree as ET

USER_AGENT = "Mozilla/5.0 (compatible; reddit-rss-daily-bot/1.0; +https://github.com/)"
BASE = "https://www.reddit.com/r/{sub}/top/.rss?sort=top&t=day&limit=5"
REDLIB = "http://127.0.0.1:8080"

# Authenticated RSS credentials (Reddit username + per-account feed token) let us
# bypass Reddit's aggressive unauthenticated rate limit. Loaded from the
# environment or a config file outside the repo — never hard-coded (the repo is
# public). See load_credentials().
CREDENTIALS_FILE = os.path.expanduser("~/.config/reddit-daily-rss/credentials")

RETRYABLE_HTTP_CODES = {429, 500, 502, 503}

# Pacing between every request. With authenticated feeds the limit is ~100/10min,
# so a light pace is plenty; without auth this alone can't beat the ~1/min ceiling.
THROTTLE_MIN, THROTTLE_MAX = 2.0, 3.0
# Per-request retry behaviour. Kept low so a throttled request fails fast and is
# requeued — when the whole IP is rate-limited, hammering one sub in place can't
# help (the limit won't reset in seconds); the between-round cooldown is what does.
MAX_RETRIES = 2
BACKOFF_BASE = 3
BACKOFF_CAP = 60
RETRY_AFTER_CAP = 120
# Bounded multi-round requeue of still-failing subreddits.
MAX_RUNTIME_SECONDS = 30 * 60
# Between-round cooldowns are the real recovery lever: a longer global pause lets
# Reddit's per-IP throttle reset before the next round retries the stragglers.
ROUND_COOLDOWN_BASE = 60
ROUND_COOLDOWN_CAP = 300
# If this many requests fail back-to-back within a round, the whole IP is
# throttled — abort the round early (don't pace through the rest only to fail
# them too) and go straight to the cooldown.
ROUND_ABORT_CONSECUTIVE_FAILS = 5

def load_credentials():
    """Return (user, feed) for authenticated RSS, or (None, None) if unset.

    Environment (REDDIT_USER / REDDIT_FEED) takes precedence over the config
    file, so manual runs can override. The config file lives outside the repo
    and is a simple KEY=VALUE format (blanks and #-comments ignored).
    """
    creds = {}
    try:
        with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key, value = key.strip(), value.strip()
                if key in ("REDDIT_USER", "REDDIT_FEED"):
                    creds[key] = value
    except FileNotFoundError:
        pass

    user = (os.environ.get("REDDIT_USER") or creds.get("REDDIT_USER") or "").strip()
    feed = (os.environ.get("REDDIT_FEED") or creds.get("REDDIT_FEED") or "").strip()
    if user and feed:
        return user, feed
    return None, None

def add_feed_auth(url: str, user: str, feed: str) -> str:
    """Add the authenticated feed/user query params to an .rss URL.

    user/feed must be raw (decoded) values — urlencode escapes them once, so a
    pre-encoded value would be double-escaped. Any existing feed/user params are
    replaced, keeping the helper idempotent.
    """
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if k not in ("feed", "user")]
    query += [("feed", feed), ("user", user)]
    return urlunsplit(parts._replace(query=urlencode(query)))

def redact_url(url: str) -> str:
    """Mask the feed/user secrets so URLs are safe to log or raise."""
    parts = urlsplit(url)
    if not parts.query:
        return url
    query = [(k, "REDACTED" if k in ("feed", "user") else v)
             for k, v in parse_qsl(parts.query, keep_blank_values=True)]
    return urlunsplit(parts._replace(query=urlencode(query)))

def fetch_xml(url: str) -> str:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except HTTPError as e:
            if e.code in RETRYABLE_HTTP_CODES and attempt < MAX_RETRIES:
                retry_after = e.headers.get("Retry-After") if e.headers else None
                if retry_after and retry_after.strip().isdigit():
                    delay = min(int(retry_after.strip()), RETRY_AFTER_CAP)
                else:
                    delay = min(BACKOFF_BASE * 2 ** (attempt - 1), BACKOFF_CAP) + random.uniform(0, 2)
                print(f"  [retry] HTTP {e.code} for {redact_url(url)}, retrying in {delay:.1f}s "
                      f"(attempt {attempt}/{MAX_RETRIES})", file=sys.stderr)
                time.sleep(delay)
            else:
                raise
        except URLError as e:
            if attempt < MAX_RETRIES:
                delay = min(BACKOFF_BASE * 2 ** (attempt - 1), BACKOFF_CAP) + random.uniform(0, 2)
                print(f"  [retry] Network error for {redact_url(url)}: {e.reason}, retrying in {delay:.1f}s "
                      f"(attempt {attempt}/{MAX_RETRIES})", file=sys.stderr)
                time.sleep(delay)
            else:
                raise
    raise RuntimeError(f"fetch_xml: unreachable (retries exhausted for {redact_url(url)})")

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

def cleanup_stale_feeds(out_dir: str, current_subs: list[str]):
    valid_files = {f"{sub}.xml" for sub in current_subs}
    for path in glob.glob(os.path.join(out_dir, "*.xml")):
        fname = os.path.basename(path)
        if fname not in valid_files:
            os.remove(path)

def build_one(sub: str, out_dir: str, user=None, feed=None) -> bool:
    """Fetch, parse, and write docs/{sub}.xml. Returns True on success."""
    url = BASE.format(sub=sub)
    if user and feed:
        url = add_feed_auth(url, user, feed)
    try:
        xml = fetch_xml(url)
        entries = parse_atom_entries(xml)
    except Exception as exc:
        print(f"WARN: skipping r/{sub} — {exc}", file=sys.stderr)
        return False

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
    _atomic_write_bytes(feed_path, rss_bytes)

    return True


def _atomic_write_bytes(path: str, data: bytes) -> None:
    """Write via a temp file + os.replace so a reader (e.g. personal-feed's poll)
    never sees a half-written, truncated feed mid-build."""
    out_dir = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=out_dir, prefix=os.path.basename(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

def main():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    subs_path = os.path.join(root_dir, "subreddits.txt")
    out_dir = os.path.join(root_dir, "docs")
    os.makedirs(out_dir, exist_ok=True)

    with open(subs_path, "r", encoding="utf-8") as f:
        subs = [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]

    user, feed = load_credentials()
    if user and feed:
        # Don't print user/feed — they're treated as secrets and this line lands
        # in the systemd journal on timer runs.
        print("Authenticated RSS: enabled")
    else:
        print("WARNING: no Reddit feed credentials found — using unauthenticated "
              "URLs, which will likely hit HTTP 429 rate limits. Set REDDIT_USER/"
              f"REDDIT_FEED or populate {CREDENTIALS_FILE}.", file=sys.stderr)

    start = time.monotonic()
    pending = list(subs)
    succeeded = set()
    round_num = 0

    while pending:
        round_num += 1
        still_failing = []
        consecutive_fails = 0
        for i, sub in enumerate(pending):
            # If the IP is globally throttled, stop pacing through the rest of the
            # list this round — requeue them untouched and let the cooldown reset.
            if consecutive_fails >= ROUND_ABORT_CONSECUTIVE_FAILS:
                still_failing.extend(pending[i:])
                print(f"Round {round_num}: {consecutive_fails} consecutive failures — "
                      f"IP appears throttled; aborting round early with "
                      f"{len(pending) - i} subreddit(s) unattempted.", file=sys.stderr)
                break
            time.sleep(random.uniform(THROTTLE_MIN, THROTTLE_MAX))
            if build_one(sub, out_dir, user, feed):
                succeeded.add(sub)
                consecutive_fails = 0
            else:
                still_failing.append(sub)
                consecutive_fails += 1

        pending = still_failing
        if not pending:
            break

        if time.monotonic() - start >= MAX_RUNTIME_SECONDS:
            print(f"Runtime budget reached after round {round_num}; "
                  f"{len(pending)} subreddit(s) still failing.", file=sys.stderr)
            break

        cooldown = min(ROUND_COOLDOWN_BASE * 2 ** (round_num - 1), ROUND_COOLDOWN_CAP)
        print(f"Round {round_num}: {len(pending)} subreddit(s) still failing "
              f"({', '.join(pending)}); cooling down {cooldown}s before retry.",
              file=sys.stderr)
        time.sleep(cooldown)
        if time.monotonic() - start >= MAX_RUNTIME_SECONDS:
            print(f"Runtime budget reached after round {round_num} cooldown; "
                  f"{len(pending)} subreddit(s) still failing.", file=sys.stderr)
            break

    # Summary
    print(f"\nFeed build complete: {len(succeeded)} succeeded, {len(pending)} failed")
    if pending:
        print(f"Stragglers (still failing after {round_num} round(s) / runtime budget): "
              f"{', '.join(pending)}", file=sys.stderr)
    if not succeeded:
        print("ERROR: all subreddits failed, exiting with error", file=sys.stderr)
        sys.exit(1)

    # Remove stale feed files (subs removed from subreddits.txt). The GitHub Pages
    # artifacts (feeds.opml / index.html) are no longer emitted — `personal-feed`,
    # reading docs/*.xml off disk, is the sole consumer now.
    cleanup_stale_feeds(out_dir, subs)

if __name__ == "__main__":
    main()
