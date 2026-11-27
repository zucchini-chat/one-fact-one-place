"""End-to-end tests: real commits in throwaway repos with the hooks installed. Run: python3 -m unittest discover tests"""
import json, os, random, re, shutil, subprocess, sys, tempfile, unittest

HOOKS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks")
GIT = shutil.which("git")
STOPPED, UNSEEN, SEEN = "Commit stopped by the pre-commit check: the lines", "DUP_OK passes only", "Possible problems in"
AGENT = dict(CLAUDECODE="1", CLAUDE_CODE_SESSION_ID="chat-a")
try:
    import yaml
except ImportError:
    yaml = None

# made-up facts; each shares no rare word with the others
F1 = "The staging database is backed up every night at 02:30 UTC to the bucket quarry-backups-eu."
F2 = "Release builds are signed with the key held by Ottilie Brandvik and expire after 397 days."
F3 = "The billing worker retries a failed Stripe webhook five times with a backoff capped at 640 seconds."
F4 = "Feature flags live in the Lunetra admin panel under the project slug harrow-web."
F5 = "Support answers tickets tagged urgent within 4 business hours, weekends excluded."
F6 = "The nightly export job writes Parquet files to the warehouse share at /mnt/fjord/exports."


def filler():
    """300 lines of nonsense words, so that the words of the facts above are rare and score like in a real repo."""
    rnd = random.Random(7)
    vocab = ["".join(rnd.choice("bcdfghklmnprstvz") + rnd.choice("aeiou") for _ in range(3)) for _ in range(1500)]
    return "# Notes\n\n" + "\n\n".join(" ".join(rnd.choice(vocab) for _ in range(12)).capitalize() + "." for _ in range(300)) + "\n"


FILLER = filler()


class Repo:
    def __init__(self, test, hooks_inside=False):
        self.tmp = tempfile.mkdtemp(prefix="ofop-")
        test.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.dir = os.path.join(self.tmp, "repo")
        os.makedirs(self.dir)
        self.hooks = os.path.join(self.dir, "tools/hooks") if hooks_inside else os.path.join(self.tmp, "hooks")
        shutil.copytree(HOOKS, self.hooks, ignore=shutil.ignore_patterns("__pycache__"))
        for args in (("init", "-q", "-b", "main"), ("config", "user.email", "test@example.com"),
                     ("config", "user.name", "Test"), ("config", "commit.gpgsign", "false"),
                     ("config", "core.hooksPath", "tools/hooks" if hooks_inside else self.hooks)):
            self.git(*args)
        self.write("filler.md", FILLER)
        self.write("facts.md", f"# Facts\n\n{F1}\n\n{F2}\n\n{F3}\n")
        self.git("add", "-A")
        assert self.commit().returncode == 0

    def env(self, **kw):
        e = {"PATH": os.environ["PATH"], "HOME": self.tmp, "GIT_CONFIG_NOSYSTEM": "1"}
        e.update(kw)
        return e

    def git(self, *args, **kw):
        return subprocess.run([GIT, *args], cwd=self.dir, capture_output=True, text=True, env=self.env(**kw))

    def write(self, path, text, append=False):
        p = os.path.join(self.dir, path)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a" if append else "w", encoding="utf-8") as f:
            f.write(text)

    def read(self, path):
        with open(os.path.join(self.dir, path), encoding="utf-8") as f:
            return f.read()

    def commit(self, *paths, **kw):
        """Commit these paths (git add first), or the index when none are given."""
        for p in paths:
            self.git("add", "--", p)
        r = self.git("commit", "-q", "-m", "test", *(["--", *paths] if paths else []), **kw)
        r.out = r.stdout + r.stderr
        return r

    def log(self):
        p = os.path.join(self.dir, ".git/dup-check/runs.jsonl")
        if not os.path.exists(p):
            return []
        with open(p, encoding="utf-8") as f:
            return [json.loads(l) for l in f]

    def py(self, script, *args, **kw):
        r = subprocess.run([sys.executable, os.path.join(self.hooks, script), *args], cwd=self.dir, capture_output=True,
                           text=True, env=self.env(**kw))
        r.out = r.stdout + r.stderr
        return r


class Duplicates(unittest.TestCase):
    def setUp(self):
        self.r = Repo(self)

    def test_agent_stopped_then_passes_with_reason(self):
        r = self.r
        r.write("notes.md", F2 + "\n")
        c = r.commit("notes.md", **AGENT)
        self.assertNotEqual(c.returncode, 0)
        self.assertIn(STOPPED, c.out)
        self.assertRegex(c.out, r"(?m)^1\. notes\.md: Release builds.*\n   -> facts\.md:5 Release builds")
        self.assertIn("Never --no-verify", c.out)
        L = r.log()[-1]
        self.assertTrue(L["stopped"])
        self.assertEqual((L["agent"], L["chat"]), ("CLAUDECODE", "chat-a"))
        c = r.commit("notes.md", DUP_OK="kept on purpose", **AGENT)
        self.assertEqual(c.returncode, 0, c.out)
        self.assertEqual(c.out.strip(), "")
        self.assertEqual(r.log()[-1]["ok"], "kept on purpose")

    def test_reason_without_a_stop_is_stopped(self):
        r = self.r
        r.write("notes.md", F2 + "\n")
        c = r.commit("notes.md", DUP_OK="blind", **AGENT)
        self.assertNotEqual(c.returncode, 0)
        self.assertIn(UNSEEN, c.out)

    def test_a_stop_counts_only_for_its_own_chat(self):
        r = self.r
        r.write("notes.md", F3 + "\n")
        c = r.commit("notes.md", ZUCCHINI_CHAT_ID="z-a")
        self.assertNotEqual(c.returncode, 0)
        self.assertEqual(r.log()[-1]["agent"], "ZUCCHINI_CHAT_ID")
        self.assertNotEqual(r.commit("notes.md", ZUCCHINI_CHAT_ID="z-b", DUP_OK="b").returncode, 0)
        self.assertEqual(r.commit("notes.md", ZUCCHINI_CHAT_ID="z-a", DUP_OK="a").returncode, 0)

    def test_dup_check_agent_variable(self):
        r = self.r
        r.write("notes.md", F1 + "\n")
        c = r.commit("notes.md", DUP_CHECK_AGENT="1")
        self.assertNotEqual(c.returncode, 0)
        self.assertEqual(r.log()[-1]["agent"], "DUP_CHECK_AGENT")

    def test_more_hits_than_shown(self):
        r = self.r
        names = ["Quobrin", "Plimmet", "Draxwell", "Mozzarek", "Yarrowind", "Velkasso", "Snarbeck"]
        lines = [f"The service account for {x} Hezzlam rotates its token every {11 + 7 * i} days via vault path kv/{x.lower()}."
                 for i, x in enumerate(names)]
        r.write("src.md", "\n\n".join(lines) + "\n")
        r.commit("src.md")
        r.write("copy.md", "\n\n".join(lines) + "\n")
        c1 = r.commit("copy.md", **AGENT)
        c2 = r.commit("copy.md", DUP_OK="all on purpose", **AGENT)
        c3 = r.commit("copy.md", DUP_OK="all on purpose", **AGENT)
        count = lambda c: len(re.findall(r"(?m)^\d+\. copy\.md: ", c.out))
        self.assertEqual(count(c1), 5)
        self.assertGreaterEqual(count(c2), 2)
        self.assertIn(UNSEEN, c2.out)
        self.assertEqual(c3.returncode, 0, c3.out)

    def test_person_only_sees_hits(self):
        r = self.r
        r.write("notes.md", F1 + "\n")
        c = r.commit("notes.md")
        self.assertEqual(c.returncode, 0)
        self.assertIn(SEEN, c.out)
        self.assertIn("-> facts.md:3", c.out)
        self.assertIsNone(r.log()[-1]["agent"])
        r.write("notes2.md", F3 + "\n")
        c = r.commit("notes2.md", DUP_OK="person")
        self.assertEqual(c.returncode, 0)
        self.assertIn(SEEN, c.out)

    def test_same_file_other_paragraph_and_same_paragraph(self):
        r = self.r
        r.write("facts.md", f"\n{F1[:-1]}, kept for 30 days.\n", append=True)
        c = r.commit("facts.md", **AGENT)
        self.assertRegex(c.out, r"(?m)^1\. facts\.md: The staging.*\n   -> facts\.md:3 ")
        r.git("checkout", "HEAD", "--", "facts.md")
        r.write("facts.md", r.read("facts.md").replace(F1 + "\n", F1 + "\n" + F1[:-1] + ", kept for 30 days.\n"))
        c = r.commit("facts.md", **AGENT)
        self.assertEqual(c.returncode, 0, c.out)

    def test_commit_by_path_checks_only_its_paths(self):
        r = self.r
        r.write("staged.md", F2 + "\n")
        r.git("add", "staged.md")
        r.write("clean.md", F6 + "\n")
        c = r.commit("clean.md", **AGENT)
        self.assertEqual(c.returncode, 0, c.out)
        self.assertEqual({q["file"] for q in r.log()[-1]["queries"]}, {"clean.md"})

    def test_edits(self):
        r = self.r
        n = len(r.log())
        r.write("facts.md", r.read("facts.md").replace(" and expire after 397 days", ""))
        self.assertEqual(r.commit("facts.md", **AGENT).returncode, 0)
        self.assertEqual(len(r.log()), n, "a deletion-only edit searches nothing")
        r.write("facts.md", r.read("facts.md").replace(F3, F3 + " " + F5))
        r.commit("facts.md", **AGENT)
        self.assertEqual([q["text"] for q in r.log()[-1]["queries"]], [F5], "an edit searches only its new sentence")

    def test_symbol_edits_count_cosmetic_ones_do_not(self):
        r = self.r
        text = ("# Edits\n\nThe hosted runner costs $100 a month and is billed to the platform team budget.\n\n"
                "The **retry** budget for the mobile gateway is spent after the third timeout in a row.\n\n"
                "The “canary” stage holds each release of the payments API for two full hours.\n")
        r.write("edits.md", text)
        r.commit("edits.md")
        for a, b, searched in (("$100", "$-100", True), ("hosted", "Hosted", False), ("**retry**", "retry", False),
                               ("“canary”", "canary", False)):
            n = len(r.log())
            r.write("edits.md", text.replace(a, b))
            r.commit("edits.md", **AGENT)
            self.assertEqual(len(r.log()) - n, int(searched), f"{a} -> {b}")
            r.write("edits.md", text)
            r.commit("edits.md")

    def test_odd_file_names(self):
        r = self.r
        for name in ("my notes.md", 'quo"te.md'):
            r.write(name, F2 + "\n")
            c = r.commit(name, **AGENT)
            self.assertIn(f"1. {name}: ", c.out)
            self.assertEqual(r.log()[-1]["queries"][0]["file"], name)

    def test_replay_prints_and_logs_nothing(self):
        r = self.r
        r.write("notes.md", F2 + "\n")
        r.commit("notes.md", DUP_CHECK_AGENT="1")
        r.commit("notes.md", DUP_CHECK_AGENT="1", DUP_OK="on purpose")
        n = len(r.log())
        c = r.py("dupcheck_hook.py", "HEAD", **AGENT)
        self.assertEqual(c.returncode, 0)
        self.assertIn("-> facts.md:5", c.out)
        self.assertEqual(len(r.log()), n)

    def test_log_lives_in_git_dir(self):
        r = self.r
        r.write("notes.md", F2 + "\n")
        r.commit("notes.md")
        self.assertTrue(r.log())
        self.assertEqual(r.git("status", "--porcelain").stdout, "")

    def test_hooks_inside_the_repo(self):
        r = Repo(self, hooks_inside=True)
        r.write("notes.md", F2 + "\n")
        c = r.commit("notes.md", **AGENT)
        self.assertNotEqual(c.returncode, 0)
        self.assertIn("python3 tools/hooks/dupcheck_search.py", c.out)


class Excludes(unittest.TestCase):
    def test_changelog_and_gitattributes(self):
        r = Repo(self)
        r.write("CHANGELOG.md", f"# Changelog\n\n{F4}\n")
        r.write("archive/old.md", f"{F5}\n")
        r.write(".gitattributes", "archive/** -dup-check\n")
        r.commit("CHANGELOG.md", "archive/old.md", ".gitattributes")
        r.write("notes.md", F4 + "\n\n" + F5 + "\n")
        self.assertEqual(r.commit("notes.md", **AGENT).returncode, 0, "excluded files are not hits")
        r.write("CHANGELOG.md", F1 + "\n", append=True)
        n = len(r.log())
        self.assertEqual(r.commit("CHANGELOG.md", **AGENT).returncode, 0)
        self.assertEqual(len(r.log()), n, "excluded files are not searched")
        r.write(".gitattributes", "CHANGELOG.md dup-check\n", append=True)
        r.commit(".gitattributes")
        r.write("more.md", F4 + "\n")
        c = r.commit("more.md", **AGENT)
        self.assertIn("-> CHANGELOG.md:3", c.out, "dup-check set brings a default-excluded file back")


class LineFiles(unittest.TestCase):
    """Files with dup-check set that are not .md or .tyaml: each line is its own record."""
    def setUp(self):
        r = self.r = Repo(self)
        r.write(".gitattributes", "data/*.csv dup-check\n")
        r.write("data/vendors.csv", f"name,notes\nexport,{F6}\n")
        r.write("other/vendors.csv", f"name,notes\nsupport,{F5}\n")
        r.commit(".gitattributes", "data/vendors.csv", "other/vendors.csv")

    def test_opted_in_lines_are_searched_and_hit(self):
        r = self.r
        r.write("notes.md", F5 + "\n\n" + F6 + "\n")
        c = r.commit("notes.md", **AGENT)
        self.assertRegex(c.out, r"(?m)^1\. notes\.md: The nightly.*\n   -> data/vendors\.csv:2 export,The nightly")
        self.assertNotIn("other/vendors.csv", c.out, "a file without the attribute is not read")
        r.write("data/vendors.csv", f"flags,{F4}\nflags-copy,{F4}\n", append=True)
        c = r.commit("data/vendors.csv", **AGENT)
        self.assertRegex(c.out, r"(?m)^1\. data/vendors\.csv: flags.*\n   -> data/vendors\.csv:\d flags", "the next line is another record")

    def test_no_link_check(self):
        r = self.r
        r.write("data/vendors.csv", "runbook,see [the runbook](missing.md) and `data/missing.csv` for the 42 steps\n", append=True)
        c = r.commit("data/vendors.csv", **AGENT)
        self.assertEqual(c.returncode, 0, c.out)

    def test_search_a_line(self):
        r = self.r
        r.write("notes.md", F6 + "\n")
        r.commit("notes.md")
        self.assertTrue(r.py("dupcheck_search.py", "data/vendors.csv:2").out.startswith("notes.md:1 "))
        self.assertEqual(r.py("dupcheck_search.py", "data/vendors.csv:9").out.strip(), "data/vendors.csv has no line 9")


class Failures(unittest.TestCase):
    def patch(self, r, old, new):
        p = os.path.join(r.hooks, "dupcheck.py")
        with open(p) as f:
            s = f.read()
        with open(p, "w") as f:
            f.write(s.replace(old, new))

    def test_timeout_and_crash_let_the_commit_through(self):
        r = Repo(self)
        hook = os.path.join(r.hooks, "dupcheck_hook.py")
        with open(hook) as f:
            s = f.read()
        with open(hook, "w") as f:
            f.write(s.replace("LIMIT = 40, 5, 4, 6", "LIMIT = 40, 5, 4, 1"))
        for name, patch, want in (("timeout", "import time; time.sleep(3)", "timeout"),
                                  ("crash", "raise ValueError('boom')", "ValueError('boom')")):
            self.patch(r, "    sents, postings, blocks = index()\n", f"    {patch}\n    sents, postings, blocks = index()\n")
            r.write(f"{name}.md", F2 + "\n")
            c = r.commit(f"{name}.md", **AGENT)
            self.assertEqual(c.returncode, 0, c.out)
            self.assertIn("pre-commit check skipped", c.out)
            self.assertEqual(r.log()[-1].get("error"), want)
            self.patch(r, f"    {patch}\n", "")

    def test_git_failure_is_logged_not_empty(self):
        """git puts its exec path first on a hook's PATH, so the failing git goes there (GIT_EXEC_PATH)."""
        r = Repo(self)
        real = subprocess.run([GIT, "--exec-path"], capture_output=True, text=True).stdout.strip()
        fake = os.path.join(r.tmp, "fakeexec")
        os.makedirs(fake)
        with open(os.path.join(fake, "git"), "w") as f:
            f.write(f'#!/bin/sh\nfor a in "$@"; do [ "$a" = ls-files ] && {{ echo "fatal: simulated" >&2; exit 128; }}; done\n'
                    f'GIT_EXEC_PATH="{real}" exec "{real}/git" "$@"\n')
        os.chmod(os.path.join(fake, "git"), 0o755)
        r.write("notes.md", F2 + "\n")
        c = r.commit("notes.md", GIT_EXEC_PATH=fake, **AGENT)
        self.assertEqual(c.returncode, 0, c.out)
        self.assertIn("simulated", r.log()[-1].get("error", ""))


class TypedYaml(unittest.TestCase):
    BILLS = ("types:\n  bills:\n    name: str\n    notes: str?\n    see: str?\n---\nbills:\n"
             f"  - name: hosting\n    notes: {F6}\n    see: docs/vendors folder page twelve, clause on renewal and indexation\n"
             "  - name: domain\n    notes: Renewed through the registrar every March for 14 euros a year.\n")

    def test_units(self):
        sys.path.insert(0, HOOKS)
        from dupcheck import units
        u = units("x.tyaml", "types:\n  a:\n    see: str\n---\na:\n  - name: Jane Example\n    see:\n      - some long path words\n"
                             "    notes: plain value here\n  - {name: y, see: a/b c d, notes: plain value, here}\n")
        self.assertEqual([t for t, _ in u], ["types:", "  a:", "    see: str", "---", "", "Jane Example", "", "", "plain value here",
                                             "y, plain value, here", ""])
        self.assertEqual(len({b for _, b in u[5:9]}), 1)
        self.assertNotEqual(u[9][1], u[8][1])

    def test_record_hit_and_skipped_field(self):
        r = Repo(self)
        r.write("bills.tyaml", self.BILLS)
        r.commit("bills.tyaml")
        r.write("bills.tyaml", f"  - name: backups\n    notes: {F6}\n", append=True)
        c = r.commit("bills.tyaml", **AGENT)
        self.assertRegex(c.out, r"(?m)^1\. bills\.tyaml: The nightly.*\n   -> bills\.tyaml:9 ")
        r.git("checkout", "HEAD", "--", "bills.tyaml")
        r.write("bills.tyaml", "  - name: mail\n    notes: Mailgun plan billed monthly to the ops card.\n"
                               "    see: docs/vendors folder page twelve, clause on renewal and indexation\n", append=True)
        c = r.commit("bills.tyaml", **AGENT)
        self.assertEqual(c.returncode, 0, c.out)

    @unittest.skipIf(yaml is None, "PyYAML is not installed")
    def test_type_error_stops_any_commit(self):
        r = Repo(self)
        r.write("my bills.tyaml", self.BILLS + "  - name: tld\n    cost: 12\n")
        c = r.commit("my bills.tyaml")
        self.assertNotEqual(c.returncode, 0)
        self.assertIn("unknown field cost", c.out)
        r.write("my bills.tyaml", self.BILLS)
        self.assertEqual(r.commit("my bills.tyaml").returncode, 0)


class Search(unittest.TestCase):
    def test_cli(self):
        r = Repo(self)
        r.write("notes.md", F2 + "\n")
        r.commit("notes.md", DUP_OK="x")
        c = r.py("dupcheck_search.py", "facts.md:5")
        self.assertTrue(c.out.startswith("notes.md:1 "), c.out)
        self.assertNotIn("facts.md:5 ", c.out)
        c = r.py("dupcheck_search.py", "Ottilie Brandvik signing key", "-k", "2", "--history")
        self.assertRegex(c.out, r"(?m)^      \d{4}-\d\d-\d\d [0-9a-f]{8} test$")
        r.write("facts.md", "Ottilie Brandvik also holds the backup signing key.\n", append=True)
        c = r.py("dupcheck_search.py", "Ottilie Brandvik signing key", "--history")
        self.assertIn("not committed yet", c.out)
        msgs = [r.py("dupcheck_search.py", t).out.strip() for t in ("nope.md:1", "facts.md:999", "facts.md:2")]
        self.assertEqual(msgs, ["no such file: nope.md", "facts.md has no line 999", "nothing to search for: ''"])

    def test_own_line_past_the_end(self):
        r = Repo(self)
        out = subprocess.run([sys.executable, "-c", f"import sys; sys.path.insert(0, {HOOKS!r}); from dupcheck import search; "
                              f"print({{h[0] for h in search([{F1!r}], 20, at=[('facts.md', 999)])[0]}})"],
                             cwd=r.dir, capture_output=True, text=True).stdout
        self.assertNotIn("facts.md", out)


class StaleCopies(unittest.TestCase):
    def setUp(self):
        self.r = Repo(self)
        self.r.write("runbook.md", "# Runbook\n\nThe restore drill starts from the 02:30 UTC snapshot in quarry-backups-eu.\n")
        self.assertEqual(self.r.commit("runbook.md", DUP_CHECK_AGENT="1").returncode, 0)

    def test_old_value_left_elsewhere_is_shown_not_stopped(self):
        r = self.r
        r.write("facts.md", r.read("facts.md").replace("02:30 UTC", "04:45 UTC"))
        c = r.commit("facts.md", **AGENT)
        self.assertEqual(c.returncode, 0, c.out)
        self.assertIn(SEEN, c.out)
        self.assertIn("still holds the old value (02:30): -> runbook.md:3 The restore drill", c.out)
        self.assertEqual(r.log()[-1]["stale"][0]["hit"][0], "runbook.md")

    def test_a_duplicate_holding_the_old_value_stops(self):
        r = self.r
        r.write("copy.md", f"Restore drill: {F1}\n")
        r.commit("copy.md", DUP_CHECK_AGENT="1")
        r.commit("copy.md", DUP_CHECK_AGENT="1", DUP_OK="test setup")
        r.write("facts.md", r.read("facts.md").replace("02:30 UTC", "04:45 UTC"))
        c = r.commit("facts.md", **AGENT)
        self.assertNotEqual(c.returncode, 0)
        self.assertIn("still holds the old value (02:30): -> copy.md:1 Restore drill", c.out)

    def test_only_a_changed_number_is_searched(self):
        r = self.r
        r.write("facts.md", r.read("facts.md").replace("staging database", "staging cluster"))
        r.commit("facts.md", **AGENT)
        self.assertEqual(r.log()[-1]["stale"], [])

    def test_both_copies_updated(self):
        r = self.r
        for f in ("facts.md", "runbook.md"):
            r.write(f, r.read(f).replace("02:30 UTC", "04:45 UTC"))
        c = r.commit("facts.md", "runbook.md", **AGENT)
        self.assertNotIn("still holds the old value (", c.out)


class Links(unittest.TestCase):
    def setUp(self):
        r = self.r = Repo(self)
        r.write("docs/deploy.md", "# Deploy\n\n## Roll back (manual)\n\nRun the rollback job.\n\n## Smoke test\n\nOpen the health page.\n")
        r.write("docs/guide.md", "# Guide\n\nStart here.\n")
        r.write("config/app.json", "{}\n")
        r.write(".gitignore", "secrets.txt\ntmp/\n")
        r.commit("docs/deploy.md", "docs/guide.md", "config/app.json", ".gitignore")

    def broken(self, line, path="docs/new.md"):
        self.r.write(path, line + "\n")
        c = self.r.commit(path, **AGENT)
        self.r.git("rm", "-q", "--cached", "-f", "--", path)
        os.remove(os.path.join(self.r.dir, path))
        return re.findall(r"broken link: (.*) \(", c.out)

    def test_broken(self):
        cases = {
            "See [the guide](guide.md) and [setup](setup.md).": ["setup.md"],
            "Config: `config/app.yaml`, deploy steps `docs/deploy.md` > \"Roll forward\".": ["config/app.yaml", 'docs/deploy.md > "Roll forward"'],
            "Back out with [roll back](deploy.md#roll-back) or [smoke](deploy.md#smoke-test).": ["deploy.md#roll-back"],
            "Read `guide.md` > \"Start\" and `missing.md`, [m](missing.md).": ['guide.md > "Start"', "missing.md"],
        }
        for line, want in cases.items():
            self.assertEqual(sorted(self.broken(line)), sorted(want), line)

    def test_not_checked_or_fine(self):
        for line in ("See [guide](guide.md), [root](/docs/guide.md), [up](../facts.md), [web](https://example.com/x.md).",
                     "`docs/deploy.md` > \"Roll back\" > \"Smoke test\", [smoke](deploy.md#smoke-test), [here](#guide-notes).",
                     "Paths: `config/app.json`, `secrets.txt`, `tmp/run.log`, `~/notes/x.md`, `/etc/hosts.md`, `*.md`, `.tyaml`.",
                     "Placeholders: `<topic>/CLAUDE.md`, [x](<name>.md), `$HOME/a.md`, `src/{a,b}.md`; code: `Node.js`, `os.path`.",
                     "Examples: `[x](nowhere.md)` and `nowhere.md > \"Heading\"` inside code spans."):
            self.assertEqual(self.broken("# Guide notes\n\n" + line), [], line)
        self.r.write("docs/fenced.md", "# F\n\n```\nsee [x](nowhere.md) and `gone/file.md`\n```\n")
        self.assertEqual(self.r.commit("docs/fenced.md", **AGENT).returncode, 0)

    def test_rename_and_heading_removal_break_links_elsewhere(self):
        r = self.r
        r.write("docs/index.md", "# Index\n\nSee [the guide](guide.md) and `docs/deploy.md` > \"Smoke test\".\n")
        r.commit("docs/index.md")
        r.git("mv", "docs/guide.md", "docs/start.md")
        c = r.commit(**AGENT)
        self.assertIn("1. docs/index.md:3 broken link: guide.md (no such file)", c.out)
        r.write("docs/index.md", r.read("docs/index.md").replace("(guide.md)", "(start.md)"))
        r.git("add", "docs/index.md")
        self.assertEqual(r.commit(**AGENT).returncode, 0, "a rename with its links updated is clean")
        r.write("docs/deploy.md", r.read("docs/deploy.md").replace("## Smoke test", "## Checks"))
        c = r.commit("docs/deploy.md", **AGENT)
        self.assertIn('docs/index.md:3 broken link: docs/deploy.md > "Smoke test" (no such heading in docs/deploy.md)', c.out)
        c = r.commit("docs/deploy.md", DUP_OK="heading renamed, index fixed next", **AGENT)
        self.assertEqual(c.returncode, 0, c.out)

    def test_deleted_file_named_bare_and_excluded_history(self):
        r = self.r
        r.write("docs/index.md", "# Index\n\nStart with `guide.md`.\n")
        r.write("log/2026.md", "- moved [the guide](../docs/guide.md) here\n")
        r.write(".gitattributes", "log/** -dup-check\n")
        r.commit("docs/index.md", "log/2026.md", ".gitattributes")
        r.git("rm", "-q", "docs/guide.md")
        c = r.commit(**AGENT)
        self.assertEqual(re.findall(r"(?m)^\d+\. (\S+) broken link", c.out), ["docs/index.md:3"], c.out)


@unittest.skipIf(yaml is None, "PyYAML is not installed")
class Manifest(unittest.TestCase):
    def test_pre_commit_hooks_yaml(self):
        with open(os.path.join(os.path.dirname(HOOKS), ".pre-commit-hooks.yaml")) as f:
            hooks = {h["id"]: h for h in yaml.safe_load(f)}
        self.assertEqual(set(hooks), {"dup-check", "tyaml"})
        self.assertTrue(hooks["dup-check"]["verbose"] and hooks["dup-check"]["always_run"])
        self.assertFalse(hooks["dup-check"].get("additional_dependencies"))
        self.assertEqual(hooks["tyaml"]["additional_dependencies"], ["pyyaml"])


if __name__ == "__main__":
    unittest.main()
