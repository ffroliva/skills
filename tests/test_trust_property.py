"""Any input not proven trusted comes back untrusted. A fixed list of seeds, so a failure repeats; the runtime has no dependencies.

The oracle below is written from docs/reference/trust.md's numbered steps, not from the code. It is run on random facts,
on random answers from GitHub at every route, and on every error branch, and nothing may raise.
"""

from __future__ import annotations

import json
import random
import unittest
from dataclasses import dataclass
from typing import Any

from fakes import FakeGitHub
from helpers import SHA

from sbxlib.adapters.gh_cli import GhCli
from sbxlib.app.trust import PullRequestTrust
from sbxlib.domain.adoption import own_work_verdict
from sbxlib.domain.trust import PullFacts, Standing, TrustLevel, TrustRules, decide, repo_id
from sbxlib.ports import CommandTimeout, Done

SEEDS = (1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233, 377, 610, 987, 1597, 2584, 4181, 6765, 10946)
ROUNDS = 400
PROJECT = "acme/app"
PROTECTED = ("docs/sbx.md", "kit")
LOGINS = ("alice", "Alice", "bob", "mallory", "", "dependabot[bot]", "a b", "../x")
ROLES = ("admin", "maintain", "write", "triage", "read", "none", "", "ADMIN", "owner", "write ", "\x00", "root")
PATHS = ("src/a.py", "docs/sbx.md", "DOCS/SBX.MD", "docs", "kit/a", "kit", "./docs/sbx.md", "docs\\sbx.md", "a/docs/sbx.md", "None", "")
REPOS = (PROJECT, "ACME/App", "stranger/fork", "acme/app2", "", "acme", "https://github.com/acme/app.git", "github.com/acme/app", "x/y/z")
STATES = ("open", "closed", "OPEN", "", "None", "draft")
SHAS = (SHA, "b" * 40, "", SHA.upper(), SHA[:7])
JUNK: tuple[Any, ...] = (None, 0, 1, -1, True, "", "x", [], {}, [None], [[]], {"a": 1}, 3.5, [{"login": None}], "a" * 1000)


@dataclass(frozen=True)
class Case:
    rules: TrustRules
    facts: PullFacts
    sha: str
    protected: tuple[str, ...]


def expected(case: Case) -> bool:
    """docs/reference/trust.md, step by step, by a route that shares no code with `decide`."""
    rules, facts = case.rules, case.facts
    if not (rules.roles or rules.team or rules.logins) or not case.protected:
        return False
    if repo_id(rules.repo) in ("",) or repo_id(rules.repo) != repo_id(facts.base_repo):
        return False
    if repo_id(facts.head_repo) != repo_id(facts.base_repo):
        return False
    if facts.head_sha != case.sha or facts.state != "open":
        return False
    if facts.commit_count != len(facts.commit_authors) or facts.file_count != len(facts.files):
        return False
    if facts.commit_count > 100 or facts.file_count > 100:
        return False

    def clean(path: str) -> str:
        return path.replace("\\", "/").removeprefix("./").strip("/").lower()

    for path in (*facts.files, *facts.renamed_from):
        for guarded in case.protected:
            name, guard = clean(path), clean(guarded)
            if name == guard or (name + "/").startswith(guard + "/") or (guard + "/").startswith(name + "/"):
                return False

    def granted(login: str) -> bool:
        if login.lower() in {name.lower() for name in rules.logins}:
            return True
        standing = facts.standings.get(login, Standing())
        return standing.role in (rules.roles & {"admin", "maintain", "write"}) or bool(rules.team and rules.team in standing.teams)

    return granted(facts.author) and all(granted(name) for name in facts.commit_authors)


def some(rng: random.Random, pool: tuple[Any, ...], limit: int = 3) -> tuple[Any, ...]:
    return tuple(rng.choice(pool) for _ in range(rng.randint(0, limit)))


def random_case(rng: random.Random) -> Case:
    rules = TrustRules(frozenset(some(rng, ROLES)), rng.choice(("", "acme/core", "stranger/x")), frozenset(some(rng, LOGINS)), rng.choice((*(PROJECT,) * 9, *REPOS)))
    authors = some(rng, LOGINS)
    author = rng.choice(LOGINS)
    files = some(rng, PATHS)
    standings = {name: Standing(rng.choice(ROLES), frozenset(some(rng, ("acme/core", "other/team"), 2))) for name in {author, *authors}}
    base = rng.choice((*(PROJECT,) * 9, *REPOS))
    head = rng.choice((*(base,) * 9, *REPOS))  # most pull requests come from a branch: a fork on every case would never reach trusted
    facts = PullFacts(7, rng.choice((*(SHA,) * 9, *SHAS)), rng.choice((*("open",) * 9, *STATES)), author, rng.choice(("OWNER", "MEMBER", "NONE", "")), head, base,
                      len(authors) + rng.choice((0, 0, 0, 1, -1, 200)), authors, len(files) + rng.choice((0, 0, 0, 1, -1, 200)), files, standings,
                      some(rng, PATHS, 1))
    return Case(rules, facts, rng.choice((*(SHA,) * 9, *SHAS)), rng.choice((PROTECTED, ("docs/sbx.md",), ())))


class Decide(unittest.TestCase):
    def test_a_verdict_is_trusted_exactly_when_the_rules_prove_it(self) -> None:
        trusted = 0
        for seed in SEEDS:
            rng = random.Random(seed)
            for _ in range(ROUNDS):
                case = random_case(rng)
                verdict = decide(case.rules, case.facts, case.sha, case.protected)
                self.assertEqual(verdict.level is TrustLevel.TRUSTED, expected(case), (seed, case))
                trusted += verdict.level is TrustLevel.TRUSTED
        self.assertGreater(trusted, 0, "the generator never reached trusted: this test would prove nothing")

    def test_unknown_roles_never_grant(self) -> None:
        for seed in SEEDS:
            rng = random.Random(seed)
            role = "".join(rng.choice("abcdefghij") for _ in range(rng.randint(0, 8)))
            rules = TrustRules(frozenset({role}), repo=PROJECT)
            facts = PullFacts(7, SHA, "open", "alice", "OWNER", PROJECT, PROJECT, 1, ("alice",), 1, ("a",), {"alice": Standing(role)})
            self.assertIs(decide(rules, facts, SHA, PROTECTED).level, TrustLevel.UNTRUSTED, role)


class OwnWork(unittest.TestCase):
    def test_only_the_exact_word_in_the_exact_repository_is_trusted(self) -> None:
        values = ("trusted", "Trusted", "TRUSTED", "true", "yes", "1", "", " trusted", "untrusted", "trusted?", "unknown")
        for seed in SEEDS:
            rng = random.Random(seed)
            for _ in range(ROUNDS):
                config = {key: rng.choice(pool) for key, pool in (("own_work", values), ("repo", REPOS)) if rng.random() < 0.9}
                repo = rng.choice(REPOS)
                level = own_work_verdict(config, repo, SHA).level
                wanted = config.get("own_work") == "trusted" and bool(repo_id(config.get("repo", ""))) and repo_id(config.get("repo", "")) == repo_id(repo)
                self.assertEqual(level is TrustLevel.TRUSTED, wanted, (config, repo))


ROUTES = ("repos/acme/app/pulls/7", "repos/acme/app/pulls/7/commits?per_page=100", "repos/acme/app/pulls/7/files?per_page=100",
          "repos/acme/app/collaborators/alice/permission", "orgs/acme/teams/core/memberships/alice")
GOOD: dict[str, Any] = {
    ROUTES[0]: {"state": "open", "head": {"sha": SHA, "repo": {"full_name": PROJECT}}, "base": {"repo": {"full_name": PROJECT}},
                "user": {"login": "alice"}, "author_association": "OWNER", "commits": 1, "changed_files": 1},
    ROUTES[1]: [{"sha": SHA, "author": {"login": "alice"}}],
    ROUTES[2]: [{"filename": "src/a.py"}],
    ROUTES[3]: {"role_name": "write"},
    ROUTES[4]: {"state": "active"},
}
RULES = TrustRules(frozenset({"write"}), "acme/core", frozenset(), PROJECT)


class HostAnswers(unittest.TestCase):
    """Whatever GitHub answers, or fails to: nothing raises, and a damaged answer never proves anything."""

    def check(self, routes: dict[str, Any], token: str = "t") -> Any:
        return PullRequestTrust(GhCli(FakeGitHub(routes), token), RULES, PROTECTED).check(PROJECT, 7, SHA)

    def test_the_untouched_answer_is_trusted(self) -> None:
        self.assertIs(self.check(dict(GOOD)).level, TrustLevel.TRUSTED)

    def test_every_error_status_at_any_route_stays_untrusted(self) -> None:
        for route in ROUTES[:3]:
            for status in (400, 401, 403, 404, 409, 422, 429, 500, 502, 503):
                self.assertIs(self.check({**GOOD, route: status}).level, TrustLevel.UNTRUSTED, (route, status))

    def test_a_missing_token_stays_untrusted(self) -> None:
        self.assertEqual(self.check(dict(GOOD), token="").rule, "no-token")

    def test_a_hung_gh_at_any_route_stays_untrusted(self) -> None:
        for route in ROUTES:
            def run(argv: Any, _stdin: Any = None, _timeout: int = 60, hang: str = route) -> Done:
                if argv[2] == hang:
                    raise CommandTimeout("gh did not answer")
                return Done(0, json.dumps(GOOD[argv[2]]))

            verdict = PullRequestTrust(GhCli(run, "t"), RULES, PROTECTED).check(PROJECT, 7, SHA)
            self.assertIs(verdict.level, TrustLevel.UNTRUSTED, route)

    def test_a_process_that_prints_rubbish_stays_untrusted(self) -> None:
        for out in ("", "not json", "null", "[]", "{}", "1", '"x"', "{" * 50):
            run = lambda *_a, text=out, **_k: Done(0, text)  # noqa: E731
            self.assertIs(PullRequestTrust(GhCli(run, "t"), RULES, PROTECTED).check(PROJECT, 7, SHA).level, TrustLevel.UNTRUSTED, out)

    def test_junk_at_any_route_never_raises_and_a_fact_it_breaks_is_never_proof(self) -> None:
        for seed in SEEDS:
            rng = random.Random(seed)
            for _ in range(ROUNDS // 4):
                routes = dict(GOOD)
                for route in rng.sample(ROUTES[:4], rng.randint(1, 3)):
                    routes[route] = rng.choice(JUNK)
                verdict = self.check(routes)  # raising here fails the test
                if routes[ROUTES[0]] is not GOOD[ROUTES[0]]:  # with the pull request itself gone, nothing can match
                    self.assertIs(verdict.level, TrustLevel.UNTRUSTED, routes)

    def test_junk_inside_the_pull_request_is_never_proof(self) -> None:
        for seed in SEEDS:
            rng = random.Random(seed)
            for key in ("state", "head", "base", "user", "commits", "changed_files"):
                value = rng.choice([item for item in JUNK if item != GOOD[ROUTES[0]][key]])  # 1 and True are the right count
                pull = {**GOOD[ROUTES[0]], key: value}
                verdict = self.check({**GOOD, ROUTES[0]: pull})
                self.assertIs(verdict.level, TrustLevel.UNTRUSTED, pull)


if __name__ == "__main__":
    unittest.main()
