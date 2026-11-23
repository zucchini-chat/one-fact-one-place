# Results

What the check was measured on, and what is not tested yet. The repos are private, so this file holds numbers only.

## The repos
- **A:** a personal notes repo that several Claude Code agents write to in parallel, in one working tree: about 660 markdown and `.tyaml` files, 43-48k sentences. All measurements of the stop are from A, November 2026.
- **B:** a second repo of the same owner and agents, code with markdown and SQL data files; used only for the same-file measurement.
- **C:** a product's code repo (apps on several platforms and a backend) with 32 markdown files: `CLAUDE.md` per component, a backlog, ops notes. Used for the noise test and the replays of the new checks.
- **S:** [personal-agent-scaffold](https://github.com/zucchini-chat/personal-agent-scaffold), about 500 sentences.

A hit is labelled a duplicate (D) when it states the same fact, so that someone changing the fact would edit both lines; related (R) when it is on the same subject or only points to where the fact lives; noise (N) otherwise. Labels come from an LLM judge in two steps (Sonnet and Haiku on every pair, then Opus with a strict rubric on each pair either called D) unless marked "by hand". On 90 hand-judged hits, Sonnet and Haiku each agreed with the hand label 77% of the time; the disagreements were on the D/R border.

## Shown after the commit vs stopping the commit
- **Shown after the commit** (a post-commit hook that printed the hits), A, 10-15 Nov: 260 runs, 1,060 sentences searched, 362 lines shown, 119 of them D (33%). For a shown D, one side was rewritten within the hour in 14 of 119 cases (12%); for an R pair, 13 of 140 (9%); for an N pair, 3 of 103 (3%). Part of the 12% is ordinary further work on the topic, so at most about 1 in 10 shown duplicates was fixed because it was shown. 8 commits credited the check for a fix, against 73 runs that showed a D. The same in the week before, with an earlier version: 14 fixes credited against 54 runs with a D.
- **Stopping the commit**, A, 16-22 Nov, 584 runs, labelled by hand: about 41-73% of the real duplicates shown were fixed, as intended (one copy cut to a link). 283 stops on 214 commits (68% of the commits checked), at most 4 stops on one commit, a median of 8 s from the first stop to the commit going through. No `--no-verify` or other bypass; every `DUP_OK` given before a stop was itself stopped. 472 shown lines were passed with `DUP_OK`; of 40 sampled, 1-4 were duplicates. Of the passed lines, 26% were own-file hits and 7% came from transcripts and records of sent text, which repeat on purpose (since left out).
- 6 commits on one day went through unchecked and unlogged when the check hit its 6 s limit; the limit now logs an error line.

## The floor (score 30)
The score is raw BM25: it grows with the words two sentences share and how rare those words are.
- What 134 commits of A would have shown (714 sentences, at most 5 lines per commit):

| rule | lines | D share | commits with a D / without / silent |
|---|---|---|---|
| no floor | 338 | 29% | 51 / 83 / 0 |
| floor 25 | 274 | 35% | 50 / 68 / 16 |
| **floor 30 (built)** | 217 | 43% | 48 / 49 / 37 |
| floor 35 | 176 | 48% | 46 / 41 / 47 |
| floor 40 | 144 | 53% | 40 / 32 / 62 |
| floor 50 | 87 | 64% | 29 / 16 / 89 |

- That floor was fitted on the same days it was scored on: the next week it showed 33% D, not 43%. By score band that week: 30-35, 10 D of 91 lines; 35-40, 8 of 64; 40-50, 39 of 83; 50-70, 40 of 94; 70 and up, 22 of 30. Under a score of 30, a hit is a D about 1 time in 20.
- The floor stays at 30 because agents fix a shown D about equally often in every band (one side rewritten within the hour: 2 of 18 at 30-40, 4 of 39 at 40-50, 4 of 40 at 50-70, 4 of 22 at 70 and up), and wrong lines around a D do not make them fix it less (a D shown alone: 3 of 28; among only Ds: 7 of 57; among other lines: 7 of 62). A floor of 40 would hide about 18 duplicates a week for shorter output.
- Under the stop, the share of shown hits gone at the same chat's next try (fixed or reworded) is flat up to 70: 14% at 30-40, 10% at 40-50, 15% at 50-70, 30% above. A floor of 40 would have spared 84 of the 283 stops and hidden 57 of the 110 hits that were gone. Own-file and other-file hits were gone about equally often (16% and 12%).
- Repo size: on random samples of A down to 300 sentences and on S, a floor of 30 keeps about the same D share (38-45%) at every size, and plain copies score 33-60. On a very small repo it misses about a quarter of the duplicates that a floor scaled down with the repo would show, but that lower floor shows two to four times the noise. A repo of a few dozen sentences shows almost nothing.

## The same file
Until 17 Nov a line was compared only with other files. Replayed: 353 commits of A, 672 of B; 1,161 same-file hits scoring 30 or more, labelled.
- Which lines of its own file a sentence skips hardly changes the D share (21-28% under each of: only the line, 3 lines around it, its paragraph, its section). Built: its paragraph in markdown, its record in a `.tyaml`. Skipping only the line itself would add 112 lines with 7 D in A, and 276 lines with 70 D in B.
- Same-file hits scoring 30-40 are D 20% of the time (other files: 12%). A same-file floor of 40 would hide 41% of the same-file duplicates.
- Cost: a same-file hit at 30 or more comes up in 42% of commits in A (with a D in 11%) and 24% in B (with a D in 8%). Most of the noise is parallel entries of one list: run logs, form letters, templates, usage lines.
- Fields that only say where a fact comes from: with them compared, records citing the same source scored alike; left out (`source`, `see` here), those pairs score under 15.
- Each sentence gets two slots, its best other-file line and its best own-file line, sharing the cap of 5; in one ranking an own-file line would push out the other-file hit. The cap was full in 8% of runs (31 of 407).

## BM25, not embeddings
On the 714 sentences agents committed to A in 134 commits, every line in the top 3 of each retriever was labelled: 7,113 pairs, 364 D. Sentences with a D at rank 1 and in the top 3, of 190 with a D in any retriever's top 3:

| retriever | D at rank 1 | D in top 3 | only it finds one (top 3, vs BM25) | only BM25 does |
|---|---|---|---|---|
| BM25 | 142 | 170 | - | - |
| bge-small-en-v1.5 (33M) | 108 | 139 | 7 | 38 |
| BM25 + bge-small, reciprocal rank fusion | 135 | 165 | 10 | 15 |
| Qwen3-Embedding-0.6B, symmetric | 113 | 137 | 8 | 41 |
| Qwen3-Embedding-0.6B, asymmetric | 114 | 142 | 15 | 43 |

- Copies written by agents share rare tokens (names, amounts, dates, ids, paths), where embedding models are weakest. Published: 13 embedding models told sentences apart by their numbers with 0.54 accuracy, 0.5 being chance ([EmbedNum-1K](https://arxiv.org/abs/2509.05691)); on LIMIT, BM25 reaches recall@100 of 93.6 where the best single-vector model reaches 18.9 ([arXiv 2508.21038](https://arxiv.org/abs/2508.21038)).
- As a noise filter an embedding added nothing: sorting BM25's top hits by a fit of BM25 score and cosine puts 99 D in the best 217; by BM25 score alone, 100.
- Tokenizer changes added nothing: D at rank 1 with the plain tokenizer 143, thousands separators normalised 143, a suffix stemmer 140, stemmer and bigrams 146.
- Cross-encoder rerankers made it worse: re-sorting the top 30 of the BM25 + bge-small fusion on 32 pairs mined from real dedupe commits took recall@3 from 0.81 to 0.66 (ms-marco-MiniLM-L-6-v2) and 0.59 (bge-reranker-base). They favour on-topic passages over the line that repeats the number.
- On the same 32 pairs, recall@3 by line: BM25 0.72, bge-small 0.53, bge-large 0.50, bge-m3 0.59.
- Cost: a dense model costs 7-9 s cold (the `torch` import), so it needs a resident server and about 1 GB of RAM; in A it once stopped silently for a day and a half after a disk cleanup deleted the model cache.
- What BM25 cannot find: a copy reworded with no rare word in common. A logged no such miss: its fails log had 55 entries by 23 Nov, all about shown hits (168 hits, 22 real).

## Speed
- A, about 47k sentences: 1.1-1.4 s per commit with something to search (median 1.35 s over 400 replayed commits, at most 2.6 s); 0.06 s when the commit has nothing to search.
- C: median 0.11 s, at most 0.33 s, over 317 replayed commits. S: 0.06 s.

## New in this repo, measured by replay
Each commit was replayed at its own tree in a throwaway clone: A's last 400 commits that touched markdown, and all such commits of C (317) and S (34), root commits aside. These count what the check would show, not what agents would do with it.

**Noise of the duplicate check on a code repo (C).** C's last 20 commits that touched markdown: 12 of the 20 would show hits, 32 lines in all: 9 D, 9 R, 14 N (labelled by one agent reading them). A real duplicate came up in 6 of the 20 commits, so an agent would have been stopped in 12 commits, 6 of them for nothing real. The noise is mostly parallel entries of one list and a backlog item next to the spec it refers to.

**Old values (shown, never stops).** First version: any short replaced span (up to 4 words) whose old words a line in another file still holds, without the new ones. On A's 400 commits that gave 140 candidates from 208 replaced sentences in 117 commits; of the 52 scoring 30 or more, read by hand, none was a stale copy. Most were a copy cut to a link whose canonical copy stays on purpose, a reworded sentence, or a review log quoting the old line. Built: only a number changed in place, with 3 or more changed digits, from a score of 20 (README > "What it checks"). Over all three replays (751 commits) it shows 5 lines: 4 in A, 1 in C, none in S. One is a real stale copy (a card number another file still gave, fixed a few commits later); four are records that name the old value on purpose (a log of what a mail said, a "the old account was ..." note, a review, a note about a former host). That is not mostly real, and no floor makes it so on this data, so it never stops a commit.

**Broken links.** Built rules as in "What it checks" in the README. Reports, and how many were real (read by hand):

| repo | commits | markdown lines added or edited | reports | commits with a report | real |
|---|---|---|---|---|---|
| A | 400 | 1,469 | 16 | 4 | 0 |
| C | 317 | 7,466 | 6 | 4 | 2 |
| S | 34 | 457 | 0 | 0 | 0 |

- All 16 in A come from commits that moved or renamed files: history records (review logs, a dated log line) naming the old path. 15 of them are in folders A leaves out of its duplicate check; with those left out, A has 1 report in 400 commits.
- C's 2 real ones: an instruction to follow a guide that the same commit deleted, and a README link to a licence file that does not exist. The 4 false ones: notes that name the files their own commit had just removed.
- So about 1 commit in 100 gets a link report, and most false reports are history that names a removed file; leave such records out with `-dup-check` in `.gitattributes`.
- Rules dropped while building it, because their reports were nearly all false: every backticked name with a file extension (on S alone, 70 reports in 34 commits, none real: gitignored local files, file names of other repos), headings matched only by their full text (most references in A name a heading by its first words, or a `**bold label**`), and backticked paths whose first folder the repo lacks (in C: shorthand relative to a component's source folder, files of dependencies).

## Not tested
- **The stop under Codex.** Codex outside Zucchini sets neither `CLAUDECODE` nor `ZUCCHINI_CHAT_ID`, so it only sees the hits unless `DUP_CHECK_AGENT` is set. In A's stop week no Codex chat committed a note file; the stop of a Codex commit was tried only in a worktree. `DUP_CHECK_AGENT` has been tried only in this repo's tests.
- **Other agents** (Cursor, Gemini CLI, Aider and others): not tried.
- **Agents acting on the new checks.** The link and old-value numbers above count reports in replays; whether agents fix them, and how often they pass them with `DUP_OK`, is unmeasured.
- **One repo, one owner.** The fix rates and the floor come from A: one person's notes, mostly English, written by Claude models.
- **The pre-commit framework install** (`.pre-commit-hooks.yaml`): not run end to end; the tool was not installed on the machine this was built on. The `core.hooksPath` install is what the tests and the measurements above use.
- **Windows:** not run. The 6 s limit uses `SIGALRM`, which Windows lacks, so there the check runs without a limit.
