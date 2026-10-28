# ms-portfolio-site

Source of my portfolio site, https://msportfolio.be. Plain HTML and CSS, no JavaScript, no framework, no build step, no third-party requests. Dutch pages at `/`, English pages at `/en/`.

- `site/` the site itself (fonts are self-hosted, licenses in `site/fonts/LICENSES.txt`)
- `scripts/check_site.py` crawls the site and reports broken links, missing security policy tags, outside resources and bad canonical/hreflang/Open Graph targets
- `scripts/add_meta.py` writes canonical, hreflang and Open Graph tags into every page, plus `sitemap.xml` and `robots.txt`
- `scripts/deploy.py` uploads `site/` over SFTP; it reads credentials from a file outside the repository, never prints them, and never deletes anything on the server except the retired `project2` folder after checking it against a local backup
- `extras/htaccess.txt` optional server settings, not part of the site until tested on the host
- `preview.bat` starts a local preview at http://localhost:8765 (opening the HTML files directly does not work, because links start with `/`)

## Check locally

```
preview.bat
python scripts/check_site.py http://localhost:8765
```

Measured with Lighthouse 12.6.1 against the live site (home pages and a case study, mobile and desktop): accessibility, best practices and SEO 100; performance 99 to 100.

## Content rule

Every text change is made in both languages (`site/...` and `site/en/...`). Each project says what was measured and what has not been done yet.
