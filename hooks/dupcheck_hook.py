#!/usr/bin/env python3
"""The pre-commit check of the .md, .tyaml and line-file lines a commit adds or edits (README.md > "What it checks"):
- duplicate: per sentence the commit adds (every sentence of a new line; of an edited line, those holding new words),
  its most similar line in another file and in the rest of its own file (dupcheck.search), from FLOOR up;
- stale copy: per sentence where an edit changed a number, its most similar line in another file that still holds
  the old number and not the new one, from STALE_FLOOR up; shown, never stops;
- broken link: a path, heading or anchor in an added or edited markdown line that does not resolve, and a link
  elsewhere to a file or heading the commit deletes or renames (dupcheck_links).
At most MAX_HITS items are shown. A duplicate or a broken link stops an agent's commit (an AGENT variable is set;
exit 3) until it fixes them or commits again with DUP_OK="<why>" in front, which passes only items a stop showed the
same chat in the last hour; anyone else only sees them. Each run is logged to .git/dup-check/runs.jsonl. On its own
error, or at its LIMIT seconds, it logs an error line and the commit goes through.
`dupcheck_hook.py <commit>` replays an older commit against today's files: it prints, stops nothing, logs nothing."""
import ast, collections, difflib, json, os, re, signal, subprocess, sys, time

try:  # a broken install must not block commits: run() reports it and lets the commit through
    from dupcheck import CORPUS, ROOT, excluded, git, is_line, search, sentences, units, words as tokens
    from dupcheck_links import fenced, headings, norm, orphans, problems
    BROKEN = None
except Exception as e:
    BROKEN = repr(e)

CHAT = os.environ.get("ZUCCHINI_CHAT_ID") or os.environ.get("CLAUDE_CODE_SESSION_ID")  # who was shown an item
AGENT = ("CLAUDECODE", "ZUCCHINI_CHAT_ID", "DUP_CHECK_AGENT")  # set by Claude Code; by Zucchini; by you, for others
MAX_QUERIES, MAX_HITS, MAX_SWAP, LIMIT = 40, 5, 4, 6
FLOOR = 30  # raw BM25 score, as dupcheck_search.py prints it; how it was set: RESULTS.md
STALE_FLOOR = 20  # the same score, for a stale copy (shown, never stops: STOPS); set from RESULTS.md
STOPS = ("dup", "link")  # the kinds that stop an agent's commit
END_PUNCT = ".,;:!?()[]{}\"'“”‘’«»`*_"  # stripped from a word's ends when an edit is compared (words)
SEARCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dupcheck_search.py")
STOPPED = "Commit stopped by the pre-commit check: the lines you are committing have the problems below."
UNSEEN = "Commit stopped by the pre-commit check: DUP_OK passes only items a stop has already shown you, and these are new."
SEEN = "Possible problems in the lines you are committing:"


def how(shown):
    """What to do about the items shown, one line per kind among them."""
    search = os.path.relpath(SEARCH) if SEARCH.startswith(os.getcwd() + os.sep) else SEARCH
    kinds = {"link" if x[0] == "link" else "old" if x[7] else "dup" for x in shown}
    return "\n".join([line for kind, line in (
        ("dup", "Duplicate (->): keep the fact in one place, put a link in the other or cut it."),
        ("old", "Old value (still holds the old value): update that copy, or cut it and link to the one place."),
        ("link", "Broken link: fix the path or the heading, here or in the file that links.")) if kind in kinds] + [
        "Then commit again. A false alarm, or repeated on purpose: commit again with DUP_OK=\"<why, per number>\" in "
        "front of `git commit`. Never --no-verify.",
        f"python3 {search} \"<text>\" lists the 20 lines most like a sentence."])


def log_path():
    r = git("rev-parse", "--git-common-dir")
    if r.returncode:
        raise RuntimeError(r.stderr.strip())
    return os.path.join(ROOT, r.stdout.strip(), "dup-check", "runs.jsonl")


def hunks(commit):
    """(file, removed lines, added lines as (number, line)) per hunk of the CORPUS diff: of the commit being made (the
    index git hands the hook), or of an older `commit` (not the root commit). Raises when git fails."""
    args = ["diff", "--unified=0", "--no-color", "--no-ext-diff", "--no-textconv", "--src-prefix=a/", "--dst-prefix=b/"]
    diff = (git(*args, f"{commit}~1", commit, "--", *CORPUS) if commit else
            subprocess.run(["git", "-c", "core.quotePath=false", *args, "--cached", "--", *CORPUS],
                           capture_output=True, encoding="utf-8", errors="replace"))
    if diff.returncode:
        raise RuntimeError(diff.stderr.strip())
    f, old, new, header, n = None, [], [], True, 0
    for l in diff.stdout.split("\n") + ["diff --git end"]:
        if l.startswith(("diff --git", "@@")):
            if f and (new or old):
                yield f, old, new
            old, new, header = [], [], l.startswith("diff --git")
            if header:
                f = None
            else:
                n = int(re.search(r"\+(\d+)", l)[1])
        elif header and l.startswith("+++ "):
            f = l[4:].rstrip("\t")  # git adds a tab after a name with a space
            if f.startswith('"'):  # a name with ", \ or a control char is C-quoted even with core.quotePath=false
                f = ast.literal_eval(f)
            f = f[2:] if f.startswith("b/") else None
        elif not header and l.startswith("-"):
            old.append(l[1:])
        elif not header and l.startswith("+"):
            new.append((n, l[1:]))
            n += 1


def words(text):
    """Lowercased whitespace tokens without punctuation or markdown emphasis at their ends: `Signal,` and `**signal**`
    are `signal`, while `$100` and `$-100` stay different."""
    return [w for w in (t.strip(END_PUNCT) for t in text.lower().split()) if w]


def changed(old, line):
    """What to search for `line`: (its sentences holding new words, [(a sentence of the line it replaced, its
    swaps)]). A new line (no line of `old` has at least half the same words) is all new and replaces nothing; an edit
    only searches the sentences holding inserted or replaced words, so one that only deleted words or changed case,
    end punctuation or emphasis searches nothing. A swap is a number changed in place: a span of at most MAX_SWAP
    words replaced by at most MAX_SWAP words holding a number, as (the old span, its dupcheck.words() tokens the new
    line lacks, the new span's tokens the old line lacks), kept when the tokens the new line lacks hold 3+ digits
    (`4417`, `02:30`, `€950`; not a day or a count like `18`). Other edits are mostly rewordings or a copy cut to a
    link, whose other copy is meant to stay: RESULTS.md."""
    sm = difflib.SequenceMatcher(None, autojunk=False)
    sm.set_seq2(words(line))
    ratio = lambda o: (sm.set_seq1(words(o)), sm.quick_ratio())[1]
    was = max(old, key=ratio) if old else ""
    sm.set_seq1(words(was))
    if sm.ratio() < 0.5:
        return sentences(line), []
    ops = sm.get_opcodes()
    new = {j for op, _, _, j1, j2 in ops if op in ("insert", "replace") for j in range(j1, j2)}
    a, b = words(was), words(line)
    ta, tb = set(tokens(was)), set(tokens(line))
    swaps = [(i1, " ".join(a[i1:i2]), sorted(set(tokens(" ".join(a[i1:i2]))) - tb), sorted(set(tokens(" ".join(b[j1:j2]))) - ta))
             for op, i1, i2, j1, j2 in ops if op == "replace" and i2 - i1 <= MAX_SWAP and j2 - j1 <= MAX_SWAP
             and re.search(r"\d", " ".join(b[j1:j2]))]
    swaps = [x for x in swaps if len(re.findall(r"\d", "".join(t for t in x[2] if re.search(r"\d", t)))) >= 3]
    return ([s for s, idx in spans(line) if new & idx],
            [(s, [x[1:] for x in swaps if x[0] in idx]) for s, idx in spans(was) if any(x[0] in idx for x in swaps)])


def held(sentence, swaps):
    """The old spans of `swaps` (changed()) whose tokens `sentence` all holds, while it holds none of the new ones."""
    t = set(tokens(sentence))
    return [old for old, o, n in swaps if set(o) <= t and not set(n) & t]


def spans(text):
    """(sentence, the indices of its words in words(text)) per sentence; sentences() splits only at whitespace, so
    word indices map onto sentences."""
    out, i = [], 0
    for s in sentences(text):
        n = len(words(s))
        out.append((s, set(range(i, i + n))))
        i += n
    return out


def stops(path):
    """The stopped runs among the last 200 of the log."""
    with open(path, encoding="utf-8") as fh:
        lines = collections.deque(fh, maxlen=200)
    for l in lines:
        try:
            r = json.loads(l)
        except ValueError:
            continue
        if r.get("stopped"):
            yield r


def log(record):
    path = log_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **record, "chat": CHAT}, ensure_ascii=False) + "\n")


def moved(commit):
    """The old paths of the files the commit deletes or renames (any file, not only markdown)."""
    args = ["diff", "--name-status", "-z", "-M", "--diff-filter=DR", "--no-ext-diff"]
    r = (git(*args, f"{commit}~1", commit) if commit else
         subprocess.run(["git", "-c", "core.quotePath=false", *args, "--cached"], capture_output=True, encoding="utf-8",
                        errors="replace"))
    if r.returncode:
        raise RuntimeError(r.stderr.strip())
    f, out, i = r.stdout.split("\0"), [], 0
    while i < len(f) - 1:
        out.append(f[i + 1])
        i += 3 if f[i].startswith("R") else 2
    return out


def check(replay=None):
    """The items to show for the commit being made, or for `replay`, links first, then duplicates and then stale
    copies by score: (kind, committed
    file, committed text, target file, target line, target text, score, note: a link's why or a stale copy's old
    value), and the record to log."""
    qs, olds, links, heads, parsed, cache = {}, {}, [], [], {}, {}
    # qs: (file, sentence): its line number, None when the working tree has it elsewhere; olds: (file, replaced
    # sentence): (the new line, the replaced words)
    hs = list(hunks(replay))
    skip = excluded({f for f, _, _ in hs})
    for f, old, new in hs:
        if f in skip:
            continue
        if f not in parsed:
            try:
                with open(os.path.join(ROOT, f), encoding="utf-8", errors="replace") as fh:
                    body = fh.read()
            except OSError:  # deleted since
                body = ""
            parsed[f] = body.split("\n"), units(f, body), fenced(body), headings(body)
        raw, u, code, have = parsed[f]
        if f.endswith(".md"):
            heads += [(f, h) for h in {norm(l) for l in old if re.match(r"#{1,6}\s", l)} - set(have)]
        for n, l in new:
            n = n if n <= len(raw) and raw[n - 1] == l else None
            if f.endswith(".md") and not (n and n - 1 in code):
                links += [(f, n, l, target, why) for target, why, _ in problems(ROOT, f, l, cache)]
            t = u[n - 1][0] if n else l
            if not is_line(t):
                continue
            add, replaced = changed(old, t)
            for s in add:
                if is_line(s) and len(qs) < MAX_QUERIES:
                    qs.setdefault((f, s), n)
            for s, sw in replaced:
                if is_line(s) and len(olds) < MAX_QUERIES:
                    olds.setdefault((f, s), (t, sw))
    found = orphans(ROOT, git, moved(replay), heads, cache)
    out = excluded({x[0] for x in found})
    links += [x for x in found if x[0] not in out and (x[0], x[3]) not in {(f, t) for f, _, _, t, _ in links}]
    qs, olds = list(qs.items()), list(olds.items())
    found = search([s for (_, s), _ in qs + olds], 20, at=[(f, n) for (f, _), n in qs] + [(f, None) for (f, _), _ in olds]) \
        if qs or olds else []
    results = [(next((h for h in r if h[0] != f), None), next((h for h in r if h[0] == f), None))  # other file, own file
               for ((f, _), _), r in zip(qs, found)]
    stale = [next((h for h in r if held(h[3], sw)), None) for (_, (_, sw)), r in zip(olds, found[len(qs):])]
    items = [("link", f, l, f, n, target, 0, why) for f, n, l, target, why in links]
    hits = [("dup", f, s, h[0], h[1], h[3], h[2], "") for ((f, s), _), r in zip(qs, results) for h in r if h and h[2] >= FLOOR]
    hits += [("stale", f, t, h[0], h[1], h[3], h[2], ", ".join(held(h[3], sw)))
             for ((f, _), (t, sw)), h in zip(olds, stale) if h and h[2] >= STALE_FLOOR]
    for x in sorted(hits, key=lambda x: (x[0] == "stale", -x[6])):
        same = [i for i, y in enumerate(items) if y[0] != "link" and y[3:5] == x[3:5]]
        if not same:
            items.append(x)
        elif x[0] == "stale":  # a duplicate that also holds the old number: say so
            items[same[0]] = items[same[0]][:7] + (x[7],)
    record = {"queries": [{"file": f, "text": s, "hit": hit, "own": own} for ((f, s), _), (hit, own) in zip(qs, results)],
              "stale": [{"file": f, "text": s, "swaps": sw, "hit": h} for ((f, s), (_, sw)), h in zip(olds, stale)],
              "links": [{"file": f, "line": n, "target": t, "why": w} for f, n, _, t, w in links]}
    return items, record


def key(item):
    """What makes an item the same across tries: its kind, the file it points at and that file's text (a sentence or,
    for a link, the target), never a line number, which an edit above it moves."""
    return [item[0], item[3], item[5]]


def main(replay=None):
    items, record = check(replay)
    if not any(record.values()):
        return
    why = os.environ.get("DUP_OK", "").strip()
    agent = None if replay else next((v for v in AGENT if v in os.environ), None)
    new = items
    if why and agent and items and os.path.exists(log_path()):  # drop the items a stop showed in the last hour
        since = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(time.time() - 3600))
        seen = {tuple(k) for r in stops(log_path()) if r["time"] >= since and r.get("chat") == CHAT for k in r["shown"]}
        new = [x for x in items if tuple(key(x)) not in seen]
    shown = new[:MAX_HITS]
    stop = bool(agent and any(x[0] in STOPS for x in shown))
    if shown:
        print(UNSEEN if stop and why else STOPPED if stop else SEEN)
        for i, (kind, f, text, hit_file, n, target, _, note) in enumerate(shown, 1):
            if kind == "link":
                print(f"{i}. {f}{f':{n}' if n else ''} broken link: {target} ({note})")
            else:
                old = f"still holds the old value ({note}): " if note else ""
                print(f"{i}. {f}: {text.strip()[:120]}\n   {old}-> {hit_file}:{n} {target.strip()[:200]}")
        if stop:
            print(how(shown))
    if not replay:
        log({"parent": git("rev-parse", "--short", "HEAD").stdout.strip(), **record,
             "shown": [key(x) for x in shown], "stopped": stop, "ok": why or None, "agent": agent})
    if stop:
        sys.exit(3)


def give_up(error, replay):
    """Say and log why the commit goes through unchecked (a replay logs nothing); never raises."""
    print(f"pre-commit check skipped: {error[:300]}", file=sys.stderr)
    if not replay:
        try:
            log({"error": error[:300]})
        except Exception:
            pass


def run():
    replay = sys.argv[1] if len(sys.argv) > 1 else None

    def timeout(*_):
        give_up("timeout", replay)
        os._exit(0)

    try:
        if hasattr(signal, "SIGALRM"):  # not on Windows, which runs without the limit
            signal.signal(signal.SIGALRM, timeout)
            signal.alarm(LIMIT)
        if BROKEN:
            raise RuntimeError(BROKEN)
        main(replay)
    except Exception as e:
        give_up(repr(e), replay)


if __name__ == "__main__":
    run()
