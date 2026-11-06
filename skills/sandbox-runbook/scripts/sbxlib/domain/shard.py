"""Split a suite across boxes. Language-agnostic: a unit is whatever one worker must keep together.

Measured units go longest first onto the lightest shard; an unmeasured unit goes by a hash of its name, so a new unit
never moves another. A unit that alone exceeds the ceiling leaves the shards for its own job: no shard count fixes it.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Collection, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class ShardPlan:
    n: int
    shards: tuple[tuple[str, ...], ...]  # shards[0] is shard 1
    own_job: tuple[str, ...]
    unmeasured: tuple[str, ...]
    weights: Mapping[str, float]

    def loads(self) -> list[float]:
        return [sum(self.weights.get(unit, 0.0) for unit in shard) for shard in self.shards]


def hash_shard(unit: str, n: int) -> int:
    """0-based. Stable across runs and machines, and a new unit never moves another."""
    return int(hashlib.sha256(unit.encode()).hexdigest(), 16) % n


def _allowed(unit: str, n: int, heavy: Collection[str], timing: Collection[str]) -> range:
    """Timing units go to the last shard and heavy units never do, so a CPU-heavy unit never shares a box with a budget test.
    An ordinary unit may share the last shard with them."""
    if n < 2 or not timing:
        return range(n)
    if unit in timing:
        return range(n - 1, n)
    return range(n - 1) if unit in heavy else range(n)


def plan(units: Collection[str], weights: Mapping[str, float], n: int, *, ceiling: float | None = None,
         heavy: Collection[str] = (), timing: Collection[str] = (), own_job: Collection[str] = ()) -> ShardPlan:
    alone = {u for u in units if u in own_job or (ceiling is not None and weights.get(u, 0.0) > ceiling)}
    measured = sorted((u for u in units if u in weights and u not in alone), key=lambda u: (-weights[u], u))
    blind = sorted(u for u in units if u not in weights and u not in alone)
    shards: list[list[str]] = [[] for _ in range(n)]
    loads = [0.0] * n
    for unit in measured:
        lightest = min(_allowed(unit, n, heavy, timing), key=lambda i: (loads[i], i))
        shards[lightest].append(unit)
        loads[lightest] += weights[unit]
    for unit in blind:
        allowed = _allowed(unit, n, heavy, timing)
        shards[allowed[hash_shard(unit, len(allowed))]].append(unit)
    return ShardPlan(n, tuple(tuple(shard) for shard in shards), tuple(sorted(alone)), tuple(blind), weights)


def lower_bound(weights: Collection[float], n: int) -> float:
    """No split beats this. With more units than shards, two of the n+1 largest must share a shard."""
    ordered = sorted(weights, reverse=True)
    pair = ordered[n - 1] + ordered[n] if len(ordered) > n else 0.0
    return max(ordered[0] if ordered else 0.0, sum(ordered) / n, pair)


def shards_needed(weights: Mapping[str, float], ceiling: float) -> int:
    """The smallest count under the ceiling, leaving out any unit that alone exceeds it."""
    fit = {unit: seconds for unit, seconds in weights.items() if seconds <= ceiling}
    return next(n for n in range(1, len(fit) + 2) if max(plan(fit, fit, n).loads(), default=0.0) <= ceiling)


def _placement(found: ShardPlan, suite: Collection[str] | None) -> list[str]:
    placed = Counter(unit for shard in found.shards for unit in shard) + Counter(found.own_job)
    problems = [f"in more than one place: {unit}" for unit, count in sorted(placed.items()) if count > 1]
    problems += [f"shard {i} is empty: a runner may exit non-zero with no tests"
                 for i, shard in enumerate(found.shards, 1) if not shard]
    if suite is not None:
        problems += [f"in no shard: {unit}" for unit in sorted(set(suite) - set(placed))]
        problems += [f"not in the suite: {unit}" for unit in sorted(set(placed) - set(suite))]
    return problems


def _loads(found: ShardPlan, ceiling: float | None, constrained: bool) -> list[str]:
    in_shards = {unit: found.weights[unit] for shard in found.shards for unit in shard if unit in found.weights}
    floor = lower_bound(list(in_shards.values()), found.n)
    problems: list[str] = []
    for index, load in enumerate(found.loads(), 1):
        if not constrained and load > 4 / 3 * floor + 1e-9:  # placement limits void the longest-first guarantee
            problems.append(f"shard {index} carries {load:.0f} s, over 4/3 of the {floor:.0f} s lower bound")
        if ceiling is not None and load > ceiling and len(_units_of(found, index)) > 1:
            problems.append(f"shard {index} carries {load:.0f} s, over the {ceiling:.0f} s ceiling: "
                            f"use {shards_needed(in_shards, ceiling)} shards")
    if ceiling is not None:
        problems += [f"{unit} alone carries {seconds:.0f} s, over the {ceiling:.0f} s ceiling: "
                     "give it its own job; no shard count fixes it"
                     for unit, seconds in sorted(in_shards.items()) if seconds > ceiling]
    return problems


def _units_of(found: ShardPlan, index: int) -> tuple[str, ...]:
    return found.shards[index - 1]


def check(found: ShardPlan, suite: Collection[str] | None = None, *, ceiling: float | None = None,
          max_unmeasured: float = 0.05, heavy: Collection[str] = (), timing: Collection[str] = ()) -> list[str]:
    """Every bound a plan must keep. [] means it keeps them."""
    problems = _placement(found, suite) + _loads(found, ceiling, bool(heavy and timing))
    total = sum(len(shard) for shard in found.shards) + len(found.own_job)
    if total and len(found.unmeasured) / total > max_unmeasured:
        problems.append(f"{len(found.unmeasured)} of {total} units unmeasured, over {max_unmeasured:.0%}: "
                        "refresh the weights from a real run")
    for index, shard in enumerate(found.shards, 1):
        both = sorted(set(shard) & set(heavy)) + sorted(set(shard) & set(timing))
        if set(shard) & set(heavy) and set(shard) & set(timing):
            problems.append(f"shard {index} holds both heavy and timing units: {', '.join(both)}")
    return problems


def advice(found: ShardPlan, ceiling: float | None = None) -> list[str]:
    """When more shards are the wrong answer."""
    total = sum(found.weights.values())
    notes: list[str] = []
    if ceiling is not None and found.n > 1 and total <= ceiling:
        notes.append(f"the whole suite is {total:.0f} s, under the {ceiling:.0f} s ceiling: one box is enough")
    notes += [f"{unit} is {seconds:.0f} s of the {total:.0f} s suite: split it before adding boxes"
              for unit, seconds in sorted(found.weights.items()) if found.n > 1 and seconds > total / found.n]
    return notes
