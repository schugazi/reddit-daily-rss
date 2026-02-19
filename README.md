# Reddit Daily RSS

A self-updating RSS feed that aggregates the top 5 daily posts from your chosen subreddits. Powered by GitHub Actions — no server required.

## How it works

1. A scheduled GitHub Actions workflow runs once per day (06:15 UTC).
2. `scripts/build_feed.py` fetches Reddit's Atom feeds for each subreddit listed in `subreddits.txt`.
3. Posts are combined, sorted by time, and written to `docs/feed.xml` as an RSS 2.0 feed.
4. A simple `docs/index.html` landing page is generated alongside it.
5. Changes are committed and pushed automatically.

Serve the `docs/` directory with GitHub Pages (or any static host) and point your RSS reader at the `feed.xml` URL.

## Setup

1. **Fork or clone** this repo.
2. **Edit `subreddits.txt`** — one subreddit name per line (without `r/`). Lines starting with `#` are ignored.
3. **Enable GitHub Pages** on your repo, set to serve from the `docs/` folder on the `main` branch.
4. The workflow will run on the next schedule, or trigger it manually from the **Actions** tab.

## Redlib proxy

By default, post links are rewritten to point to a local [Redlib](https://github.com/redlib-org/redlib) instance at `http://127.0.0.1:8080`. Change the `REDLIB` variable in `scripts/build_feed.py` to use a public instance or the original Reddit URLs.

## Project structure

```
subreddits.txt              # list of subreddits to follow
scripts/build_feed.py       # feed generator (Python 3.11+, stdlib only)
docs/feed.xml               # generated RSS feed (auto-committed)
docs/index.html             # generated landing page (auto-committed)
.github/workflows/daily.yml # GitHub Actions schedule
```

## License

MIT
