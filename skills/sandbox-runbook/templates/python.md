# Recipe for {{TARGET_PROJECT}}: Python (pytest, xdist, uv)

Run from the project root. `<skill>` is the folder holding this skill. On sbx 0.51.0 `shell` ships uv and Python 3.14.

The recipe does not choose a Python. A box takes what uv picks, 3.14.10 on one run, so to match CI write `uv sync --python <CI's version>` in `command`.

## Full suite on shards

```bash
python <skill>/scripts/sbx_fleet.py --config docs/sbx.md --repo "$(git remote get-url origin)" --sha "$(git rev-parse HEAD)" \
  --boxes 5 --out ../{{TARGET_PROJECT}}-fleet-out
python <skill>/scripts/sbx_shard.py check --junit ../{{TARGET_PROJECT}}-fleet-out --expect <unique tests in the suite>
```

Box names read `{{TARGET_PROJECT}}-shards-01-k3f9`, and results land in a folder of that name.

`docs/sbx.md` holds `command` and `allow`. A sharded run's command must read `$SHARD`, or five boxes each run everything.

## Selecting a shard

If the project already shards (a plugin such as pytest-split, a shard file, a shard variable in CI), do not add a filter:
map `$SHARD` of `$SHARDS` onto what it has. `sbx_detect.py` lists what it found under `sharding`.

Otherwise plan from a green run's JUnit, one plan per platform. `-o junit_family=xunit1` adds the `file` attribute that makes
a file the unit.

```bash
python <skill>/scripts/sbx_shard.py plan --junit <green-run> --n 5 --ceiling 170 > shards-linux.json
python <skill>/scripts/sbx_shard.py check --plan shards-linux.json --ceiling 170
```

Add this to the root `conftest.py`. It skips a file before importing it, keeps a file together, and places a file the plan
does not know by the same hash as the planner, so a new file never moves another. Ignoring at this hook is cheaper than
deselecting after collection, which imports everything.

```python
import hashlib
import json
import os
from pathlib import Path

SHARD, SHARDS = int(os.environ.get("SHARD", 1)), int(os.environ.get("SHARDS", 1))
PLAN = json.loads(Path(__file__).with_name("shards-linux.json").read_text()) if SHARDS > 1 else {"shards": []}
OWNER = {unit: entry["index"] for entry in PLAN["shards"] for unit in entry["units"]}
OWN_JOB = set(PLAN.get("own_job", ()))


def pytest_ignore_collect(collection_path, config):
    if SHARDS == 1 or not collection_path.is_file() or not collection_path.name.startswith("test_"):
        return None  # None, never False: False would override every other ignore rule
    unit = collection_path.relative_to(config.rootpath).as_posix()
    if unit in OWN_JOB:
        return True
    owner = OWNER.get(unit, int(hashlib.sha256(unit.encode()).hexdigest(), 16) % SHARDS + 1)
    return True if owner != SHARD else None
```

Run the `own_job` files in their own box: `--command 'uv run pytest <file> --junitxml=$OUT/junit.xml'`.

## Database tests

One database per worker, and one worker per vCPU: memory runs out before CPU. Give each xdist worker its own, keyed on
`PYTEST_XDIST_WORKER`, or the workers share state.

## Testcontainers

Tried once on sbx 0.51.0 (one PostgreSQL container, one worker). Use `template: shell`, and keep `**.docker.com` and
`**.docker.io` in `allow`. `*.docker.com` is not enough: blobs come from a host two labels deep.

Count container starts on a few tests before the whole gate, and keep `-o timeout_func_only=true` if you use pytest-timeout, which
otherwise counts a container's boot against the first test. The skill's Testcontainers note says why.

Pre-pull with retries before the tests. Docker Hub answers 5xx now and then, and Testcontainers pulls its reaper image once,
then dies on the failure.

```bash
pull() { for i in 1 2 3 4 5; do docker pull -q "$1" && return 0; sleep $((i * 5)); done; return 1; }
pull postgres:17-alpine && pull "$(uv run --no-sync python -c 'from testcontainers.core.config import testcontainers_config as c; print(c.ryuk_image)')"
```

The attribute `testcontainers_config.ryuk_image` is unverified here, so test the one-liner locally first. Failing that, run once in
a probe box, then `docker images --format '{{.Repository}}:{{.Tag}}' | grep -i ryuk`.

If tests use a fake HTTP transport, run them with the proxy variables unset (`env -u HTTP_PROXY -u HTTPS_PROXY`): the box's
egress proxy settings otherwise catch that traffic.

## Playwright

Add `storage.googleapis.com` and `*.playwright.dev` to `allow`, and use `-n 4` for browser tests. To avoid the per-run
install, bake the browser into a kit whose Playwright version equals your lock file's.
