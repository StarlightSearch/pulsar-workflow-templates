"""Check a drafted support reply and its triage before they are handed over.

Usage: python3 check_reply.py <reply.md> <output.json> <ticket.txt> <help_dir_or_file> [...]

Checks, printing one PROBLEM line each:
  - output.json has the fields and allowed values the workflow promises;
  - every source in output.json is a real file that was searched;
  - the reply is between 40 and 220 words and has no em-dashes;
  - every link, email address and menu path ("Settings > Billing") in the
    reply appears in the ticket or a help file, so nothing is invented;
  - no unfilled placeholder other than [Your name] is left.
Prints "ok" and exits 0 when clean, else exits 1.
"""
import json
import os
import re
import sys

CATEGORIES = {"bug", "how-to", "feature-request", "billing", "account", "integration", "security", "data", "performance"}
ROUTES = {"tier-1", "tier-2", "engineering", "product", "security", "billing"}
PRIORITIES = {"P1", "P2", "P3", "P4"}
ANSWERED = {"fully", "partly", "no"}
EXTS = (".md", ".markdown", ".txt", ".html", ".htm")


def read(p: str) -> str:
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


def help_files(paths: list[str]) -> dict[str, str]:
    out = {}
    for root in paths:
        if os.path.isfile(root):
            out[os.path.basename(root)] = read(root)
        elif os.path.isdir(root):
            for d, dirs, files in os.walk(root):
                dirs[:] = [x for x in dirs if not x.startswith(".")]
                for x in files:
                    if x.lower().endswith(EXTS):
                        p = os.path.join(d, x)
                        out[os.path.relpath(p, root)] = read(p)
    return out


def squash(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("&gt;", ">")).strip().lower()


def main(reply_p: str, out_p: str, ticket_p: str, roots: list[str]) -> None:
    problems = []
    reply = read(reply_p)
    try:
        tri = json.loads(read(out_p))
    except Exception as e:
        tri = {}
        problems.append(f"output.json is not valid JSON ({type(e).__name__})")
    files = help_files(roots)
    known = squash(read(ticket_p) + "\n" + "\n".join(files.values()))

    for key, allowed in (("category", CATEGORIES), ("route_to", ROUTES), ("priority", PRIORITIES), ("answered_from_articles", ANSWERED)):
        if tri.get(key) not in allowed:
            problems.append(f"output.json {key} is {tri.get(key)!r}; use one of {sorted(allowed)}")
    if not str(tri.get("summary", "")).strip():
        problems.append("output.json has no summary")
    sources = tri.get("sources", [])
    if not isinstance(sources, list):
        problems.append("output.json sources must be a list")
        sources = []
    names = set(files)
    base = {os.path.basename(n): n for n in names}
    for s in sources:
        f = s.get("file") if isinstance(s, dict) else s
        if f not in names and os.path.basename(str(f)) not in base:
            problems.append(f"source {f!r} is not one of the help files searched")
    if tri.get("answered_from_articles") in ("fully", "partly") and not sources:
        problems.append("answered_from_articles says the articles answered it, but sources is empty")
    if tri.get("answered_from_articles") == "no" and sources:
        problems.append("answered_from_articles is 'no' but sources are listed; list only sections the reply relies on")

    words = len(re.findall(r"\b[\w'£$€.,%-]+\b", reply))
    if words < 40 or words > 220:
        problems.append(f"the reply is {words} words; keep it between 40 and 220")
    if chr(0x2014) in reply:
        problems.append("the reply contains an em-dash; use a comma, a full stop or brackets")
    for url in re.findall(r"https?://[^\s)>\]]+", reply):
        if squash(url.rstrip(".,")) not in known:
            problems.append(f"the link {url} is not in the ticket or the help files; remove it")
    for mail in re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", reply):
        if squash(mail.rstrip(".")) not in known:
            problems.append(f"the address {mail} is not in the ticket or the help files; remove it")
    # Menu paths: each "A > B" step must appear in a help file or the ticket.
    for a, b in re.findall(r"([\w-]+)\s*>\s*(?=([\w-]+))", reply.replace("&gt;", ">")):
        if squash(f"{a} > {b}") not in known:
            problems.append(f"the menu step '{a} > {b}' is not in any help file; copy menu paths exactly")
    for ph in re.findall(r"\[[^\]\n]{1,40}\]", reply):
        if ph.lower() != "[your name]":
            problems.append(f"placeholder {ph} is left in the reply; fill it from the ticket or drop it")

    for p in problems:
        print(f"PROBLEM: {p}")
    print("ok" if not problems else f"{len(problems)} problem(s)")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    if len(sys.argv) < 5:
        sys.exit("usage: check_reply.py <reply.md> <output.json> <ticket.txt> <help_dir_or_file> [...]")
    main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:])
