import json
import tempfile
import unittest
from pathlib import Path

from helpers import done

from sbx_detect import main as sbx_detect_main
from sbxlib.adapters import project_scan


def no_tools(argv, stdin=None, timeout=60):
    return done(127)


class DetectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, name, text=""):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def detect(self, run=no_tools):
        return project_scan.detect(self.root, run=run)

    def test_python_uv_pytest_postgres_playwright(self):
        self.write("pyproject.toml", '[project]\ndependencies=["sqlalchemy","psycopg"]\n[dependency-groups]\ntest=["pytest","pytest-xdist","testcontainers[postgres]","playwright"]\n')
        self.write("uv.lock", "")
        self.write(".github/workflows/ci.yml", "on: push\n")
        found = self.detect()
        self.assertEqual(found["language"], ["python"])
        self.assertEqual(found["build_tool"], ["uv"])
        self.assertEqual(found["test_runner"], ["pytest"])
        self.assertTrue(found["parallel_runner"])
        self.assertTrue(found["testcontainers"])
        self.assertEqual(found["browser"], ["playwright"])
        self.assertEqual(found["ci"], ["github-actions"])

    def test_java_maven_spring(self):
        self.write("pom.xml", "<project><artifactId>spring-boot-starter-web</artifactId><artifactId>testcontainers</artifactId><artifactId>postgresql</artifactId><artifactId>spring-boot-starter-data-redis</artifactId></project>")
        self.write("mvnw", "")
        self.write("src/test/java/AThing.java", "")
        found = self.detect()
        self.assertEqual(found["language"], ["java"])
        self.assertEqual(found["build_tool"], ["maven"])
        self.assertEqual(found["test_runner"], ["maven-surefire"])
        self.assertTrue(found["testcontainers"])

    def test_empty_project_reports_nothing_and_keeps_every_key(self):
        found = self.detect()
        self.assertEqual(found["language"], [])
        self.assertEqual(found["repo_visibility"], "unknown")

    def test_secret_files_are_named_never_read(self):
        self.write(".env", "TOKEN=do-not-read-this")
        found = self.detect()
        self.assertEqual(found["secret_files"], [".env"])
        self.assertNotIn("do-not-read-this", json.dumps(found))

    def test_public_github_remote(self):
        def run(argv, stdin=None, timeout=60):
            if argv[:2] == ["git", "remote"]:
                return done(0, "https://github.com/acme/app.git\n")
            if argv[0] == "gh":
                return done(0, "PUBLIC\n")
            return done(127)

        found = self.detect(run)
        self.assertEqual(found["repo_visibility"], "public")
        self.assertEqual(found["remote"], "https://github.com/acme/app.git")

    def test_token_in_remote_url_is_stripped(self):
        def run(argv, stdin=None, timeout=60):
            if argv[:2] == ["git", "remote"]:
                return done(0, "https://x:s3cret@github.com/acme/app.git\n")
            return done(127)

        found = self.detect(run)
        self.assertNotIn("s3cret", json.dumps(found))
        self.assertEqual(found["remote"], "https://github.com/acme/app.git")

    def test_no_shape_of_credential_survives_in_a_remote(self):
        for url in ("ssh://u:tok@host/x/y", "HTTPS://tok@github.com/acme/app", "https://a@tok@github.com/acme/app", "git+ssh://u:tok@host/x"):
            def run(argv, stdin=None, timeout=60, value=url):
                return done(0, value + "\n") if argv[:2] == ["git", "remote"] else done(127)

            with self.subTest(url):
                self.assertNotIn("tok", self.detect(run)["remote"])

    def test_an_ordinary_ssh_user_stays(self):
        def run(argv, stdin=None, timeout=60):
            return done(0, "ssh://git@github.com/acme/app.git\n") if argv[:2] == ["git", "remote"] else done(127)

        self.assertEqual(self.detect(run)["remote"], "ssh://git@github.com/acme/app.git")

    def test_private_ssh_remote(self):
        def run(argv, stdin=None, timeout=60):
            if argv[:2] == ["git", "remote"]:
                return done(0, "git@github.com:acme/app.git\n")
            if argv[0] == "gh":
                self.assertIn("acme/app", argv)
                return done(0, "PRIVATE\n")
            return done(127)

        self.assertEqual(self.detect(run)["repo_visibility"], "private")

    def test_cli_prints_json(self):
        self.write("package.json", '{"devDependencies":{"vitest":"1","cypress":"1"}}')
        import contextlib
        import io

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(sbx_detect_main([str(self.root)]), 0)
        found = json.loads(out.getvalue())
        self.assertEqual(found["language"], ["javascript"])
        self.assertEqual(found["browser"], ["cypress"])


if __name__ == "__main__":
    unittest.main()
