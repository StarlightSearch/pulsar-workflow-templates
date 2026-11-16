"""Pull candidate facts (prices, trials, customer counts, compliance) out of fetched pages.

Usage: python3 extract_facts.py <fetch_out_dir> [<fetch_out_dir> ...]

Reads every pages/*.md written by fetch_site.py and prints JSON:
  {"<dir name>": {"pages": [urls], "facts": [{"kind", "text", "url"}]}}
"text" is the whole line the match sits in (cut to 300 characters), so a fact
can be checked in context and quoted with its source. These are candidates,
not conclusions: read each in context before using it.
"""
import glob
import json
import os
import re
import sys

MONEY = r"(?:[$€£]\s?\d[\d,.]*|\d[\d,.]*\s?(?:USD|EUR|GBP|usd|eur|gbp)\b)"
PATTERNS = {
    "price": re.compile(MONEY + r"(?:\s*(?:/|per|a|an)\s*(?:mo|month|yr|year|user|seat|site|member|editor))?", re.I),
    "trial": re.compile(r"\b(free trial|\d{1,3}[- ]day (?:free )?trial|free (?:plan|tier|forever)|no credit card)\b", re.I),
    "scale_claim": re.compile(r"\b(?:trusted by|used by|join(?:ed)?|over|more than)\s+[\d,.]+\s?(?:k|m|million|thousand)?\+?\s+(?:customers|companies|teams|businesses|websites|sites|users|people|organi[sz]ations)", re.I),
    "founded": re.compile(r"\b(?:founded|started|since|launched)\s+(?:in\s+)?(?:19|20)\d{2}\b", re.I),
    "team": re.compile(r"\b(?:team of|we are|we're)\s+(?:a\s+)?[\d]+\s+(?:people|employees|humans)?|\b\d+\s+(?:employees|team members)\b", re.I),
    "compliance": re.compile(r"\b(GDPR|CCPA|PECR|SOC ?2|ISO ?27001|HIPAA|cookie banner|cookieless|no cookies)\b", re.I),
    "hosting": re.compile(r"\b(?:hosted|data (?:is |stays )?(?:stored|hosted)|servers?)\s+(?:in|on)\s+(?:the\s+)?(?:EU|European Union|Europe|Germany|US|United States|Canada|UK|[A-Z][a-z]+)\b", re.I),
    "integrations": re.compile(r"\b\d+\+?\s+integrations\b|\bintegrat(?:es|ions?) with\b", re.I),
    "open_source": re.compile(r"\bopen[- ]source\b|\bself[- ]host", re.I),
}


def main(dirs: list[str]) -> None:
    out = {}
    for d in dirs:
        facts, pages, seen = [], [], set()
        for md in sorted(glob.glob(os.path.join(d, "pages", "*.md"))):
            with open(md, encoding="utf-8", errors="replace") as f:
                text = f.read()
            m = re.match(r"<!-- (\S+) fetched", text)
            url = m.group(1) if m else os.path.basename(md)
            pages.append(url)
            for line in text.splitlines():
                if line.startswith("<!--"):
                    continue
                for kind, rx in PATTERNS.items():
                    if rx.search(line):
                        key = (kind, line.strip()[:120])
                        if key in seen:
                            continue
                        seen.add(key)
                        facts.append({"kind": kind, "text": line.strip()[:300], "url": url})
        # Keep the output readable: at most 25 lines of each kind per competitor.
        capped, count = [], {}
        for f in facts:
            count[f["kind"]] = count.get(f["kind"], 0) + 1
            if count[f["kind"]] <= 25:
                capped.append(f)
        out[os.path.basename(os.path.normpath(d))] = {"pages": pages, "facts": capped, "counts": count}
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: extract_facts.py <fetch_out_dir> [...]")
    main(sys.argv[1:])
