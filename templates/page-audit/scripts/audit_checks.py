"""Run the mechanical SEO and technical checks on a page fetched by fetch_site.py.

Usage: python3 audit_checks.py <fetch_out_dir> [<out.json>]

Reads <fetch_out_dir>/site.json and the start page's facts (pages/<name>.json)
and prints, and writes to <out.json> (default <fetch_out_dir>/checks.json):
  {"url": ..., "checks": [{"id", "status": "fail" | "warn" | "pass",
   "priority": "high" | "medium" | "low", "element", "evidence", "fix"}],
   "counts": {...}, "page": {title, meta_description, h1, word_count, ...}}
Thresholds follow common practice (title 30 to 60 characters, description 70
to 160, one H1). The run decides what each failure means for this page.
"""
import json
import os
import sys
from urllib.parse import urlparse


def norm_url(u: str | None) -> str:
    if not u:
        return ""
    p = urlparse(u)
    return f"{(p.hostname or '').lower().removeprefix('www.')}{p.path.rstrip('/') or '/'}"


def main(d: str, out: str | None) -> None:
    with open(os.path.join(d, "site.json"), encoding="utf-8") as f:
        site = json.load(f)
    name = site["pages"][0]["name"]
    with open(os.path.join(d, "pages", f"{name}.json"), encoding="utf-8") as f:
        pg = json.load(f)
    checks = []

    def add(cid, ok, priority, element, evidence, fix, warn=False):
        checks.append({"id": cid, "status": "pass" if ok else ("warn" if warn else "fail"), "priority": priority, "element": element, "evidence": evidence, "fix": "" if ok else fix})

    # Crawlability and indexing
    robots = (pg.get("meta_robots") or "").lower() + " " + (pg.get("headers", {}).get("x-robots-tag") or "").lower()
    add("indexable", "noindex" not in robots, "high", "meta robots / X-Robots-Tag", f"robots: {robots.strip() or 'not set (indexable by default)'}", "Remove noindex if this page should appear in search.")
    sc = site.get("site_checks", {})
    if sc:
        rt = sc.get("robots_txt", {})
        add("robots_txt", rt.get("found") and not rt.get("disallow_all"), "high" if rt.get("disallow_all") else "low", "/robots.txt",
            "disallows the whole site" if rt.get("disallow_all") else (f"found (HTTP {rt.get('status')})" if rt.get("found") else f"not found (HTTP {rt.get('status')})"),
            "Serve a robots.txt that allows the pages you want indexed and names the sitemap.", warn=not rt.get("disallow_all"))
        sm = sc.get("sitemap", {})
        add("sitemap", bool(sm.get("looks_like_sitemap")), "medium", "XML sitemap", f"{sm.get('url')} answered HTTP {sm.get('status')}" + ("" if sm.get("looks_like_sitemap") else ", not a sitemap"),
            "Publish an XML sitemap and reference it in robots.txt.")
        if sc.get("http_redirects_to_https") is not None:
            add("https_redirect", sc["http_redirects_to_https"], "high", "http:// version", "redirects to https" if sc["http_redirects_to_https"] else "does not redirect to https",
                "Redirect every http:// URL to https:// with a 301.")
    canon = pg.get("canonical")
    if not canon:
        add("canonical", False, "medium", "<link rel=canonical>", "missing", "Add a self-referencing canonical URL.")
    else:
        same = norm_url(canon) == norm_url(pg["final_url"])
        add("canonical", same, "high" if not same else "medium", "<link rel=canonical>", f"points to {canon}", "Point the canonical at this page's own URL unless it is a deliberate duplicate.", warn=not same)
    red = pg.get("redirects") or []
    add("redirects", len(red) <= 1, "medium", "redirect chain", f"{len(red)} redirect(s) before the page", "Link straight to the final URL; avoid chains of redirects.")
    add("https", pg.get("https"), "high", "protocol", pg["final_url"], "Serve the page over HTTPS.")

    # On-page
    t = pg.get("title") or ""
    add("title", 30 <= len(t) <= 60, "high" if not t else "medium", "<title>", f'{len(t)} characters: "{t}"' if t else "missing",
        "Write a 30 to 60 character title with the main topic near the front and the brand at the end.", warn=bool(t))
    md = pg.get("meta_description") or ""
    add("meta_description", 70 <= len(md) <= 160, "medium" if not md else "low", "meta description", f'{len(md)} characters: "{md}"' if md else "missing",
        "Write a 70 to 160 character description that states the value and invites the click.", warn=bool(md))
    h1s = [h["text"] for h in pg.get("headings", []) if h["level"] == 1]
    add("h1", len(h1s) == 1, "high" if not h1s else "medium", "<h1>", f"{len(h1s)} H1: " + " | ".join(f'"{x}"' for x in h1s[:3]) if h1s else "no H1",
        "Use exactly one H1 that says what the page offers.")
    skips, prev = [], 0
    for h in pg.get("headings", []):
        if prev and h["level"] > prev + 1:
            skips.append(f"H{prev} to H{h['level']} at \"{h['text'][:50]}\"")
        prev = h["level"]
    add("heading_order", not skips, "low", "heading levels", "; ".join(skips[:3]) if skips else "no skipped levels", "Keep headings in order (H1, then H2, then H3) so the outline makes sense.", warn=True)
    wc = pg.get("word_count", 0)
    add("content_length", wc >= 300, "medium", "body text", f"{wc} words of readable text", "Add enough useful text to answer the visitor's question; under 300 words is thin for most pages.", warn=True)
    add("lang", bool(pg.get("lang")), "low", "<html lang>", pg.get("lang") or "missing", "Set the page language, e.g. <html lang=\"en\">.")
    add("viewport", bool(pg.get("viewport")), "high", "meta viewport", pg.get("viewport") or "missing", "Add <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"> for mobile.")
    img = pg.get("images", {})
    miss = img.get("missing_alt", 0)
    add("image_alt", miss == 0, "medium" if miss > 3 else "low", "<img alt>", f"{miss} of {img.get('count', 0)} images have no alt attribute" + (f" (e.g. {', '.join(x or '(no src)' for x in img.get('missing_alt_examples', [])[:3])})" if miss else ""),
        "Give every meaningful image a short descriptive alt text, and decorative ones alt=\"\".")
    ea = pg.get("links", {}).get("empty_anchor_text", 0)
    add("link_text", ea == 0, "low", "<a> link text", f"{ea} links with no text or label", "Give every link text or an aria-label that says where it goes.")
    og = pg.get("open_graph", {})
    missing_og = [k for k in ("title", "description", "image") if not og.get(k)]
    add("social_preview", not missing_og, "low", "Open Graph tags", "missing og:" + ", og:".join(missing_og) if missing_og else "og:title, og:description and og:image set", "Add og:title, og:description and og:image so shared links show a preview.")
    types = pg.get("jsonld_types", [])
    add("structured_data", bool(types), "low", "JSON-LD structured data", ", ".join(types) if types else "none in the HTML (some sites add it with JavaScript, which this check cannot see)",
        "Add JSON-LD for the page type (Organization, Product, Article, FAQPage) where it fits.", warn=True)

    # Performance signals (server side only)
    ms = pg.get("elapsed_ms", 0)
    add("response_time", ms <= 1500, "medium", "server response", f"HTML fetched in {ms} ms", "Investigate server response time and caching; aim for well under a second.", warn=True)
    kb = pg.get("bytes", 0) // 1024
    add("html_weight", kb <= 1024, "low", "HTML size", f"{kb} KB of HTML", "Trim inline scripts, styles and markup; very large HTML slows the first render.", warn=True)
    js = pg.get("scripts_external", 0)
    add("script_count", js <= 30, "low", "external scripts", f"{js} external scripts", "Remove unused third-party scripts and defer the rest.", warn=True)
    lc = site.get("link_check")
    if lc:
        broken = lc.get("broken", [])
        add("broken_links", not broken, "high" if broken else "medium", "internal links", f"{len(broken)} broken of {lc.get('checked')} checked" + (": " + ", ".join(f"{b['url']} ({b.get('status') or b.get('error')})" for b in broken[:5]) if broken else ""),
            "Fix or remove links that return errors.")
        if lc.get("restricted"):
            add("links_unverified", False, "low", "internal links", f"{len(lc['restricted'])} links refused the automated check: " + ", ".join(f"{b['url']} ({b['status']})" for b in lc["restricted"][:5]),
                "Open these by hand to confirm they work for visitors.", warn=True)

    counts = {s: sum(1 for c in checks if c["status"] == s) for s in ("fail", "warn", "pass")}
    result = {
        "url": pg["final_url"],
        "fetched_at": site.get("fetched_at"),
        "checks": checks,
        "counts": counts,
        "page": {k: pg.get(k) for k in ("title", "meta_description", "word_count", "lang", "canonical")} | {"h1": h1s, "first_words": pg.get("first_words")},
        "js_rendered_suspected": pg.get("js_rendered_suspected"),
    }
    out = out or os.path.join(d, "checks.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)
    for c in checks:
        print(f"{c['status'].upper():4} {c['priority']:6} {c['id']}: {c['evidence']}")
    print(json.dumps({"counts": counts, "written": out}))


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        sys.exit("usage: audit_checks.py <fetch_out_dir> [<out.json>]")
    main(sys.argv[1], sys.argv[2] if len(sys.argv) == 3 else None)
