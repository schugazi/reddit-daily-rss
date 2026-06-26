# Reddit Daily RSS

A local generator that aggregates the top 5 daily posts from your chosen subreddits into per-subreddit RSS 2.0 files. Runs daily on this server via a systemd user timer.

> **This repo is now a local-only feed generator for [`personal-feed`](../personal-feed).** `personal-feed` reads `docs/*.xml` straight off disk as the **sole consumer**, so the old GitHub Pages publishing tail has been removed: **no `git pull`/`commit`/`push` in the daily loop, no OPML/landing page, and `docs/` is untracked** (generated feeds live untracked on disk; the repo versions only code). This eliminated the whole git-state footgun class. If you ever want a public/static feed reader again, re-add a publish step — but nothing consumes Pages today.

## How it works

1. A systemd user timer runs `run-daily.sh` once per day (02:15 AM ET).
2. `scripts/build_feed.py` fetches Reddit's Atom feeds for each subreddit listed in `subreddits.txt`.
3. Requests use authenticated RSS credentials (see [Rate limiting](#rate-limiting)) and are throttled; any subreddit that still fails is retried with backoff and requeued across additional rounds until it succeeds or a max-runtime budget is hit — so a normal run completes every subreddit.
4. Each subreddit gets its own RSS 2.0 feed at `docs/{subreddit}.xml`, written **atomically** (temp file + `os.replace`) so a concurrent reader (`personal-feed`'s poll) never sees a half-written, truncated feed.
5. Stale feed files are automatically removed when a subreddit is deleted from `subreddits.txt`.

Post links in each feed point at a local Redlib permalink (`http://127.0.0.1:8080/r/...`); `personal-feed` applies the public redlib (or `old.reddit.com`) base at render time, so the stored URLs never need to change.

## Coupling with `personal-feed`

- `personal-feed` reads `docs/{sub}.xml` directly (no network, no dependency on any push).
- `personal-feed` **edits `subreddits.txt`** when you add a subreddit from its UI — an atomic `os.replace` under a private `subreddits.txt.lock` (this build never takes that lock, so it's unaffected) — and then **triggers `reddit-daily-rss.service`** to rebuild. Because Reddit rebuilds the whole list, a freshly-added sub can take a few minutes to appear.
- `reddit-daily-rss.service` now has `TimeoutStartSec=40min` (the user-manager default of 90 s would kill a slow multi-round build).
- A subreddit that fails inside a build keeps its previous `docs/{sub}.xml` rather than going empty; `personal-feed` flags it `stale` by comparing the file's mtime against the newest rebuild.

## Setup

1. **Clone** this repo to the server.
2. **Edit `subreddits.txt`** — one subreddit name per line (without `r/`). Lines starting with `#` are ignored. (Or add subs from the `personal-feed` UI, which edits this file for you.)
3. **Provide credentials** (see [Rate limiting](#rate-limiting)).
4. **Enable the systemd timer**: `systemctl --user enable --now reddit-daily-rss.timer`
5. Run manually anytime with `./run-daily.sh`.

## Redlib proxy

Post links are rewritten to point to a local [Redlib](https://github.com/redlib-org/redlib) instance at `http://127.0.0.1:8080` (the `REDLIB` constant in `scripts/build_feed.py`). `personal-feed` rewrites that prefix to its configured public base at render time, so the on-disk URLs stay stable regardless of how redlib is exposed.

## Rate limiting

Reddit heavily rate-limits *unauthenticated* RSS, which makes fetching dozens of feeds per run fail with `HTTP 429`. To avoid this, the build appends your account's authenticated RSS parameters (`user` and `feed`) to each request — these come from your reddit.com RSS feed preferences and lift the limit substantially.

Because the feed token is an account secret and this repo may be public, credentials are **not** stored in the repo. The script reads them from the `REDDIT_USER` / `REDDIT_FEED` environment variables, falling back to a local config file outside the working tree at `~/.config/reddit-daily-rss/credentials` (`KEY=VALUE`, `chmod 600`). If no credentials are found, the build warns and falls back to unauthenticated requests.

As a safety net (the token can expire and the unofficial behavior may change), the build still paces requests and retries failures with exponential backoff — honoring any `Retry-After` header — and requeues still-failing subreddits across additional rounds under a bounded wall-clock budget, so the job always ends. The timing knobs live as constants at the top of `scripts/build_feed.py`.

## Project structure

```
subreddits.txt              # list of subreddits to follow
scripts/build_feed.py       # feed generator (Python 3, stdlib only; atomic writes)
run-daily.sh                # wrapper: just runs build_feed.py (no git)
docs/{subreddit}.xml        # per-subreddit RSS feeds (UNTRACKED — generated on disk)
```

## License

MIT
