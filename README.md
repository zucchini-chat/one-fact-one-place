# one-fact-one-place

A git pre-commit hook for repos that AI agents write to. It stops an agent's commit when a line it adds repeats a fact that already lives elsewhere in the repo's markdown, or links to a file or heading that does not exist. A person committing sees the same list and the commit goes through. Python 3.9+ standard library; the optional `.tyaml` type check also needs PyYAML.

Tools that keep an agent's memory in git mostly help the agent find and read it. This one checks what gets written: an agent that writes a fact a second time, in another file or further down the same one, leaves two copies that drift apart, and by the time anyone notices, that agent has moved on. It fits any repo whose notes, docs, `CLAUDE.md` or `AGENTS.md` agents keep editing, code repos included.

It is the memory part of [personal-agent-scaffold](https://github.com/zucchini-chat/personal-agent-scaffold) (a full personal-agent setup), on its own.

## Why it stops the commit
On a personal notes repo that several Claude Code agents write to in parallel, agents fixed at most 1 in 10 of the real duplicates the check showed them after the commit, and about 41-73% once it stopped the commit. In the stop's first week there: 283 stops on 214 commits, a median 8 s from the first stop to the commit going through, no `--no-verify`. The cost is noise: about a third of the lines it shows are real duplicates. Numbers, sample sizes and what is untested: [RESULTS.md](RESULTS.md).

## What it checks
For each `.md` and `.tyaml` line a commit adds or edits:
- **Duplicate.** Each new sentence (of an edited line, only the sentences holding new words; an edit that only deletes words or changes case, end punctuation or emphasis is skipped) against the most similar line in another file and in the rest of its own file, outside its own paragraph (in a `.tyaml`, its record; values are compared without their keys). BM25 word matching, rebuilt on each commit, no model and no index on disk. A hit shows from a score of 30 (`FLOOR` in `hooks/dupcheck_hook.py`), best first, at most 5 per commit, at most 40 sentences searched.
- **Broken link.** In markdown lines: `[x](path)` and `[x](path#anchor)` links, `file.md > "Heading"` references (backticks optional around the file name, `> "Sub"` repeatable; a heading or a `**bold label**` that holds the quoted words), and backticked `dir/file.ext` paths whose first folder exists. A path resolves from the linking file's folder first, then from the repo root; a backticked path may also be the tail of a longer one (`adapters/x.rs` for `src/adapters/x.rs`). Not checked: URLs, paths outside the repo, files git ignores, placeholders (`<x>`, `*`, `$`), fenced code. A commit that deletes or renames a file or a heading is also checked for lines elsewhere that link to it; a rename whose links were updated in the same commit is clean.
- **Old value** (shown, never stops). When an edit changes a number in place (`02:30` to `03:15`, `4417` to `8820`), the most similar line in another file that still holds the old number and not the new one, from a score of 20. Measured too noisy to stop a commit.

An agent's commit, stopped:
```
Commit stopped by the pre-commit check: the lines you are committing have the problems below.
1. docs/runbook.md:5 broken link: docs/deploy.md > "Roll forward" (no such heading in docs/deploy.md)
2. docs/runbook.md: Staging database backups run every night at 02:30 UTC into quarry-backups-eu.
   -> ops/backups.md:3 The staging database is backed up every night at 02:30 UTC to the bucket quarry-backups-eu.
Duplicate (->): keep the fact in one place, put a link in the other or cut it.
Broken link: fix the path or the heading, here or in the file that links.
Then commit again. A false alarm, or repeated on purpose: commit again with DUP_OK="<why, per number>" in front of `git commit`. Never --no-verify.
python3 tools/hooks/dupcheck_search.py "<text>" lists the 20 lines most like a sentence.
```

## Install
**Agent repos: a clone inside the repo (recommended).** In the repo's root:
```
git clone https://github.com/zucchini-chat/one-fact-one-place
echo /one-fact-one-place/ >> .gitignore
git config core.hooksPath one-fact-one-place/hooks
```
and one line in the repo's `CLAUDE.md` or `AGENTS.md`:
```
- Storage rules: @one-fact-one-place/RULES.md (Claude Code loads it from this line; any other agent reads that file before its first edit).
```
The clone is git-ignored, so the repo holds no copy of the hooks or the rules, and `git -C one-fact-one-place pull --ff-only` updates both. The relative `hooksPath` works wherever the repo is cloned; each clone runs these three commands once. Claude Code expands an `@path` import into the session's context, outside code spans only, so the path is not in backticks; Codex does not expand imports and reads the same line as an instruction. Keep the clone inside the working directory: Claude Code asks in an interactive dialog before loading an import from outside it, and a session that never shows that dialog never loads the rules. Without the clone git runs no hooks and says nothing, so have something the agent sees at session start report a missing `one-fact-one-place/hooks/pre-commit`.

**git `core.hooksPath`.** Copy `hooks/` into your repo, for example as `tools/hooks/`, commit it, and run in each clone:
```
git config core.hooksPath tools/hooks
```
Or keep one clone of this repo and point at it from any repo: `git config core.hooksPath ~/src/one-fact-one-place/hooks`. The setting is local config, so every clone needs it once; `git config --unset core.hooksPath` turns it off. It replaces `.git/hooks`: if the repo already has a pre-commit hook (husky's included), call `sh tools/hooks/pre-commit` from that hook instead. Only exit code 3 from a check stops the commit; a crash or a missing `python3` lets it through.

**[pre-commit](https://pre-commit.com) framework.** In `.pre-commit-config.yaml`:
```yaml
repos:
  - repo: https://github.com/zucchini-chat/one-fact-one-place
    rev: v0.1.0
    hooks:
      - id: dup-check
      - id: tyaml  # only if the repo has .tyaml files; pre-commit installs PyYAML for it
```
`dup-check` runs on every commit (`always_run`, so deleting or renaming a file is checked too) and prints its list even when the commit passes (`verbose`).

## Who is stopped
An agent, known by one of these environment variables:
- `CLAUDECODE`, which Claude Code sets in its shell;
- `ZUCCHINI_CHAT_ID`, which [Zucchini](https://zucchini.chat) sets for every agent it runs, Codex included (Zucchini keeps agent chats running on your own always-on machine);
- `DUP_CHECK_AGENT`, which you set yourself in the environment of any other agent's shell commands. Codex run outside Zucchini sets neither of the first two.

Anyone else, a person, a script or CI, gets the same list printed and the commit goes through.

**`DUP_OK`.** `DUP_OK="<why>" git commit ...` passes only the items a stop already showed the same chat in the last hour, matched by the file and text they point at. An item not shown before stops the commit again, listing only the new ones. The chat is `ZUCCHINI_CHAT_ID`, else `CLAUDE_CODE_SESSION_ID`; agents with neither count as one chat. Never `--no-verify`: it skips every other hook too, the type check included.

## Leaving files out
Left out by default, neither searched nor hit: changelog-type files (`CHANGELOG*`, `CHANGES*`, `HISTORY*`, `NEWS*`, any case) and symlinks (an `AGENTS.md` that links to `CLAUDE.md`). Leave out more, or bring one back, with the `dup-check` attribute in `.gitattributes`:
```
docs/archive/** -dup-check
*-transcript.md -dup-check
CHANGELOG.md dup-check
```
Leave out records that quote old text on purpose: logs, reviews, transcripts, templates meant to be copied. In the replays behind RESULTS.md, most false link reports came from such records naming a file that had since moved.

## Run log, failures, replay
- Each run with something to check appends one JSON line to `.git/dup-check/runs.jsonl`, inside the git directory, so it is never committed and never shows in `git status`: the time, the parent commit, each searched sentence with its best line in another file (`hit`) and in its own file (`own`) and their scores (those under the floor too, so the floor can be re-fit), the old-value candidates (`stale`), the link problems (`links`), what was shown, whether the commit stopped, the `DUP_OK` reason (`ok`), which agent variable was set and the chat.
- It fails open: its own error, a failing git command or its 6 s limit (not on Windows) logs an `error` line, prints `pre-commit check skipped: ...` and lets the commit through.
- `python3 hooks/dupcheck_hook.py <commit>` replays an older commit against today's files: it prints, stops nothing and logs nothing.

## Searching by hand
`python3 hooks/dupcheck_search.py "<text>"` prints the 20 lines most like a sentence, with their scores; `python3 hooks/dupcheck_search.py path/file.md:LINE` does the same for a line of the repo, leaving out its paragraph. The hook shows at most two hits per sentence; this finds a fact's other copies. `--history` adds under each hit the last commit that touched that line (`git blame`): its date, hash and subject.

## Typed YAML
Records that scripts read or that need required fields can go in a `.tyaml` file: two YAML documents, first `types:`, which gives each top-level key of the data the fields of its records, then `---` and the data. Field types: `str`, `int`, `num` (int or decimal), `bool`, `date` (YYYY-MM-DD), `a|b` (one of these words), `T[]` (a non-empty list of T), `?` at the end = optional; a field not listed fails.
```yaml
types:
  vendors:
    name: str
    renews: date
    plan: monthly|yearly
    seats: int?
    source: str?
---
vendors:
  - {name: Lunetra, renews: 2027-03-01, plan: yearly, seats: 12}
```
The pre-commit hook runs `hooks/tyaml.py` on each `.tyaml` file the commit adds or changes and stops any commit, a person's too, on a type error. A `''` anywhere on a line also fails (a grep for an apostrophe misses a doubled one): write such a value as a `|-` block. PyYAML (MIT) must be importable by the `python3` the hooks run; without it the check stops commits that touch a `.tyaml` file. The duplicate check reads `.tyaml` files without PyYAML and skips the fields `source` and `see`, which say where a fact comes from or where it lives.

## Storage rules
[RULES.md](RULES.md) is the section of a repo's `CLAUDE.md` or `AGENTS.md` that tells agents how to store facts: files hold current state and the git log holds history, save a decision in the same turn, one fact in one place, links resolve, what to do when `git commit` stops, commit by explicit path because parallel agents share a working tree, never hard-wrap prose, `.tyaml` for records. Import it ("Install") or paste it; a pasted copy can drop the `.tyaml` line when the repo does not use the type check, and the commit-by-path line when every agent works in its own clone or worktree. The rules alone are not enough ("Why it stops the commit"): the hook makes the agent stop and look; the rules tell it what to do then.

## Tests
`python3 -m unittest discover tests`: real commits in throwaway repos, about 25 s. The `.tyaml` tests need PyYAML and are skipped without it.

## Licence
MIT, see [LICENSE](LICENSE).
