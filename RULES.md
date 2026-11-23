# Storage rules

Paste the section below into the `CLAUDE.md` or `AGENTS.md` of a repo that agents write to. The rules alone are not enough: on the repo where this was measured, agents fixed at most 1 in 10 of the real duplicates shown to them after the commit, and about 41-73% once the commit stopped ([RESULTS.md](RESULTS.md)). The hook makes the agent stop and look; the rules tell it what to do then.

```markdown
## Storing facts
- **Files hold the current state; the git log holds the history.** When a fact changes, replace it in place. The commit message carries the old value, the date, the reason and where the new value came from. No "as of", "previously" or "(corrected)" trails in the files.
- **One fact in one place.** Update the file that already covers the subject instead of starting a new one. A fact found in two places is fixed in one and replaced by a link in the other, never edited twice.
- **Links resolve.** A path, `file.md` > "Heading" reference or #anchor you write points at something that exists. When you rename or delete a file or a heading, fix what links to it in the same commit.
- **`git commit` checks this.** It stops when a line you add may repeat a fact that lives elsewhere, in another file or in the same one, or links to nothing. Fix each numbered item and commit again; when the repeat is on purpose or the hit is wrong, commit again with `DUP_OK="<why, per number>"` in front of `git commit`. Never `--no-verify`: it skips every other check too. A line saying another file "still holds the old value" of a number you changed does not stop the commit: update that copy if it states the same fact.
- **Commit by explicit path:** `git commit -m "..." -- <paths>` (a new file needs `git add <path>` first). Never `git add -A`, `git add .` or a bare `git commit`: other agents work in this same working tree, and a bare commit takes whatever they have staged. Never stash, checkout, restore, reset or clean a file you did not change: its uncommitted edits are another agent's work.
- **Never hard-wrap prose.** One paragraph or list item is one line, so a diff shows only the fact that changed and the check compares whole sentences.
- **Records that scripts read or that need required fields go in a `.tyaml` (typed YAML) file; prose stays in `.md`.** A `.tyaml` holds two YAML documents: first `types:`, which gives each top-level key of the data the fields of its records, then `---` and the data. Field types: `str`, `int`, `num` (int or decimal), `bool`, `date` (YYYY-MM-DD), `a|b` (one of these words), `T[]` (a non-empty list of T), `?` at the end = optional; a field not listed fails. `git commit` stops on a type error.
```

Drop the `.tyaml` line if the repo does not use the type check, and the commit-by-path line if every agent works in its own clone or worktree.
