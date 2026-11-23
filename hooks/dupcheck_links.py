"""The link check of one markdown line: each explicit repo path in it must resolve. What counts as one: a markdown link
`[x](path)`, `[x](path#anchor)` or `[x](#anchor)`, a reference definition `[x]: path`, `file.md > "Heading"`
(backticks optional, `> "Sub"` repeatable), and a backticked `dir/name.ext` with a known extension (EXT) whose first
folder exists; a bare `name.md` only when the commit deleted or renamed a file of that name (problems()).
A path resolves from the line's own folder first, then from the repo root; a backticked path or a heading reference
may also name any file whose path ends with it (`adapters/x.rs` for src/adapters/x.rs). A heading reference must name
a heading or a bold label of that file (has()), an anchor a heading; other files only need to exist. Not checked:
URLs, paths outside the repo (/abs, ~, ../ past the root, a first folder the repo lacks), paths git ignores (local
files such as secrets), placeholders (<x>, *, $, {x}), bare extensions (.tyaml), links inside code spans, lines inside
fenced code."""
import os, re, subprocess
from urllib.parse import unquote

EXT = set("md markdown mdx txt rst tyaml yaml yml json toml ini cfg csv tsv xml html css scss sql sh bash zsh py js mjs "
          "cjs ts tsx jsx go rs swift kt java rb ex exs c h cc cpp hpp cs php lock pdf png jpg jpeg gif svg".split())
CODE = re.compile(r"(`+)(.+?)\1")
LINK = re.compile(r"!?\[[^\]]*\]\(\s*(<[^>]*>|[^)\s]+)(?:\s+[\"'(][^)]*)?\)")
REF_DEF = re.compile(r"^\s{0,3}\[[^\]]+\]:\s+(<[^>]*>|\S+)")
HEADING_REF = re.compile(r"(?<![\w./>}~-])`?([\w./-]+\.md)`?((?:\s*>\s*[\"“][^\"”]+[\"”])+)")
PATH = re.compile(r"[\w@+-][\w.@+-]*(?:/[\w.@+-]+)*/?")
PLACEHOLDER = re.compile(r"[<>*{}$]")
ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}  # a hook's GIT_INDEX_FILE may be temporary


def fenced(text):
    """0-based indices of the lines inside ``` or ~~~ fences, the fence lines included."""
    out, fence = set(), None
    for i, l in enumerate(text.split("\n")):
        m = re.match(r"\s{0,3}(`{3,}|~{3,})", l)
        if fence or m:
            out.add(i)
        if m and not fence:
            fence = m[1]
        elif m and m[1][0] == fence[0] and len(m[1]) >= len(fence):
            fence = None
    return out


def norm(heading):
    """A heading's text as matched: without leading #s, symbols or numbering (`## 2. ⚑ Setup` is `setup`), without *,
    backticks or quotes, casefolded."""
    t = re.sub(r"^#+\s*|\s+#+\s*$", "", heading.strip())
    t = re.sub(r"^[^\w]*(?:\d+(?:\.\d+)*\.?\s+)?[^\w]*", "", t)
    return re.sub(r"[*`\"“”]", "", t).strip().casefold()


def headings(text):
    """The norm() texts of a markdown text's headings, fenced code left out."""
    skip = fenced(text)
    return [norm(l) for i, l in enumerate(text.split("\n")) if i not in skip and re.match(r"#{1,6}\s", l)]


def labels(text):
    """What a `file.md > "X"` reference may name: the headings, and the bold labels (`**X:**` anywhere in a line)."""
    skip = fenced(text)
    return headings(text) + [norm(b) for i, l in enumerate(text.split("\n")) if i not in skip
                             for b in re.findall(r"\*\*(.+?)\*\*", l)]


def anchors(text):
    """GitHub's anchors for the headings of a markdown text (a repeated one gets -1, -2, ...)."""
    out, seen = set(), {}
    for h in headings(text):
        s = re.sub(r"[^\w\- ]", "", h).replace(" ", "-")
        out.add(f"{s}-{seen[s]}" if s in seen else s)
        seen[s] = seen.get(s, 0) + 1
    return out


def has(ref, have):
    """Whether a norm() reference names one of `have`: as the whole of it or as whole words in it ("Browser" for
    "Browser (shared, logged in)", "founding roles" for "Target set addition - founding roles")."""
    pat = re.compile(r"(?<!\w)" + re.escape(ref) + r"(?!\w)")
    return any(pat.search(h) for h in have)


def ignored(root, paths):
    """Whether git ignores one of `paths`: a local file each clone makes for itself (secrets, scratch)."""
    return any(subprocess.run(["git", "-C", root, "check-ignore", "-q", "--no-index", "--", p], env=ENV).returncode == 0
               for p in paths)


def problems(root, file, line, cache=None, bare=()):
    """[(what the line says, why it does not resolve, the repo paths it may mean)] for the repo paths in `line` of
    `file` (relative to root). cache: {path: text} of the files read, shared across calls. A backticked bare
    `name.md` is checked only when its name is in `bare` (the names of files a commit deleted or renamed): elsewhere
    it often names a file of another tool or machine."""
    here, cache = os.path.dirname(file), {} if cache is None else cache

    def names(path):
        """The repo-relative paths `path` may mean, the line's folder first; none when it points outside the repo."""
        path = unquote(path)
        out = [os.path.normpath(p) for p in ([path[1:]] if path.startswith("/") else [os.path.join(here, path), path])]
        return [] if any(p.startswith("..") for p in out) else out

    def find(path):
        return next((p for p in names(path) if os.path.exists(os.path.join(root, p))), None)

    def missing(path):
        return not find(path) and not ignored(root, names(path))

    def anywhere(path):
        """The repo's files whose path ends with `path`: `adapters/x.rs` for src/adapters/x.rs, `x.md` for any x.md."""
        if "\0files" not in cache:
            r = subprocess.run(["git", "-C", root, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                               capture_output=True, encoding="utf-8", errors="replace", env=ENV)
            cache["\0files"] = [f for f in r.stdout.split("\0") if f]
        path = os.path.normpath(path)
        return [f for f in cache["\0files"] if f == path or f.endswith("/" + path)]

    def text(p):
        if p not in cache:
            try:
                with open(os.path.join(root, p), encoding="utf-8", errors="replace") as fh:
                    cache[p] = fh.read()
            except OSError:
                cache[p] = ""
        return cache[p]

    out = []
    plain = CODE.sub(lambda m: " " * len(m[0]), line)  # links inside code spans are examples
    for t in [m[1] for m in LINK.finditer(plain)] + [m[1] for m in REF_DEF.finditer(plain)]:
        t = t.strip("<>")
        if not t or re.match(r"[a-zA-Z][\w+.-]*:", t) or t.startswith(("~", "//")) or PLACEHOLDER.search(t):
            continue
        path, _, anchor = t.partition("#")
        if path and not names(path):
            continue
        p = find(path) if path else file
        if not p and missing(path):
            out.append((t, "no such file", names(path)))
        elif p and anchor and p.endswith(".md") and not re.fullmatch(r"L\d+(-L\d+)?", anchor) \
                and unquote(anchor).lower() not in anchors(text(p)):
            out.append((t, f"no heading for #{anchor} in {p}", [p]))
    named = set()
    spans = [m.span() for m in CODE.finditer(line)]
    for m in HEADING_REF.finditer(line):
        named.add(m[1])
        if not names(m[1]) or any(a <= m.start() and m.end() <= b for a, b in spans):  # inside one code span: an example
            continue
        ps = [p for p in names(m[1]) if os.path.isfile(os.path.join(root, p))] or anywhere(m[1])
        if not ps:
            if missing(m[1]):
                out.append((m[1], "no such file", names(m[1])))
            continue
        out += [(f'{m[1]} > "{h}"', f"no such heading in {ps[0]}", ps)
                for h in re.findall(r"[\"“]([^\"”]+)[\"”]", m[2]) if not any(has(norm(h), labels(text(p))) for p in ps)]
    for m in CODE.finditer(line):
        c = re.sub(r":\d+(?:-\d+)?$|#L\d+.*$", "", m[2].strip())  # file.md:12, file.md:12-20, file.py#L3
        if c in named or not PATH.fullmatch(c) or not names(c):
            continue
        last = c.rsplit("/", 1)[-1]
        ext = last.rsplit(".", 1)[1] if "." in last.lstrip(".") else ""
        if "/" in c and (ext not in EXT or not find(c.split("/")[0])) or "/" not in c and c not in bare:
            continue
        if missing(c) and not anywhere(c):
            out.append((c, "no such file", names(c)))
    return out


def orphans(root, git, gone, heads, cache):
    """Lines of the repo's markdown that link to a path in `gone` (deleted or renamed) or to a heading in `heads`
    [(file, norm() text)] that was removed, and so no longer resolve: [(file, line number, line, target, why)].
    Raises when git grep fails."""
    slugs = [(f, h, re.sub(r"[^\w\- ]", "", h).replace(" ", "-")) for f, h in heads]
    pats = {os.path.basename(p) for p in gone} | {x for _, h, s in slugs for x in (h, s)}
    if not pats:
        return []
    r = git("grep", "-n", "-z", "-I", "-i", "-F", "--untracked", *[a for p in sorted(pats) for a in ("-e", p)], "--", "*.md")
    if r.returncode > 1:
        raise RuntimeError(r.stderr.strip())
    out, code, names = [], {}, {os.path.basename(p) for p in gone}
    for hit in r.stdout.split("\n"):
        if hit.count("\0") < 2:
            continue
        f, n, line = hit.split("\0", 2)
        if f not in cache:
            with open(os.path.join(root, f), encoding="utf-8", errors="replace") as fh:
                cache[f] = fh.read()
        if f not in code:
            code[f] = fenced(cache[f])
        if int(n) - 1 in code[f]:
            continue
        for target, why, means in problems(root, f, line, cache, names):
            t = target.casefold()
            if set(means) & set(gone) or "/" not in target and target in names \
                    or any(hf in means and (h in t or s in t) for hf, h, s in slugs):
                out.append((f, int(n), line, target, why))
    return out
