"""Read-only visitor summary from the host's access logs. No script runs on the site, no cookies.

    .venv\\Scripts\\python scripts\\visitors.py [--days 14]

Downloads logs/access.log* over SFTP into memory (same credentials file as deploy.py), counts page views and
approximate unique visitors per day, and lists crawler visits separately. IP addresses are only used in memory to
tell visitors apart (hashed together with the browser string); they are never printed or saved.
"""

import argparse
import gzip
import hashlib
import io
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deploy  # noqa: E402

LINE = re.compile(r'^(\S+) \S+ \S+ \[([^\]]+)\] "(\S+) (\S+)[^"]*" (\d{3}) \S+ "([^"]*)" "([^"]*)"')
CRAWLERS = [
    ("Googlebot", "Googlebot"), ("Bing", "bingbot|BingPreview"), ("OpenAI", "GPTBot|OAI-SearchBot|ChatGPT-User"),
    ("Anthropic", "ClaudeBot|Claude-User|Claude-SearchBot"), ("Perplexity", "PerplexityBot"),
    ("Apple", "Applebot"), ("DuckDuckGo", "DuckDuckBot"),
]
NOT_HUMAN = re.compile(r"bot|crawl|spider|slurp|preview|monitor|curl|wget|python|go-http|scan|headless|uptime|facebookexternalhit|whatsapp|linkedin", re.I)
PAGE = re.compile(r"(/|\.html|\.pdf)$")


def read_logs(sftp):
    for entry in sftp.listdir_attr("logs"):
        name = entry.filename
        if not re.fullmatch(r"access\.log(\.\d+\.gz|\.\d+)?", name):
            continue
        raw = sftp.open(f"logs/{name}").read()
        if name.endswith(".gz"):
            raw = gzip.decompress(raw)
        yield from io.StringIO(raw.decode("utf-8", "replace"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--env", default=str(deploy.DEFAULT_ENV))
    parser.add_argument("--trust-new-host", action="store_true")
    args = parser.parse_args()
    sftp = deploy.connect(args)

    since = datetime.now().astimezone() - timedelta(days=args.days)
    views, visitors = Counter(), defaultdict(set)
    pages, referrers, downloads, bots = Counter(), Counter(), Counter(), Counter()
    seen = set()
    for line in read_logs(sftp):
        if line in seen:
            continue
        seen.add(line)
        m = LINE.match(line)
        if not m:
            continue
        ip, stamp, method, path, status, ref, agent = m.groups()
        when = datetime.strptime(stamp, "%d/%b/%Y:%H:%M:%S %z")
        if when < since or method != "GET" or status not in ("200", "304"):
            continue
        path = path.split("?")[0]
        crawler = next((label for label, pattern in CRAWLERS if re.search(pattern, agent)), None)
        if crawler:
            bots[crawler] += 1
            continue
        if NOT_HUMAN.search(agent) or not PAGE.search(path):
            continue
        day = when.date().isoformat()
        views[day] += 1
        visitors[day].add(hashlib.sha256((ip + agent).encode()).hexdigest()[:12])
        pages[path] += 1
        if path.endswith(".pdf"):
            downloads[path] += 1
        host = urlparse(ref).netloc.removeprefix("www.")
        if host and host != "msportfolio.be":
            referrers[host] += 1

    print(f"\nLast {args.days} days (human page views, approximate unique visitors per day)")
    for day in sorted(views):
        print(f"  {day}  views {views[day]:>4}  visitors {len(visitors[day]):>3}")
    if not views:
        print("  none yet")
    for title, counter in (("Top pages", pages), ("CV downloads", downloads), ("Referrers", referrers)):
        print(f"\n{title}")
        for key, n in counter.most_common(8):
            print(f"  {n:>4}  {key}")
        if not counter:
            print("  none")
    print("\nCrawler visits (successful page fetches)")
    for key, n in bots.most_common():
        print(f"  {n:>4}  {key}")
    if not bots:
        print("  none yet")
    print("\nNote: your own visits are included; shared networks and privacy tools make unique counts approximate.")


if __name__ == "__main__":
    main()
