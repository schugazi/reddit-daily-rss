# Reddit Daily RSS

A self-updating RSS feed that aggregates the top 5 daily posts from your chosen subreddits. Runs daily on a local server via a systemd timer.

## How it works

1. A systemd user timer runs `run-daily.sh` once per day (02:15 AM ET).
2. `scripts/build_feed.py` fetches Reddit's Atom feeds for each subreddit listed in `subreddits.txt`.
3. Requests use authenticated RSS credentials (see [Rate limiting](#rate-limiting)) and are throttled; any subreddit that still fails is retried with backoff and requeued across additional rounds until it succeeds or a max-runtime budget is hit — so a normal run completes every subreddit.
4. Each subreddit gets its own RSS 2.0 feed at `docs/{subreddit}.xml`.
5. An OPML file (`docs/feeds.opml`) is generated for one-click import into feed readers.
6. A landing page (`docs/index.html`) links to each individual feed and the OPML file.
7. Stale feed files are automatically removed when a subreddit is deleted from the list.
8. Changes are committed and pushed automatically.

Serve the `docs/` directory with GitHub Pages (or any static host) and subscribe to individual subreddit feeds or import `feeds.opml` into your reader.

## Setup

1. **Clone** this repo to your server.
2. **Edit `subreddits.txt`** — one subreddit name per line (without `r/`). Lines starting with `#` are ignored.
3. **Enable GitHub Pages** on your repo, set to serve from the `docs/` folder on the `main` branch.
4. **Enable the systemd timer**: `systemctl --user enable --now reddit-daily-rss.timer`
5. Run manually anytime with `./run-daily.sh`.

## Redlib proxy

By default, post links are rewritten to point to a local [Redlib](https://github.com/redlib-org/redlib) instance at `http://127.0.0.1:8080`. Change the `REDLIB` variable in `scripts/build_feed.py` to use a public instance or the original Reddit URLs.

## Rate limiting

Reddit heavily rate-limits *unauthenticated* RSS, which makes fetching dozens of feeds per run fail with `HTTP 429`. To avoid this, the build appends your account's authenticated RSS parameters (`user` and `feed`) to each request — these come from your reddit.com RSS feed preferences and lift the limit substantially.

Because the feed token is an account secret and this repo may be public, credentials are **not** stored in the repo. The script reads them from the `REDDIT_USER` / `REDDIT_FEED` environment variables, falling back to a local config file outside the working tree at `~/.config/reddit-daily-rss/credentials` (`KEY=VALUE`, `chmod 600`). If no credentials are found, the build warns and falls back to unauthenticated requests.

As a safety net (the token can expire and the unofficial behavior may change), the build still paces requests and retries failures with exponential backoff — honoring any `Retry-After` header — and requeues still-failing subreddits across additional rounds under a bounded wall-clock budget, so the job always ends. A subreddit that fails every round keeps its previous `docs/{subreddit}.xml` rather than going empty, so readers retain last-known content. The timing knobs live as constants at the top of `scripts/build_feed.py`.

## Project structure

```
subreddits.txt              # list of subreddits to follow
scripts/build_feed.py       # feed generator (Python 3.11+, stdlib only)
run-daily.sh                # wrapper script: pull, build, commit, push
docs/{subreddit}.xml        # per-subreddit RSS feeds (auto-committed)
docs/feeds.opml             # OPML file for bulk feed import (auto-committed)
docs/index.html             # landing page with feed links (auto-committed)
```

## License

MIT
