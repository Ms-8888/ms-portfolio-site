"""Add canonical, hreflang and Open Graph tags to every page and write sitemap.xml.

Run after changing any page title, description or URL:
    python scripts/add_meta.py

Idempotent: the generated block sits between <!-- seo --> markers.
"""

import html
import re
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "site"
BASE = "https://msportfolio.be"

# Dutch path -> English path
PAIRS = {
    "/": "/en/",
    "/projecten/": "/en/projects/",
    "/projecten/webhook-platform/": "/en/projects/webhook-platform/",
    "/projecten/kennisassistent/": "/en/projects/knowledge-assistant/",
    "/projecten/datakwaliteit/": "/en/projects/data-quality/",
    "/hoe-ik-werk/": "/en/how-i-work/",
    "/cv/": "/en/cv/",
    "/contact/": "/en/contact/",
}
EN_TO_NL = {en: nl for nl, en in PAIRS.items()}


def file_for(path: str) -> Path:
    return SITE / path.strip("/") / "index.html" if path != "/" else SITE / "index.html"


def build_block(path: str) -> str:
    is_en = path in EN_TO_NL
    nl, en = (EN_TO_NL[path], path) if is_en else (path, PAIRS[path])
    page = file_for(path).read_text(encoding="utf-8")
    title = html.unescape(re.search(r"<title>(.*?)</title>", page, re.S).group(1)).strip()
    desc = html.unescape(re.search(r'<meta name="description" content="(.*?)">', page, re.S).group(1))
    esc = lambda text: html.escape(text, quote=True)
    own = BASE + path
    return f"""  <!-- seo -->
  <link rel="canonical" href="{own}">
  <link rel="alternate" hreflang="nl" href="{BASE + nl}">
  <link rel="alternate" hreflang="en" href="{BASE + en}">
  <link rel="alternate" hreflang="x-default" href="{BASE + nl}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="Mohannad Shafik">
  <meta property="og:title" content="{esc(title)}">
  <meta property="og:description" content="{esc(desc)}">
  <meta property="og:url" content="{own}">
  <meta property="og:locale" content="{'en_GB' if is_en else 'nl_BE'}">
  <meta property="og:locale:alternate" content="{'nl_BE' if is_en else 'en_GB'}">
  <meta property="og:image" content="{BASE}/img/og-image.jpg">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta property="og:image:type" content="image/jpeg">
  <meta property="og:image:alt" content="Mohannad Shafik, Full-Stack Developer — AI &amp; Automation (portrait and name on a teal background)">
  <meta name="twitter:card" content="summary_large_image">
  <!-- /seo -->
"""


def main() -> None:
    for path in list(PAIRS) + list(PAIRS.values()):
        f = file_for(path)
        text = f.read_text(encoding="utf-8")
        text = re.sub(r"\s*<!-- seo -->.*?<!-- /seo -->\n?", "\n", text, flags=re.S)
        text = re.sub(r'\s*<link rel="alternate" hreflang="[^"]+" href="[^"]+">', "", text)
        text = text.replace("</head>", build_block(path) + "</head>", 1)
        f.write_text(text, encoding="utf-8")

    urls = []
    for nl, en in PAIRS.items():
        for own in (nl, en):
            urls.append(
                f"""  <url>
    <loc>{BASE + own}</loc>
    <xhtml:link rel="alternate" hreflang="nl" href="{BASE + nl}"/>
    <xhtml:link rel="alternate" hreflang="en" href="{BASE + en}"/>
    <xhtml:link rel="alternate" hreflang="x-default" href="{BASE + nl}"/>
  </url>"""
            )
    (SITE / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">\n'
        + "\n".join(urls)
        + "\n</urlset>\n",
        encoding="utf-8",
    )
    (SITE / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {BASE}/sitemap.xml\n", encoding="utf-8")
    print(f"updated {len(PAIRS) * 2} pages, sitemap.xml and robots.txt")


if __name__ == "__main__":
    main()
