"""The shard planner, with seeded property tests: stdlib only, so a failure names its seed."""

from __future__ import annotations

import itertools
import random
import unittest

import helpers  # noqa: F401

from sbxlib.domain.junit import Outcome, TestCase, per_box, problems, weights
from sbxlib.domain.shard import ShardPlan, advice, check, hash_shard, lower_bound, plan, shards_needed

SEEDS = range(200)


def instance(seed: int) -> tuple[dict[str, float], int]:
    rng = random.Random(seed)
    table = {f"u{i}": float(rng.randint(1, 60)) for i in range(rng.randint(1, 30))}
    return table, rng.randint(1, 7)


def best_makespan(values: list[float], n: int) -> float:
    return min(max(sum(v for v, s in zip(values, choice, strict=True) if s == i) for i in range(n))
               for choice in itertools.product(range(n), repeat=len(values)))


class Plan(unittest.TestCase):
    def test_every_unit_lands_in_exactly_one_place(self) -> None:
        for seed in SEEDS:
            table, n = instance(seed)
            units = [*table, "new_a", "new_b"]
            result = plan(units, table, n, ceiling=40.0)
            placed = [unit for shard in result.shards for unit in shard] + list(result.own_job)
            self.assertEqual(sorted(placed), sorted(units), f"seed {seed}")
            self.assertEqual(len(result.shards), n, f"seed {seed}")

    def test_load_stays_within_four_thirds_of_the_lower_bound(self) -> None:
        for seed in SEEDS:
            table, n = instance(seed)
            result = plan(table, table, n)
            self.assertLessEqual(max(result.loads()), 4 / 3 * lower_bound(table.values(), n) + 1e-9, f"seed {seed}")

    def test_the_planner_is_longest_first_within_graham_of_the_true_optimum(self) -> None:
        for seed in range(40):
            rng = random.Random(seed)
            n = rng.randint(2, 3)
            table = {f"u{i}": float(rng.randint(1, 30)) for i in range(rng.randint(n + 1, 7))}
            best = best_makespan(list(table.values()), n)
            self.assertLessEqual(max(plan(table, table, n).loads()), (4 / 3 - 1 / (3 * n)) * best + 1e-9, f"seed {seed}")

    def test_four_equal_units_on_three_shards_do_not_break_the_bound(self) -> None:
        """max(largest, mean) alone is too low here: 4/3 of it is 1.78, and no split beats 2."""
        table = dict.fromkeys("abcd", 1.0)
        self.assertEqual(lower_bound(table.values(), 3), 2.0)
        self.assertEqual(check(plan(table, table, 3), table), [])

    def test_longest_goes_first_onto_the_lightest_shard(self) -> None:
        result = plan(["a", "b", "c", "d"], {"a": 9.0, "b": 5.0, "c": 4.0, "d": 1.0}, 2)
        self.assertEqual(result.shards, (("a", "d"), ("b", "c")))

    def test_an_unmeasured_unit_goes_by_hash_and_is_reported(self) -> None:
        result = plan(["a", "new"], {"a": 1.0}, 4)
        self.assertEqual(result.unmeasured, ("new",))
        self.assertIn("new", result.shards[hash_shard("new", 4)])

    def test_a_new_unit_never_moves_a_measured_one(self) -> None:
        table = {f"u{i}": float(i + 1) for i in range(12)}
        before = plan(table, table, 3)
        after = plan([*table, "new"], table, 3)
        for old, new in zip(before.shards, after.shards, strict=True):
            self.assertEqual(old, tuple(unit for unit in new if unit != "new"))

    def test_the_hash_is_stable(self) -> None:
        self.assertEqual(hash_shard("tests/test_a.py", 8), hash_shard("tests/test_a.py", 8))
        self.assertEqual(hash_shard("tests/test_a.py", 1000), 347)

    def test_a_unit_over_the_ceiling_gets_its_own_job(self) -> None:
        result = plan(["big", "a"], {"big": 487.0, "a": 10.0}, 3, ceiling=170.0)
        self.assertEqual(result.own_job, ("big",))
        self.assertNotIn("big", [unit for shard in result.shards for unit in shard])

    def test_a_named_own_job_unit_leaves_the_shards_whatever_its_weight(self) -> None:
        self.assertEqual(plan(["gate", "a"], {"gate": 1.0, "a": 1.0}, 2, own_job=["gate"]).own_job, ("gate",))

    def test_heavy_and_timing_units_never_share_a_shard(self) -> None:
        for seed in SEEDS:
            table, n = instance(seed)
            if n < 2:
                continue
            names = sorted(table)
            timing = names[:2]
            heavy = [unit for unit in table if table[unit] >= 30 and unit not in timing]
            result = plan([*table, "new_timing"], table, n, heavy=heavy, timing=[*timing, "new_timing"])
            found = check(result, heavy=heavy, timing=[*timing, "new_timing"], max_unmeasured=1.0)
            self.assertEqual([line for line in found if "holds both" in line], [], f"seed {seed}")

    def test_with_one_shard_there_is_nothing_to_separate(self) -> None:
        result = plan(["h", "t"], {"h": 40.0, "t": 1.0}, 1, heavy=["h"], timing=["t"])
        self.assertEqual(result.shards, (("h", "t"),))


class Bounds(unittest.TestCase):
    def good(self) -> ShardPlan:
        return plan(["a", "b"], {"a": 1.0, "b": 1.0}, 2)

    def test_a_good_plan_passes(self) -> None:
        self.assertEqual(check(self.good(), ["a", "b"]), [])

    def test_a_unit_in_two_shards_is_a_problem(self) -> None:
        bad = ShardPlan(2, (("a", "b"), ("b",)), (), (), {"a": 1.0, "b": 1.0})
        self.assertIn("in more than one place: b", check(bad, ["a", "b"]))

    def test_a_unit_in_no_shard_is_a_problem(self) -> None:
        bad = ShardPlan(2, (("a",), ("c",)), (), (), {"a": 1.0, "c": 1.0})
        self.assertIn("in no shard: b", check(bad, ["a", "b", "c"]))

    def test_a_unit_outside_the_suite_is_a_problem(self) -> None:
        self.assertIn("not in the suite: b", check(self.good(), ["a"]))

    def test_an_own_job_unit_counts_as_placed(self) -> None:
        result = plan(["a", "b", "big"], {"a": 1.0, "b": 1.0, "big": 99.0}, 2, ceiling=10.0)
        self.assertEqual(check(result, ["a", "b", "big"], ceiling=10.0), [])

    def test_an_empty_shard_is_a_problem(self) -> None:
        self.assertIn("shard 2 is empty: a runner may exit non-zero with no tests", check(plan(["a"], {"a": 1.0}, 2)))

    def test_a_load_over_the_longest_first_bound_is_a_problem(self) -> None:
        bad = ShardPlan(2, (("a", "b", "c"), ("d",)), (), (), dict.fromkeys("abcd", 10.0))
        self.assertIn("shard 1 carries 30 s, over 4/3 of the 20 s lower bound", check(bad))

    def test_a_load_over_the_ceiling_names_the_shard_count_that_fits(self) -> None:
        table = dict.fromkeys("abcdef", 10.0)
        found = check(plan(table, table, 2), table, ceiling=20.0)
        self.assertIn("shard 1 carries 30 s, over the 20 s ceiling: use 3 shards", found)

    def test_a_unit_alone_over_the_ceiling_is_named_not_answered_with_more_shards(self) -> None:
        bad = ShardPlan(2, (("big",), ("a",)), (), (), {"big": 300.0, "a": 1.0})
        self.assertIn("big alone carries 300 s, over the 20 s ceiling: give it its own job; no shard count fixes it",
                      check(bad, ceiling=20.0))

    def test_too_many_unmeasured_units_ask_for_a_refresh(self) -> None:
        table = {f"u{i}": 1.0 for i in range(9)}
        found = check(plan([*table, "new"], table, 2), max_unmeasured=0.05)
        self.assertIn("1 of 10 units unmeasured, over 5%: refresh the weights from a real run", found)

    def test_unmeasured_units_within_the_limit_pass(self) -> None:
        table = {f"u{i}": 1.0 for i in range(19)}
        self.assertEqual(check(plan([*table, "new"], table, 2), max_unmeasured=0.05), [])

    def test_a_heavy_unit_sharing_with_a_timing_test_is_a_problem(self) -> None:
        bad = ShardPlan(2, (("h", "t"), ("a",)), (), (), {"h": 40.0, "t": 1.0, "a": 39.0})
        self.assertIn("shard 1 holds both heavy and timing units: h, t", check(bad, heavy=["h"], timing=["t"]))

    def test_shards_needed_is_the_smallest_count_under_the_ceiling(self) -> None:
        self.assertEqual(shards_needed(dict.fromkeys("abcdef", 10.0), 20.0), 3)
        self.assertEqual(shards_needed({"a": 5.0}, 20.0), 1)

    def test_shards_needed_ignores_a_unit_no_count_can_fit(self) -> None:
        self.assertEqual(shards_needed({"big": 99.0, "a": 10.0}, 20.0), 1)


class WhenNotToShard(unittest.TestCase):
    def test_one_box_under_the_ceiling_needs_no_shards(self) -> None:
        table = {"a": 5.0, "b": 5.0}
        self.assertIn("the whole suite is 10 s, under the 60 s ceiling: one box is enough", advice(plan(table, table, 2), 60.0))

    def test_a_dominant_unit_is_called_out(self) -> None:
        table = {"big": 100.0, "a": 1.0, "b": 1.0}
        self.assertIn("big is 100 s of the 102 s suite: split it before adding boxes", advice(plan(table, table, 3)))

    def test_a_balanced_suite_gets_no_advice(self) -> None:
        table = dict.fromkeys("abcdef", 10.0)
        self.assertEqual(advice(plan(table, table, 2)), [])


def case(box: str, name: str, outcome: Outcome = Outcome.PASSED, seconds: float = 1.0, classname: str = "C") -> TestCase:
    return TestCase(box, classname, name, f"{classname}.py", seconds, outcome)


class Junit(unittest.TestCase):
    def test_weights_sum_by_unit(self) -> None:
        self.assertEqual(weights([case("b1", "a", seconds=1.5), case("b1", "b", seconds=2.5), case("b2", "c", classname="D")]),
                         {"C.py": 4.0, "D.py": 1.0})

    def test_per_box_lines_count_every_outcome(self) -> None:
        cases = [case("b1", "a"), case("b1", "b", Outcome.FAILED), case("b1", "c", Outcome.ERROR), case("b2", "d", Outcome.SKIPPED)]
        self.assertEqual(per_box(cases), ["b1: 3 tests, 1 failures, 1 errors, 0 skipped",
                                          "b2: 1 tests, 0 failures, 0 errors, 1 skipped",
                                          "total: 4 tests, 1 failures, 1 errors, 1 skipped"])

    def test_clean_cases_at_the_expected_count_pass(self) -> None:
        self.assertEqual(problems([case("b1", "a"), case("b2", "b")], expect=2), [])

    def test_a_lost_shard_fails_on_the_count(self) -> None:
        self.assertIn("expected 3 unique tests, found 2: a shard was lost", problems([case("b1", "a"), case("b2", "b")], expect=3))

    def test_a_doubled_test_cannot_hide_a_lost_one(self) -> None:
        found = problems([case("b1", "a"), case("b2", "a"), case("b1", "b")], expect=3)
        self.assertIn("expected 3 unique tests, found 2: a shard was lost", found)

    def test_a_test_in_two_boxes_is_overlap(self) -> None:
        self.assertIn("1 test ran in more than one box: the shards overlap", problems([case("b1", "a"), case("b2", "a")]))

    def test_a_repeat_inside_one_box_is_not_overlap(self) -> None:
        self.assertEqual(problems([case("b1", "a"), case("b1", "a")]), [])

    def test_a_failure_is_a_problem(self) -> None:
        self.assertIn("1 failed, 0 errors", problems([case("b1", "a", Outcome.FAILED)]))

    def test_an_error_is_a_problem(self) -> None:
        self.assertIn("0 failed, 1 errors", problems([case("b1", "a", Outcome.ERROR)]))

    def test_a_skip_is_not_a_failure(self) -> None:
        self.assertEqual(problems([case("b1", "a", Outcome.SKIPPED)]), [])

    def test_no_cases_at_all_is_a_problem(self) -> None:
        self.assertIn("no test cases found", problems([]))


if __name__ == "__main__":
    unittest.main()
