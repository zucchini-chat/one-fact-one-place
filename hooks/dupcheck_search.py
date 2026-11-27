#!/usr/bin/env python3
"""Lines of the repo's markdown, .tyaml and line files most like a text or like one repo line, best first: file:line,
BM25 score, the line's best-matching sentence. The pre-commit check (dupcheck_hook.py) shows a hit from its FLOOR up.
Usage: dupcheck_search.py "text" [-k 20] [--history]
       dupcheck_search.py path/to/file.md:LINE [-k 20] [--history]   (or any file; that line's paragraph or record is
       left out, dupcheck.units)
--history adds under each hit the last commit that touched that line (git blame): date, hash, subject."""
import argparse, os, re, sys, time
from dupcheck import ROOT, git, search, units


def last_commit(f, n):
    r = git("blame", "--porcelain", "-L", f"{n},{n}", "--", f)
    if r.returncode:
        return "not committed yet"
    head, *rest = r.stdout.split("\n")
    sha = head.split(" ", 1)[0]
    if not sha.strip("0"):
        return "not committed yet"
    info = dict(l.split(" ", 1) for l in rest if " " in l and not l.startswith("\t"))
    return f"{time.strftime('%Y-%m-%d', time.localtime(int(info['author-time'])))} {sha[:8]} {info['summary'][:150]}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target")
    ap.add_argument("-k", type=int, default=20)
    ap.add_argument("--history", action="store_true")
    a = ap.parse_args()
    if not ROOT:
        sys.exit("not inside a git repository")
    m = re.fullmatch(r"(.+):(\d+)", a.target)
    path = m and next((p for p in (os.path.abspath(m[1]), os.path.join(ROOT, m[1])) if os.path.isfile(p)), None)
    if path or m and m[1].endswith((".md", ".tyaml")):
        if not path:
            sys.exit(f"no such file: {m[1]}")
        f, n = os.path.relpath(os.path.realpath(path), os.path.realpath(ROOT)), int(m[2])
        with open(path, encoding="utf-8", errors="replace") as fh:
            u = units(f, fh.read())
        if not 1 <= n <= len(u):
            sys.exit(f"{m[1]} has no line {n}")
        text, at = u[n - 1][0], (f, n)
    else:
        text, at = a.target, None
    if not re.search(r"\w", text):
        sys.exit(f"nothing to search for: {text!r}")
    for f, n, score, sentence in search([text], a.k, at=[at])[0]:
        print(f"{f}:{n}  {score:5.1f}  {sentence.strip()[:200]}")
        if a.history:
            print(f"      {last_commit(f, n)}")


if __name__ == "__main__":
    main()
