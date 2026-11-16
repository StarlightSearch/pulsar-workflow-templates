"""Check a cold email draft against the rules that decide whether it gets read.

Usage: python3 check_email.py <email.md> "<Company name>"

email.md starts with "Subject: ..." then a blank line, then the body: a greeting
line ("Hi Sam," or "Hi,"), the message, a single closing question as the last
line before the sign-off, and "[Your name]" as the last line.
Prints one PROBLEM line per rule broken, then "ok" or a count, and a
"words: n" line. Exits 1 when there are problems.
"""
import re
import sys

BANNED = [
    "i hope this email finds you well", "i hope you're well", "i hope you are well", "my name is", "i came across",
    "i wanted to reach out", "just reaching out", "quick question", "leverage", "synergy", "best-in-class",
    "world-class", "cutting-edge", "game-changer", "game changer", "unlock", "revolutionize", "revolutionise",
    "take it to the next level", "circle back", "touch base", "here's the thing", "i'll be honest",
    "say goodbye to", "seamless", "streamline", "robust", "leading provider", "pick your brain",
    "it's not about", "not just", "the result?",
]


def main(path: str, company: str) -> None:
    with open(path, encoding="utf-8") as f:
        text = f.read().strip()
    problems = []
    m = re.match(r"(?i)^subject:[ \t]*([^\n]+)\n\s*\n(.*)$", text, re.S)
    if not m:
        print("PROBLEM: email.md must start with 'Subject: ...', then a blank line, then the body")
        sys.exit(1)
    subject, body = m.group(1).strip(), m.group(2).strip()
    body_words = re.findall(r"[\w'’-]+", body)
    words = len(body_words)
    sw = len(subject.split())
    if sw < 2 or sw > 6:
        problems.append(f"the subject has {sw} words; use 2 to 6, plain, like a colleague would write")
    if re.search(r"[!?]|^(re|fwd?):", subject, re.I):
        problems.append("the subject must not use ! or ?, or a fake Re:/Fwd:")
    if words > 150:
        problems.append(f"the body is {words} words; cut it to 150 or fewer")
    if words < 40:
        problems.append(f"the body is only {words} words; it needs the hook, the problem and one ask")
    if company and company.lower() not in text.lower():
        problems.append(f"the email never names {company}; the opening should show it was written for them")
    if chr(0x2014) in text:
        problems.append("the email contains an em-dash; use a comma or a full stop")
    low = text.lower().replace("’", "'")
    for b in BANNED:
        if b in low:
            problems.append(f"remove the stock phrase '{b}'")
    links = re.findall(r"https?://\S+", body)
    if len(links) > 1:
        problems.append(f"{len(links)} links; use at most one, ideally none")
    q = body.count("?")
    lines = [l.strip() for l in body.splitlines() if l.strip()]
    while lines and (lines[-1] == "[Your name]" or re.fullmatch(r"[A-Za-z ,]{1,25},", lines[-1])):
        lines.pop()  # the sign-off ("Best," then "[Your name]")
    if q != 1:
        problems.append(f"{q} questions; use exactly one, as the closing ask" if q else "there is no question; end with one low-friction ask")
    elif not lines or not lines[-1].endswith("?"):
        problems.append("the question must be the last line before the sign-off")
    if lines and not re.fullmatch(r"(Hi|Hello)( [A-Z][\w'’-]+)?,", lines[0]):
        problems.append("the first line must be the greeting: 'Hi <first name>,' with the contact's real first name, or 'Hi,' when none is given")
    if not body.splitlines()[-1].strip() == "[Your name]":
        problems.append("end with '[Your name]' on its own line")
    for ph in re.findall(r"<[^<>\n]{1,40}>", text):
        problems.append(f"placeholder {ph} is left in the email; fill it in or rewrite the line")
    for ph in re.findall(r"\[[^\]\n]{1,60}\]", text):
        if ph not in ("[Your name]", "[ONE LINE ON WHAT YOU OFFER]"):
            problems.append(f"placeholder {ph} is left in the email; fill it in or rewrite the line")
    if body.count("!") > 1:
        problems.append("more than one exclamation mark")
    you = len(re.findall(r"\b(you|your|you're|yours)\b", low))
    we = len(re.findall(r"\b(i|we|our|us|my|i'm|we're)\b", low))
    if we > you + 2:
        problems.append(f"the email talks about the sender ({we}x I/we) more than the reader ({you}x you); lead with their world")
    first = body.splitlines()[0] if body else ""
    if re.match(r"(?i)^(hi|hello|hey|dear)\b[^,\n]*,?\s*$", first) and len(body.splitlines()) > 1:
        opener = next((l for l in body.splitlines()[1:] if l.strip()), "")
    else:
        opener = first
    if re.match(r"(?i)^\s*(i am|i'm|we are|we're|my name|our company|at \w+ we)", opener):
        problems.append("the first line is about the sender; open with something about them")
    for p in problems:
        print(f"PROBLEM: {p}")
    print(f"words: {words}")
    print("ok" if not problems else f"{len(problems)} problem(s)")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit('usage: check_email.py <email.md> "<Company name>"')
    main(sys.argv[1], sys.argv[2])
