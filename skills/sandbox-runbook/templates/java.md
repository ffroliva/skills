# Recipe for {{TARGET_PROJECT}}: Java (Maven, Surefire)

Measured on a target project, not independently reproducible: a Java 25, Spring Boot service with a Maven wrapper.
Sharding a Maven suite across boxes is **an untested idea**: start with one command per box.

## One box, full build

```bash
python <skill>/scripts/sbx_fleet.py --config docs/sbx.md --repo "$(git remote get-url origin)" --sha "$(git rev-parse HEAD)" \
  --cpus 4 --memory 8g --command './mvnw -B verify; rc=$?; cp target/surefire-reports/*.xml $OUT/ 2>/dev/null; exit $rc'
```

Keep the exit code as above: a bare `&&` chain drops the reports of a failing build.

## Selecting a shard

Surefire writes one report per class, so a class is the unit. Plan from a green run's reports, one plan per platform:

```bash
python <skill>/scripts/sbx_shard.py plan --junit <reports> --n 3 > shards-linux.json
python <skill>/scripts/sbx_shard.py check --plan shards-linux.json
```

Print the box's classes from the plan and pass them with Surefire's `-Dtest`. This one-liner is untested:

```bash
TESTS=$(python3 -c 'import json, os; p = json.load(open("shards-linux.json")); print(",".join(p["shards"][int(os.environ["SHARD"]) - 1]["units"]))')
./mvnw -B verify -Dtest="$TESTS"
```

## One command per box

Unit and integration suites make a natural split. Give each its own `--command`.

```bash
--command './mvnw -B verify' --command './mvnw -B verify -Pit'
```

The `-Pit` profile is an example: use your own integration profile.

## Know before you start

- Each new box starts with an empty `~/.m2`. Do not share a writable one across boxes.
- The v3 agent workload ships no JDK, and the built-in agent template does. Moving a project onto kits silently loses Java:
  add a JDK mixin.
- Behind a TLS-filtering firewall, Maven's wrapper download can hang while the policy log says allowed.
- An agent's own build in a box: `sbx create --clone --cpus 4 --memory 8g claude <repo>`.
