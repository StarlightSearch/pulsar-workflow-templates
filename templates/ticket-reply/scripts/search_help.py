"""Find the help-article sections that best match a support ticket.

Usage: python3 search_help.py <query.txt> <dir_or_file> [<dir_or_file> ...] [--top 8]

Reads every .md, .markdown, .txt, .html and .htm file under the given paths
(recursively, at most 3000 files), splits each into sections at its headings,
and ranks the sections against the query with BM25. Prints JSON:
  {"files": n, "sections": n, "results": [{"file", "heading", "score", "text"}]}
"text" is the whole section (cut at 2000 characters). Scores are relative:
compare them within one search, not across searches.
"""
import json
import math
import os
import re
import sys
from collections import Counter

EXTS = (".md", ".markdown", ".txt", ".html", ".htm")
STOP = set("""a about above after again against all am an and any are as at be because been before being below between both but by can
could did do does doing down during each few for from further had has have having he her here hers him his how i if in into is it its
itself just me more most my no nor not now of off on once only or other our ours out over own same she should so some such than that the
their them then there these they this those through to too under until up very was we were what when where which while who whom why will
with would you your yours hi hello thanks thank please regards dear also get got im ive dont cant""".split())


def stem(w: str) -> str:
    for suf in ("ations", "ation", "ings", "ing", "ies", "ied", "es", "ed", "s"):
        if len(w) > len(suf) + 2 and w.endswith(suf):
            return w[: -len(suf)] + ("y" if suf in ("ies", "ied") else "")
    return w


def tokens(text: str) -> list[str]:
    return [stem(w) for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP and len(w) > 1]


def strip_html(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|nav|footer)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?i)<h([1-4])[^>]*>", lambda m: "\n" + "#" * int(m.group(1)) + " ", html)
    html = re.sub(r"(?i)</h[1-4]>|<br\s*/?>|</p>|</li>", "\n", html)
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"[ \t]+", " ", text)


def sections(path: str, root: str) -> list[dict]:
    with open(path, encoding="utf-8", errors="replace") as f:
        raw = f.read()
    if path.lower().endswith((".html", ".htm")):
        raw = strip_html(raw)
    rel = os.path.relpath(path, root) if os.path.isdir(root) else os.path.basename(path)
    title, out, head, buf = None, [], None, []
    for line in raw.splitlines():
        m = re.match(r"^\s*(#{1,4})\s+(.*\S)", line)
        if m:
            if buf and "".join(buf).strip():
                out.append({"heading": head or title or rel, "lines": buf})
            if title is None:
                title = m.group(2)
            head = m.group(2)
            buf = [line]
        else:
            buf.append(line)
    if buf and "".join(buf).strip():
        out.append({"heading": head or title or rel, "lines": buf})
    res = []
    for s in out:
        text = "\n".join(s["lines"]).strip()
        # Index the article title with every section, so "Downloading invoices" helps its sub-sections too.
        res.append({"file": rel, "path": path, "heading": s["heading"], "title": title or rel, "text": text})
    return res


def main(argv: list[str]) -> None:
    top = 8
    if "--top" in argv:
        i = argv.index("--top")
        top = int(argv[i + 1])
        argv = argv[:i] + argv[i + 2 :]
    if len(argv) < 2:
        sys.exit("usage: search_help.py <query.txt> <dir_or_file> [...] [--top 8]")
    with open(argv[0], encoding="utf-8", errors="replace") as f:
        query = tokens(f.read())
    secs, nfiles = [], 0
    for root in argv[1:]:
        paths = []
        if os.path.isfile(root):
            paths = [root]
        elif os.path.isdir(root):
            for d, dirs, files in os.walk(root):
                dirs[:] = [x for x in sorted(dirs) if not x.startswith(".")]
                paths += [os.path.join(d, x) for x in sorted(files) if x.lower().endswith(EXTS)]
        for p in paths:
            if nfiles >= 3000 or os.path.abspath(p) == os.path.abspath(argv[0]):
                continue
            nfiles += 1
            try:
                secs += sections(p, root)
            except OSError:
                continue
    if not secs or not query:
        print(json.dumps({"files": nfiles, "sections": len(secs), "results": []}))
        return
    docs = [tokens(s["title"] + " " + s["heading"] + " " + s["text"]) for s in secs]
    avg = sum(len(d) for d in docs) / len(docs)
    df = Counter(t for d in docs for t in set(d))
    n = len(docs)
    qset = Counter(query)
    scored = []
    for s, d in zip(secs, docs):
        tf = Counter(d)
        score = 0.0
        for t, qn in qset.items():
            if t not in tf:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            score += idf * tf[t] * 2.2 / (tf[t] + 1.2 * (0.25 + 0.75 * len(d) / avg)) * min(qn, 3)
        if score > 0:
            scored.append((score, s))
    scored.sort(key=lambda x: -x[0])
    results = [
        {"file": s["file"], "heading": s["heading"], "score": round(sc, 2), "text": s["text"][:2000]}
        for sc, s in scored[:top]
    ]
    print(json.dumps({"files": nfiles, "sections": n, "results": results}, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
