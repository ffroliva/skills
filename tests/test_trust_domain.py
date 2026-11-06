"""The trust decision: anything not proven trusted is untrusted, and the decision is about one exact commit."""

from __future__ import annotations

import unittest
from dataclasses import replace

import helpers  # noqa: F401

from sbxlib.domain.trust import PullFacts, Standing, TrustLevel, TrustRules, decide, unknown_roles

SHA = "a" * 40
MEMBER = Standing(role="write", teams=frozenset({"acme/core"}))
OUTSIDER = Standing(role="read")
ADOPTION = ("docs/sbx.md",)


def facts(**changes: object) -> PullFacts:
    base = PullFacts(7, SHA, "open", "alice", "CONTRIBUTOR", "acme/app", "acme/app", 1, ("alice",), 1, ("src/a.py",),
                     {"alice": MEMBER})
    return replace(base, **changes)  # type: ignore[arg-type]


REPO = "acme/app"
ROLES = TrustRules(roles=frozenset({"write", "maintain", "admin"}), repo=REPO)


class Decide(unittest.TestCase):
    def assert_untrusted(self, rule: str, rules: TrustRules, pull: PullFacts, sha: str = SHA) -> None:
        verdict = decide(rules, pull, sha, ADOPTION)
        self.assertEqual((verdict.level, verdict.rule), (TrustLevel.UNTRUSTED, rule))

    def test_a_role_rule_trusts_a_member_at_that_exact_sha(self) -> None:
        verdict = decide(ROLES, facts(), SHA, ADOPTION)
        self.assertEqual((verdict.level, verdict.rule), (TrustLevel.TRUSTED, "role:write"))

    def test_a_team_rule_trusts_its_member(self) -> None:
        verdict = decide(TrustRules(team="acme/core", repo=REPO), facts(), SHA, ADOPTION)
        self.assertEqual((verdict.level, verdict.rule), (TrustLevel.TRUSTED, "team:acme/core"))

    def test_a_login_rule_trusts_a_named_login(self) -> None:
        pull = facts(standings={"alice": OUTSIDER})
        verdict = decide(TrustRules(logins=frozenset({"alice"}), repo=REPO), pull, SHA, ADOPTION)
        self.assertEqual((verdict.level, verdict.rule), (TrustLevel.TRUSTED, "login:alice"))

    def test_login_comparison_ignores_case_as_github_does(self) -> None:
        pull = facts(author="Alice", commit_authors=("alice",), standings={"Alice": OUTSIDER, "alice": OUTSIDER})
        self.assertIs(decide(TrustRules(logins=frozenset({"ALICE"}), repo=REPO), pull, SHA, ADOPTION).level, TrustLevel.TRUSTED)

    def test_no_rule_set_means_untrusted_even_for_an_owner(self) -> None:
        self.assert_untrusted("no-rules", TrustRules(), facts(author_association="OWNER"))

    def test_author_association_never_grants_trust(self) -> None:
        self.assert_untrusted("no-rule-matched", ROLES, facts(author_association="MEMBER", standings={"alice": OUTSIDER}))

    def test_a_push_after_the_check_is_untrusted(self) -> None:
        self.assert_untrusted("sha-changed", ROLES, facts(head_sha="b" * 40))

    def test_a_closed_pull_request_is_untrusted(self) -> None:
        self.assert_untrusted("pull-not-open", ROLES, facts(state="closed"))

    def test_a_read_role_is_never_enough(self) -> None:
        self.assert_untrusted("no-rule-matched", TrustRules(roles=frozenset({"read"}), repo=REPO), facts(standings={"alice": OUTSIDER}))

    def test_an_unknown_login_is_untrusted(self) -> None:
        self.assert_untrusted("no-rule-matched", ROLES, facts(standings={}))

    def test_a_trusted_author_carrying_another_persons_commit_is_untrusted(self) -> None:
        pull = facts(commit_count=2, commit_authors=("alice", "mallory"), standings={"alice": MEMBER, "mallory": OUTSIDER})
        self.assert_untrusted("foreign-commit", ROLES, pull)

    def test_a_commit_mapped_to_no_account_is_untrusted(self) -> None:
        self.assert_untrusted("foreign-commit", ROLES, facts(commit_count=2, commit_authors=("alice", "")))

    def test_two_trusted_authors_are_trusted(self) -> None:
        pull = facts(commit_count=2, commit_authors=("alice", "bob"), standings={"alice": MEMBER, "bob": MEMBER})
        self.assertIs(decide(ROLES, pull, SHA, ADOPTION).level, TrustLevel.TRUSTED)

    def test_a_pull_request_editing_the_adoption_file_cannot_trust_itself(self) -> None:
        self.assert_untrusted("adoption-file-changed", ROLES, facts(files=("src/a.py", ADOPTION[0]), file_count=2))

    def test_a_commit_list_longer_than_a_page_is_not_read_as_clean(self) -> None:
        self.assert_untrusted("listing-incomplete", ROLES, facts(commit_count=101))

    def test_a_file_list_longer_than_a_page_is_not_read_as_clean(self) -> None:
        self.assert_untrusted("listing-incomplete", ROLES, facts(file_count=101))

    def test_a_short_commit_listing_is_not_read_as_clean(self) -> None:
        self.assert_untrusted("listing-incomplete", ROLES, facts(commit_count=3))

    def test_the_verdict_carries_the_exact_commit_and_what_was_seen(self) -> None:
        verdict = decide(ROLES, facts(), SHA, ADOPTION).to_json()
        self.assertEqual(verdict["level"], "trusted")
        evidence = verdict["evidence"]
        self.assertIsInstance(evidence, dict)
        assert isinstance(evidence, dict)
        self.assertEqual((evidence["sha"], evidence["pull"], evidence["author"], evidence["author_association"]),
                         (SHA, 7, "alice", "CONTRIBUTOR"))

    def test_read_and_triage_are_reported_as_unusable_roles(self) -> None:
        self.assertEqual(unknown_roles(TrustRules(roles=frozenset({"read", "triage", "write"}))), ["read", "triage"])


if __name__ == "__main__":
    unittest.main()
