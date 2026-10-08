import os, shutil, subprocess, tempfile, unittest
from pathlib import Path
from unittest import mock

from app import analyzer, db, pipeline


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   cwd=cwd, check=True, capture_output=True)


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        p = mock.patch.object(db, "DB_PATH", str(self.tmp / "t.db"))
        p.start(); self.addCleanup(p.stop)
        db.init()


class Validation(unittest.TestCase):
    def test_accepts_github_urls(self):
        for u in ["https://github.com/a/b", "https://github.com/a/b/", "https://github.com/a/b.git", " https://github.com/a/b "]:
            self.assertEqual(analyzer.validate_url(u), "https://github.com/a/b.git")

    def test_rejects_everything_else(self):
        for u in ["http://github.com/a/b", "https://gitlab.com/a/b", "https://github.com/a",
                  "https://github.com/a/b/tree/main", "file:///etc/passwd", "--upload-pack=x",
                  "https://github.com/a/b; rm -rf /"]:
            with self.assertRaises(ValueError, msg=u):
                analyzer.validate_url(u)


class Scoring(unittest.TestCase):
    base = dict(nloc=300, max_ccn=15, long_functions=0, todos=0, commits=0)

    def test_bounds(self):
        small = dict(nloc=10, max_ccn=1, long_functions=0, todos=0, commits=0)
        huge = dict(nloc=2000, max_ccn=60, long_functions=9, todos=20, commits=50)
        self.assertLess(analyzer.score_file(small), 10)
        self.assertEqual(analyzer.score_file(huge), 100)

    def test_hotspot_raises_score(self):
        self.assertGreater(analyzer.score_file({**self.base, "commits": 20}), analyzer.score_file(self.base))

    def test_empty_repo(self):
        r = analyzer.build_result([])
        self.assertEqual((r["repo_score"], r["totals"]["files"], r["totals"]["nloc"]), (0.0, 0, 0))

    def test_repo_score_is_weighted_by_size(self):
        r = analyzer.build_result([{"score": 100, "nloc": 900, "todos": 0, "commits": 0},
                                   {"score": 0, "nloc": 100, "todos": 0, "commits": 0}])
        self.assertEqual(r["repo_score"], 90.0)


class Analysis(TempDirCase):
    def test_skips_symlinks_ignored_dirs_and_other_extensions(self):
        outside = self.tmp / "secret.py"; outside.write_text("x = 1\n")
        repo = self.tmp / "repo"; (repo / "node_modules").mkdir(parents=True)
        (repo / "a.py").write_text("def f(x):\n    # TODO: simplify\n    # FIXME: wrong\n    return x\n")
        (repo / "node_modules" / "x.js").write_text("var a = 1;\n")
        (repo / "README.md").write_text("# hi\n")
        (repo / "link.py").symlink_to(outside)
        (repo / "broken.py").symlink_to(self.tmp / "missing.py")  # no debe romper el análisis
        files = analyzer.analyze_dir(repo)
        self.assertEqual([f["path"] for f in files], ["a.py"])
        self.assertEqual(files[0]["todos"], 2)

    def test_commit_counts(self):
        repo = self.tmp / "r"; repo.mkdir()
        git(repo, "init", "-q")
        for i in range(2):
            (repo / "a.py").write_text(f"x = {i}\n")
            git(repo, "add", "."); git(repo, "commit", "-qm", f"c{i}")
        self.assertEqual(analyzer.commit_counts(repo)["a.py"], 2)

    def test_commit_counts_outside_git_repo(self):
        self.assertEqual(len(analyzer.commit_counts(self.tmp)), 0)

    @unittest.skipUnless(__import__("tests").HAS_LIZARD, "requiere lizard real")
    def test_complexity_is_measured(self):
        repo = self.tmp / "c"; repo.mkdir()
        body = "def f(x):\n" + "".join(f"    if x == {i}:\n        return {i}\n" for i in range(12)) + "    return -1\n"
        (repo / "c.py").write_text(body)
        self.assertGreaterEqual(analyzer.analyze_dir(repo)[0]["max_ccn"], 13)


class Pipeline(TempDirCase):
    def _fake_clone(self, src):
        return lambda url, dest: shutil.copytree(src, dest, dirs_exist_ok=True)

    def test_full_run_without_ai(self):
        src = self.tmp / "src"; src.mkdir()
        (src / "a.py").write_text("def f():\n    return 1\n")
        aid = db.create("https://github.com/a/b.git")
        with mock.patch.dict(os.environ, {}, clear=False), mock.patch.object(analyzer, "clone", self._fake_clone(src)):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            pipeline.run(aid, "https://github.com/a/b.git")
        row = db.get(aid)
        self.assertEqual(row["status"], "done")
        self.assertEqual(len(row["result"]["files"]), 1)
        self.assertNotIn("ai", row["result"]["files"][0])

    def test_failure_is_recorded(self):
        aid = db.create("https://github.com/a/b.git")
        with mock.patch.object(analyzer, "clone", side_effect=RuntimeError("boom")):
            pipeline.run(aid, "https://github.com/a/b.git")
        row = db.get(aid)
        self.assertEqual((row["status"], row["error"]), ("error", "boom"))

    def test_ai_failure_does_not_break_analysis(self):
        src = self.tmp / "src"; src.mkdir()
        (src / "a.py").write_text("def f():\n    return 1\n")
        aid = db.create("https://github.com/a/b.git")
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "x"}), \
             mock.patch.object(analyzer, "clone", self._fake_clone(src)), \
             mock.patch.object(pipeline.ai, "review_file", return_value={"error": "x"}):
            pipeline.run(aid, "https://github.com/a/b.git")
        self.assertEqual(db.get(aid)["status"], "done")


class Db(TempDirCase):
    def test_fail_stale_only_touches_unfinished(self):
        a, b, c = (db.create("u") for _ in range(3))
        db.update(b, status="done"); db.update(c, status="analyzing")
        db.fail_stale()
        self.assertEqual([db.get(x)["status"] for x in (a, b, c)], ["error", "done", "error"])

    def test_get_unknown_returns_none(self):
        self.assertIsNone(db.get("nope"))


if __name__ == "__main__":
    unittest.main()
