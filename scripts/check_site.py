"""Crawl a site and report broken links, missing security policy and outside resources.

Usage:
    python scripts/check_site.py http://localhost:8765            # local test server
    python scripts/check_site.py https://msportfolio.be --external  # live site, also test outside links

Standard library only. Exit code 1 if anything is wrong.
"""

import sys
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

LIVE_HOST = "msportfolio.be"
LINKEDIN = "linkedin.com"  # answers 999 to scripts; treated as reachable


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.resources, self.metalinks = [], [], []
        self.csp = False
        self.h1 = 0
        self.title = ""
        self._in_title = False
        self.imgs_without_alt = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and a.get("href"):
            self.links.append(a["href"])
        if tag == "link" and a.get("href"):
            if a.get("rel") in ("alternate", "canonical"):
                self.metalinks.append(a["href"])
            else:
                self.resources.append(a["href"])
        if tag == "meta" and a.get("property") == "og:image":
            self.metalinks.append(a.get("content", ""))
        if tag in ("script", "img", "iframe", "object") and (a.get("src") or a.get("data")):
            self.resources.append(a.get("src") or a.get("data"))
        if tag == "img" and "alt" not in a:
            self.imgs_without_alt += 1
        if tag == "meta" and a.get("http-equiv", "").lower() == "content-security-policy":
            self.csp = True
        if tag == "h1":
            self.h1 += 1
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def fetch(url, method="GET"):
    request = urllib.request.Request(url, method=method, headers={"User-Agent": "site-check/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            return response.status, response.headers.get("Content-Type", ""), response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers.get("Content-Type", ""), b""
    except Exception as error:  # DNS, TLS, timeout
        return 0, type(error).__name__, b""


def main() -> int:
    base = sys.argv[1].rstrip("/")
    check_external = "--external" in sys.argv
    host = urllib.parse.urlparse(base).netloc
    problems, seen, queue, external = [], set(), ["/"], set()
    files = {}

    while queue:
        path = queue.pop(0)
        if path in seen:
            continue
        seen.add(path)
        status, ctype, body = fetch(base + path)
        files[path] = (status, ctype)
        if status != 200:
            problems.append(f"{path}: HTTP {status}")
            continue
        if "text/html" not in ctype:
            continue
        page = Page()
        page.feed(body.decode("utf-8", errors="replace"))
        if not page.csp:
            problems.append(f"{path}: no Content-Security-Policy meta tag")
        if page.h1 != 1:
            problems.append(f"{path}: {page.h1} h1 elements (expected 1)")
        if not page.title.strip():
            problems.append(f"{path}: empty title")
        if page.imgs_without_alt:
            problems.append(f"{path}: {page.imgs_without_alt} image(s) without alt")
        for resource in page.resources:
            absolute = urllib.parse.urljoin(base + path, resource)
            if urllib.parse.urlparse(absolute).netloc != host:
                problems.append(f"{path}: outside resource {resource}")
            else:
                queue.append(urllib.parse.urlparse(absolute).path)
        for link in page.metalinks:  # canonical, hreflang, og:image: must point at this site and exist
            parsed = urllib.parse.urlparse(urllib.parse.urljoin(base + path, link))
            if parsed.netloc not in (host, LIVE_HOST):
                problems.append(f"{path}: metadata link to another site {link}")
            else:
                queue.append(parsed.path or "/")
        for link in page.links:
            if link.startswith(("mailto:", "#")):
                continue
            absolute = urllib.parse.urljoin(base + path, link)
            parsed = urllib.parse.urlparse(absolute)
            if parsed.netloc == host:
                queue.append(parsed.path or "/")
            else:
                external.add(absolute)

    print(f"pages and files checked: {len(files)}")
    for path, (status, ctype) in sorted(files.items()):
        print(f"  {status} {path}  ({ctype.split(';')[0]})")

    if check_external:
        print(f"external links: {len(external)}")
        for url in sorted(external):
            if LINKEDIN in url:
                print(f"  skipped (blocks scripts) {url}")
                continue
            status, _, _ = fetch(url, "HEAD")
            if status in (405, 403, 0):
                status, _, _ = fetch(url, "GET")
            print(f"  {status} {url}")
            if status != 200:
                problems.append(f"external {url}: HTTP {status}")

    print()
    print("PROBLEMS:" if problems else "no problems found")
    for problem in problems:
        print("  -", problem)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
