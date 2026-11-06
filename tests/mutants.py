"""Hand-picked safety mutants: each breaks one rule on purpose, and the suite must fail. Run weekly (.github/workflows/mutants.yml).

Not `test_*`, so discovery skips it. Exit 1 when a mutant survives or no longer applies: a mutant that stops matching the source
proves nothing, so it is rewritten with the code. `python tests/mutants.py [label substring]`; costs minutes, runs no sbx.
"""
import concurrent.futures as cf
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
L = "skills/sandbox-runbook/scripts/"
AF, AT = L + "sbxlib/app/fleet.py", L + "sbxlib/app/trust.py"
JX = L + "sbxlib/adapters/junit_xml.py"
DF, DS, DJ, DD = L + "sbxlib/domain/fleet.py", L + "sbxlib/domain/shard.py", L + "sbxlib/domain/junit.py", L + "sbxlib/domain/drift.py"
CLI, PROC, GIT, FILES = L + "sbxlib/adapters/sbx_cli.py", L + "sbxlib/adapters/process.py", L + "sbxlib/adapters/git_cli.py", L + "sbxlib/adapters/files.py"
TR, FLEET_D, ADO, TRUST_E, SBX_CHECK = L + "sbxlib/domain/trust.py", L + "sbxlib/domain/fleet.py", L + "sbxlib/domain/adoption.py", L + "sbx_trust.py", L + "sbx_check.py"
T5 = "skills/sandbox-runbook/templates/github-pr-target.yml"
ADR, CHK, V, F, SCAN, ONB, GH = L + "sbxlib/app/drift.py", L + "sbxlib/app/check.py", L + "validate_skill.py", L + "sbx_fleet.py", L + "sbxlib/adapters/project_scan.py", L + "sbxlib/domain/onboard.py", L + "sbxlib/adapters/gh_cli.py"

M = [
 ("cleanup never runs", AF, "            self._remove(name)  # a create", "            pass  # a create"),
 ("no --on-timeout delete", CLI, '"--on-timeout", "delete", "--no-progress"]', '"--no-progress"]'),
 ("no --ttl", CLI, '"--ttl", f"{request.ttl_minutes}m",', ''),
 ("scrub is a no-op", DF, '    for value in filter(None, values):\n        text = text.replace(value, "***")\n', ""),
 ("tar extract trusts the archive", FILES, "                    _write(tar, member, root)", '                    tar.extract(member, root, filter="fully_trusted")'),
 ("R4H1 links pass the check", FILES, "if not (member.isreg() or member.isdir()) or any(", "if any("),
 ("R4H1 names pass the check", FILES, " or any(_BAD_PART.search(part) for part in member.name.split(\"/\")):", ":"),
 ("R4H1 check skipped", FILES, "                _check(member)\n", ""),
 ("R4H1 no folder check", FILES, "    if not path.parent.resolve().is_relative_to(root):", "    if False:"),
 ("signal handlers never installed", F, 'names = [name for name in ("SIGTERM", "SIGBREAK", "SIGHUP") if hasattr(signal, name)]', "names: list[str] = []"),
 ("Ctrl+C does not set stop", AF, "                run.stop.set()  # each box", "                pass  # each box"),
 ("main no longer maps interrupt to 130", AF, "code = 130 if stop.is_set() else exit_code(", "code = exit_code("),
 ("wait_done ignores stop", AF, '            if self.stop.is_set():\n                return "interrupted"\n            clock.sleep(POLL_S)', "            clock.sleep(POLL_S)"),
 ("box starts after stop", AF, '        if self.stop.is_set():\n            return BoxResult(index, fatal="interrupted")\n        try:', "        try:"),
 ("left-behind warning silent", AF, "    for name in left:\n        edge.out(_left_line(name))\n", ""),
 ("rm timeout escapes cleanup", AF, '        except CommandTimeout:\n            pass  # the final check finds what this left\n        except Exception as exc:  # the same: the final check must still run\n            self.tell(f"fleet: removing {name}: {type(exc).__name__}; the final check looks again")\n', "        except ZeroDivisionError:\n            pass\n"),
 ("no create retry", AF, "CREATE_ATTEMPTS = 5", "CREATE_ATTEMPTS = 1"),
 ("env name unchecked", DF, '    found += [f"--env {name.partition(\'=\')[0]}: takes a variable NAME, never NAME=value" for name in request.env_names\n              if not _ENV_NAME.fullmatch(name)]\n', ""),
 ("sweep matches anywhere", DF, 'return re.fullmatch(rf"{re.escape(project)}-(?:{modes})-\\d{{2,}}-[a-z0-9]{{4}}", name) is not None', "return project in name"),
 ("sweep ignores failed ls", AF, '    except (Unreadable, CommandTimeout) as exc:\n        edge.out(f"fleet: cannot read the account: {exc}")\n        return 3\n', '    except (Unreadable, CommandTimeout) as exc:\n        edge.out(f"fleet: cannot read the account: {exc}")\n        return 0\n'),
 ("deadline tar skipped", AF, '        runtime.run(name, "bash", "-c", "tar -czf ~/out.tgz -C ~ out", timeout=120)', "        pass"),
 ("secret repr visible", AF, "value: str = field(repr=False)", "value: str = field()"),
 ("rc file ignored", FILES, 'rc = int(rc_file.read_text(encoding="utf-8").strip() or "-1") if rc_file.exists() else None', "rc = 0"),
 ("bad flag --no-progres", CLI, '"--no-progress"]', '"--no-progres"]'),
 ("bad flag --allow-net", CLI, '("--allow-network", host)', '("--allow-net", host)'),
 ("bad flag rm --purge", CLI, 'self._call("rm", "-f", box)', 'self._call("rm", "--purge", box)'),
 ("bad flag secret rm --yes", CLI, '"--sandbox", box, "--force")', '"--sandbox", box, "--yes")'),
 ("box script loses rc", DF, "; echo $? > $OUT/rc", ""),
 ("box script never marks done", DF, "touch $HOME/out.done", "true"),
 ("clone failure not fatal", DF, "|| echo clone-failed >> $OUT/fatal", ""),
 ("ls-remote: unreadable treated pushed", GIT, "        if not sha or tips is None:\n            return False\n", "        if not sha or tips is None:\n            return True\n"),
 ("no CREATE_NO_WINDOW", PROC, 'NO_WINDOW: int = getattr(subprocess, "CREATE_NO_WINDOW", 0)', "NO_WINDOW: int = 0"),
 ("missing exe raises", PROC, '    if tool is None:\n        return Done(127, "", f"{argv[0]}: not found")\n', '    tool = str(tool)\n'),
 ("no network reads aligned", ADR, '    if newest is None:\n        lines.append("could not read the newest release (no network or no gh): not reported as aligned")\n        return 3\n', ""),
 ("version mismatch ignored", ADR, 'if any(diff.values()) or report["version_behind"] or version != snapshot["version"]:\n        report["status"]', 'if any(diff.values()) or report["version_behind"]:\n        report["status"]'),
 ("behind ignored", ADR, 'report["version_behind"] = version_tuple(snapshot["version"]) < max(version_tuple(version), version_tuple(newest or ""))', 'report["version_behind"] = False'),
 ("missing verb not flagged", DD, "    missing: list[str] = sorted(gone)\n", "    missing: list[str] = []\n"),
 ("snapshot failure tolerated", ADR, '    if broken:\n        raise RuntimeError(f"`sbx --cloud <command> --help` failed for: {\', \'.join(broken)}")\n', ""),
 ("no NFKD in tokens", V, 'folded = unicodedata.normalize("NFKD", text.lower().translate(LOOKALIKES)).encode("ascii", "ignore").decode()', "folded = text.lower()"),
 ("hyphen compounds dropped", V, '    return re.sub(r"[^a-z0-9]+", "", folded)\n', "    return folded\n"),
 ("macOS home not checked", V, ' r"/users/\\w+",', ""),
 ("msys home not checked", V, ' r"/c/(?:users|development)\\b",', ""),
 ("URL pin check off", V, "if repo in ALLOWED_PAGES or PINNED.search(tail) or NUMBERED.search(tail):", "if True:"),
 ("deny-file ignored", V, 'if any(word in line for line in folded)]', 'if False]'),
 ("private label accepted anywhere", V, 'elif state != "untested-idea" and "://" not in source and UNPUBLISHED_LABEL not in source:', "elif False:"),
 ("TTL finding gone", CHK, 'Finding("ttl", _ttl_ok(config),', 'Finding("ttl", True,'),
 ("on-timeout finding gone", CHK, 'Finding("on-timeout", config.get("on_timeout") == "delete",', 'Finding("on-timeout", True,'),
 ("leftover-secrets always ok", CHK, 'Finding("leftover-secrets", not left, fixes)', 'Finding("leftover-secrets", True, fixes)'),
 ("quota: no figure reads free", CLI, '    if not isinstance(cpus, int):\n        raise Unreadable(f"{typed[\'name\']}: sbx ls --json reports no vCPU figure")\n    return BoxRow(str(typed["name"]).rpartition("/")[2], cpus)', '    return BoxRow(str(typed["name"]).rpartition("/")[2], cpus if isinstance(cpus, int) else 0)'),
 ("pushed always ok", CHK, 'Finding("pushed", source.on_remote(head, "origin"),', 'Finding("pushed", True,'),
 ("dirty tree ok", CHK, 'Finding("working-tree", not source.dirty(),', 'Finding("working-tree", True,'),
 ("gone verb no refusal", CHK, 'if report.get("missing_verbs"):', "if False:"),
 ("sbx timeout not caught in check", CHK, "    except (Unreadable, CommandTimeout) as exc:\n        anchor = anchor_for(str(exc)) or", "    except Unreadable as exc:\n        anchor = anchor_for(str(exc)) or"),
 ("--expect ignored", DJ, "if expect is not None and ran != expect:", "if False:"),
 ("JUnit close events dropped", JX, "        collect(cast(Iterator[tuple[str, ET.Element]], parser.read_events()))\n    except", "        pass\n    except"),
 ("JUnit NUL bypass", JX, 'if "\\x00" in text or "<!DOCTYPE" in text', 'if "<!DOCTYPE" in text'),
 ("Low env refusal echoes value", DF, 'f"--env {name.partition(\'=\')[0]}: takes a variable NAME', 'f"--env {name}: takes a variable NAME'),
 ("Low shard expect accepts zero", L + "sbx_shard.py", 'check.add_argument("--expect", type=_positive,', 'check.add_argument("--expect", type=int,'),
 ("Low sweep blocked by unrelated setting", F, "        if not args.sweep_only:\n            _settings(args, config)", "        if True:\n            _settings(args, config)"),
 ("overlap report removed", DJ, "    if overlap:\n", "    if False:\n"),
 ("token kept in remote", SCAN, 'return _CREDENTIAL.sub(r"\\1", done.out.strip())', "return done.out.strip()"),
 ("secret files not listed", SCAN, "names = {name for name in SECRET_NAMES if (root / name).is_file()}", "names = set()"),
 ("onboard loses config", ONB, "    text = add_missing_keys(text, config)\n    for name, body in", "    text = config_block(config)\n    for name, body in"),
 ("onboard loses notes", ONB, '        text = pattern.sub(lambda _match, value=region: value, text)\n', '        text = config_block(config) + region\n'),
]
EXTRA = [
 # review 3, H1: the account's own allow list
 ("R3H1 account list not counted", AF, "found += exposure(secrets, (*request.allow, *policy.allow), boxes)", "found += exposure(secrets, request.allow, boxes)"),
 ("R3H1 account wildcard not refused", AF, "found = _collisions(request, boxes, secrets) + open_account_hosts(policy.allow)", "found = _collisions(request, boxes, secrets)"),
 ("R3H1 fleet never reads the policy", AF, 'policy = edge.runtime.account_policy() if denied else AccountPolicy("")', 'policy = AccountPolicy("deny-all")'),
 ("R3H1 check: list not counted", CHK, "exposure(rows, (*allow, *policy.allow), boxes)", "exposure(rows, allow, boxes)"),
 ("R3H1 check: wildcard not refused", CHK, 'policy.mode == "deny-all" and not open_hosts', 'policy.mode == "deny-all"'),
 ("R3H1 bare wildcard covers nothing", FLEET_D, "return not base or host == base", "return host == base"),
 ("R3H1 missing list reads empty", CLI, 'if not isinstance(allow, list) or not all(isinstance(host, str) for host in cast(Sequence[Any], allow)):', "allow = allow or []\n        if False:"),
 # review 3, H2: a file name is not the rules
 ("R3H2 no escape", ONB, 'return "".join(char if char.isprintable() and char not in "`|<>\\\\{}" else f"\\\\u{ord(char):04x}" for char in str(value))', "return str(value)"),
 ("R3H2 detection not escaped", ONB, "{_cell(shown) if shown not in", "{shown if shown not in"),
 ("R3H2 why not escaped", ONB, "{_cell(r['why'])}", "{r['why']}"),
 ("R3H2 a pipe stays", ONB, 'char not in "`|<>\\\\{}"', 'char not in "`<>\\\\{}"'),
 ("R3H2 a second block reads", ADO, "if text.count(FENCE) > 1:", "if False:"),
 ("R3H2 a block anywhere on a line", ADO, '_OPEN = re.compile(rf"^{FENCE}[ \\t]*\\r?\\n", re.MULTILINE)', '_OPEN = re.compile(rf"{FENCE}[ \\t]*\\r?\\n")'),
 ("R3H2 a block above the tables", ADO, "if text.find(REGION_END, opened.end()) != -1:", "if False:"),
 ("R3H2 a block that never closes", ADO, "    if not closed:\n        raise ValueError", "    if False:\n        raise ValueError"),
 ("R3H2 any fence closes it", ADO, '_CLOSE = re.compile(r"^```[ \\t]*\\r?$", re.MULTILINE)', '_CLOSE = re.compile(r"```")'),
 ("R3H2 splitlines is back", ADO, 'text[span[0]:span[1]].split("\\n")', "text[span[0]:span[1]].splitlines()"),
 ("R3H2 a line break is written", ADO, 'if any("\\n" in value or "\\r" in value for value in config.values()):', "if False:"),
 ("R3H2 rerun parses after tree data", ONB, "    text = add_missing_keys(text, config)\n    for name, body in", "    for name, body in"),
 ("R3H2 trust reads a refused file", TRUST_E, 'print(json.dumps(untrusted("adoption-file-refused", why=str(exc)).to_json(), indent=2))\n        return 1', "config = {}"),
 # fix 6: pins agree, a repeat is per box, a fan-out without $SHARD still refuses
 ("F6 pins may disagree", V, "if len(shas) > 1 and not set(shas) <= SECOND_PINS.get(repo, frozenset())]", "if False]"),
 ("F6 a named second pin lets any through", V, "not set(shas) <= SECOND_PINS.get(repo, frozenset())]", "repo not in SECOND_PINS]"),
 ("F6 templates go unread", V, 'if path.suffix in (".md", ".yml"):  # where evidence', 'if path.suffix == ".md":  # where evidence'),
 ("F6 a fan-out passes as repeats", F, "args.max_usd, len(args.commands) > 1)", "args.max_usd, True)"),
 ("F6 repeats dedupe as shards", FLEET_D, 'command if "SHARD" in command else result.index', "command"),
 ("F6 shards add up", FLEET_D, 'command if "SHARD" in command else result.index', "result.index"),
 # review 3, H3: a create that may finish
 ("R3H3 delete self.late.set()", AF, "            self.late.set()\n            self.unsure.add(name)\n", "            self.unsure.add(name)\n"),
 ("R3H3 unsure forgotten", AF, "            self.late.set()\n            self.unsure.add(name)\n", "            self.late.set()\n"),
 ("R3H3 only a timeout counts", AF, "if created is None or created.rc != 0:  # a killed", "if created is None:  # a killed"),
 ("R3H3 a seen box stays unsure", AF, "                    self.unsure.discard(name)\n", ""),
 ("R3H3 possibly not printed", AF, "    for name in possibly:\n        edge.out(_possibly_line(name, request.project))\n", ""),
 ("R3H3 possibly not stored", AF, '"possibly_left_behind": possibly,', '"possibly_left_behind": [],'),
 ("R3H3 every box was removed", AF, '"fleet: stopped; every box was removed" if not (left or possibly) else', '"fleet: stopped; every box was removed" if not left else'),
 # review 3, mediums and lows
 ("R3M1 fork trusted", TR, '    if repo_id(facts.head_repo) != repo_id(facts.base_repo):\n        return "fork-head"', '    if False:\n        return "fork-head"'),
 ("R3M3 a skip counts as run", FILES, "for case in cases if case.outcome is not Outcome.SKIPPED))", "for case in cases))"),
 ("R3M3 shard counts a skip", DJ, "for case in cases if case.outcome is not Outcome.SKIPPED})", "for case in cases})"),
 ("R3M3 skip not printed", AF, 'skipped = f", {result.skipped} skipped" if result.skipped else ""', 'skipped = ""'),
 ("R3M4 relative PATH counts", PROC, "if os.path.isabs(item)]", "]"),
 ("R3M4 bare name reaches the OS", PROC, "subprocess.run([tool, *argv[1:]],", "subprocess.run(list(argv),"),
 ("R3M8 real path dropped", FILES, "for candidate in (Path(os.path.abspath(path)), path.resolve()):", "for candidate in (Path(os.path.abspath(path)),):"),
 ("R3M8 written path dropped", FILES, "for candidate in (Path(os.path.abspath(path)), path.resolve()):", "for candidate in (path.resolve(),):"),
 ("R3M8 more than expected passes", FLEET_D, '    if ran == expected:\n        return ""\n', '    if ran >= expected:\n        return ""\n'),
 ("R4M4 no case cap", L + "sbxlib/adapters/junit_xml.py", "if counted + len(cases) >= limit:", "if False:"),
 ("R4M4 cap per file only", FILES, "read_file(xml, box, MAX_CASES, len(cases))", "read_file(xml, box, MAX_CASES)"),
 ("R4L1 unknown encoding escapes", L + "sbxlib/adapters/junit_xml.py", "except (ET.ParseError, LookupError) as exc:", "except ET.ParseError as exc:"),
 ("R4M3 ##[ reaches the runner", FLEET_D, '_V1_COMMAND.sub("#[", _CONTROL.sub(" ", text).strip()[:200])', '_CONTROL.sub(" ", text).strip()[:200]'),
 ("F7b a skip is called lost", FLEET_D, "max(0, expected - ran - skipped)", "max(0, expected - ran)"),
 ("F7b lost not stored", AF, '"lost": counts(results, request.expect_tests, request.commands)[2]', '"lost": 0'),
 ("R3L1 stagger nan", FLEET_D, "if not 0 <= request.stagger <= MAX_STAGGER_S:", "if request.stagger < 0:"),
 ("R4L3 stagger unbounded", FLEET_D, "if not 0 <= request.stagger <= MAX_STAGGER_S:", 'if not 0 <= request.stagger < float("inf"):'),
 ("R4L3 unwritable verdict escapes", AF, "    except OSError as exc:\n        edge.out(f\"fleet: could not write verdict.json", "    except ZeroDivisionError as exc:\n        edge.out(f\"fleet: could not write verdict.json"),
 ("R4L3 unwritable verdict reads green", AF, "        code = code or 1\n", ""),
 ("R3L2 dash template", FLEET_D, r"""|(?!-)[\w.-]+(?:/""", r"""|[\w.-]+(?:/"""),
 ("R3L3 check blind to env", F, 'for line in (*_refused(config, request, PROFILES[trust.level]), *filter(None, [_env_refusal(args)]))]', "for line in _refused(config, request, PROFILES[trust.level])]"),
 ("R3L4 one scheme", SCAN, '_CREDENTIAL = re.compile(r"^([a-z][a-z0-9+.-]*://)(?!git@)[^/]*@", re.IGNORECASE)', '_CREDENTIAL = re.compile(r"^(https?://)[^/@]+@")'),
 ("R3L5 no rc reads as never ran", AF, 'missing = "" if read.rc is not None else "the box returned no exit code"', 'missing = ""'),
 ("R3L6 ceiling rounded", FLEET_D, "ttl_minutes / 60, 6)", "ttl_minutes / 60, 2)"),
 ("R3L7 empty plan", L + "sbx_shard.py", '    if not shards:\n        raise ValueError("the plan has no shards")\n', ""),
 ("R3L8 snapshot unchecked", L + "sbx_drift.py", "and version and is_valid_snapshot(data) else None", "and version else None"),
 ("R3L8 only behind counts", L + "sbx_drift.py", "apart = version_tuple(version) != version_tuple(newest)", "apart = version_tuple(version) < version_tuple(newest)"),
 ("R3L10 SIGHUP unhandled", F, '("SIGTERM", "SIGBREAK", "SIGHUP")', '("SIGTERM", "SIGBREAK")'),
 ("R3L10 a closed terminal raises", F, "with contextlib.suppress(OSError):  # a closed terminal", "with contextlib.suppress(ZeroDivisionError):  # a closed terminal"),
 ("visibility: unknown skips the token check", SBX_CHECK, 'det.get("repo_visibility") == "private":', 'det.get("repo_visibility") != "public":'),
 # round 5: the fork pull request recipe, and the file onboarding writes
 ("CI reads the rules from the pull request", T5, "ref: ${{ github.event.repository.default_branch }}", "ref: ${{ github.event.pull_request.head.sha }}"),
 ("CI checks out with no ref check", T5, "          ref: ${{ github.event.repository.default_branch }}\n          persist-credentials: false\n", "          persist-credentials: false\n"),
 ("CI keeps a credential", T5, "          fetch-depth: 0\n          persist-credentials: false\n", "          fetch-depth: 0\n"),
 ("CI token for a stranger", T5, "${{ needs.decide.outputs.level == 'trusted' && secrets.SBX_TRUST_TOKEN || '' }}", "${{ secrets.SBX_TRUST_TOKEN }}"),
 ("CI one environment", T5, "${{ needs.decide.outputs.level == 'trusted' && 'sbx-trusted' || 'sbx-external' }}", "sbx-trusted"),
 ("CI sweep skipped on failure", T5, "      - name: Sweep this pull request's boxes\n        if: always()\n", "      - name: Sweep this pull request's boxes\n"),
 ("CI expression in a shell", T5, '--sha "$SHA" --pr "$PR" --project', '--sha "${{ github.event.pull_request.head.sha }}" --pr "$PR" --project'),
 ("CI a failed check stops the job", T5, "          if python3 .sandbox-runbook/skills/sandbox-runbook/scripts/sbx_trust.py check --repo \"$GITHUB_REPOSITORY\" --pr \"$PR\" --sha \"$SHA\" --config docs/sbx.md; then\n            level=trusted\n          fi\n", "          python3 .sandbox-runbook/skills/sandbox-runbook/scripts/sbx_trust.py check --repo \"$GITHUB_REPOSITORY\" --pr \"$PR\" --sha \"$SHA\" --config docs/sbx.md\n          level=trusted\n"),
 ("R4M2 decide runs an unchecked skill", T5, '          git merge-base --is-ancestor "$SBX_SKILL_SHA" origin/HEAD || [ -n "$(git tag --points-at "$SBX_SKILL_SHA")" ]\n      - name: Decide', "          true\n      - name: Decide"),
 ("R4M2 the fleet runs an unchecked skill", T5, '          git merge-base --is-ancestor "$SBX_SKILL_SHA" origin/HEAD || [ -n "$(git tag --points-at "$SBX_SKILL_SHA")" ]\n      - name: Install sbx', "          true\n      - name: Install sbx"),
 ("R4M2 any commit is its own ancestor", T5, '"$SBX_SKILL_SHA" origin/HEAD ||', '"$SBX_SKILL_SHA" "$SBX_SKILL_SHA" ||'),
 ("R4M2 shallow skill checkout", T5, "          path: .sandbox-runbook\n          fetch-depth: 0\n", "          path: .sandbox-runbook\n"),
 ("R4H2 no branch rule in the template", T5, "#   GitHub matches that rule against GITHUB_REF", "#   GitHub matches it against nothing"),
 ("R4H2 any branch may deploy", T5, "Selected branches and tags, your default branch only.", "No restriction."),
 ("onboard: unknown takes the token", ONB, 'return det["repo_visibility"] != "private"', 'return det["repo_visibility"] == "public"'),
 ("onboard: strangers get five boxes", ONB, '"boxes": "5" if "$SHARD" in command and not takes_strangers else "1"', '"boxes": "5" if "$SHARD" in command else "1"'),
 ("onboard: network left undecided", ONB, '"network_policy": "deny-all" if takes_strangers else "unknown"', '"network_policy": "unknown"'),
 # the field log of 2026-11-05
 ("F11 no repository runs anyway", F, "found = [*_refused(config, request, profile),", "found = [*refusals(request, profile),"),
 ("F11 sbx_check does not see it", F, "for line in (*_refused(config, request, PROFILES[trust.level]),", "for line in (*refusals(request, PROFILES[trust.level]),"),
 ("F11 the fix is buried", F, "return [problem] if problem else refusals(request, profile)", "return [*refusals(request, profile), *filter(None, [problem])]"),
 ("F11 any own_work value refuses", ADO, 'if config.get("own_work") != "trusted" or repo_id(config.get("repo", "")):', 'if repo_id(config.get("repo", "")):'),
 ("F11 an unreadable repository passes", ADO, 'or repo_id(config.get("repo", "")):\n        return ""', 'or config.get("repo", ""):\n        return ""'),
 ("F7 a short count stays green", AF, "    code = 1 if short and code == 0 else code\n", ""),
 ("F7 a short count is no reason", FLEET_D, "    if ran == expected:\n", "    if True:\n"),
 ("F7 a dead box reads complete", FLEET_D, "left = [str(result.index) for result in results if result.rc is None or result.fatal]", "left: list[str] = []"),
 ("F7 no JUnit passes an expected count", FLEET_D, "if request.expect_tests is not None and not request.require_junit:", "if False:"),
 ("F7 a wrong count reads complete", FLEET_D, 'if tests == expected else (False, f"INCOMPLETE: {count}")', 'if True else (False, "")'),
 ("F9 no ceiling", FLEET_D, "if request.max_usd is not None and worst > request.max_usd:", "if False:"),
 ("F9 nan is a ceiling", F, 'if not 0 < value < float("inf"):', "if False:"),
 ("F9 config ceiling ignored", F, '(*BUILTIN, "boxes", "commands", "max_usd")', '(*BUILTIN, "boxes", "commands")'),
 ("F18 no live read", AF, "(read if self.profile.output is OutputPolicy.EVERYTHING else \"\")", '""'),
 ("F18 a live read of an untrusted box", AF, '(read if self.profile.output is OutputPolicy.EVERYTHING else "")', "read"),
 ("F21 label count unchecked", FLEET_D, "if request.labels and len(request.labels) != request.total:", "if False:"),
 ("F22 no n/a", AF, 'tests = f"{result.tests} tests" if request.require_junit else "tests n/a"', 'tests = f"{result.tests} tests"'),
 ("F2 --config ignored by sbx_check", SBX_CHECK, "path = args.config or args.root / args.file", "path = args.root / args.file"),
 ("F2 commands do not count boxes", CHK, '**({"boxes": str(len(commands))} if len(commands) > 1 else {})', "**{}"),
 ("F1 --config still writes in the project", L + "sbx_onboard.py", "path.with_name(Path(RECIPE).name) if outside else root / RECIPE", "root / RECIPE"),
 ("F1 --file may leave the project", L + "sbx_onboard.py", "if not outside and not path.is_relative_to(root):", "if False:"),
 # review 2, H1: the guard fires on real paths
 ("H1 fleet guard path is garbage", F, "protected_paths(args.config or Path(ADOPTION_FILE), args.template)", '("garbage/path",)'),
 ("H1 fleet guard path is the raw string", F, "protected_paths(args.config or Path(ADOPTION_FILE), args.template)", "(str(args.config or ADOPTION_FILE),)"),
 ("H1 trust CLI guard path is garbage", TRUST_E, 'protected_paths(args.config, config.get("template", ""))', '("garbage/path",)'),
 ("H1 rename ignored", TR, "touches((*facts.files, *facts.renamed_from), protected)", "touches(facts.files, protected)"),
 ("H1 gh drops the old name", GH, 'str(row.get("previous_filename") or "")', '""'),
 ("H1 case kept", TR, '.strip("/").casefold()', '.strip("/")'),
 ("H1 parent folder ignored", TR, 'name == path or path.startswith(f"{name}/") or name', "name == path or name"),
 ("H1 kit contents ignored", TR, ' or name.startswith(f"{path}/")', ""),
 ("H1 kit not protected", FILES, 'kit = _repo_paths(Path(template)) if template.startswith((".", "/")) else ()', "kit = ()"),
 ("H1 no repository still protected", FILES, "return (ADOPTION_FILE, *paths, *kit) if paths else ()", "return (ADOPTION_FILE, *paths, *kit)"),
 ("H1 not-in-repo passes", TR, '    if not protected:\n        return "adoption-file-not-in-repo"\n', ""),
 # review 2, H2: an account secret a box could use
 ("H2 exposure check off", AF, "    if profile.secrets is SecretPolicy.NONE:\n        found += exposure(secrets, (*request.allow, *policy.allow), boxes)\n", ""),
 ("H2 unknown hosts read as unreachable", FLEET_D, "return (not hosts or any(", "return (any("),
 ("H2 scope ignored", FLEET_D, "if not _one_box(scope, live) and reaches(", "if reaches("),
 ("H2 a row with no scope is not global", FLEET_D, "return scope in live or _FLEET_SCOPE", 'return scope == "" or scope in live or _FLEET_SCOPE'),
 ("R4M1 only global is global", FLEET_D, "if not _one_box(scope, live) and", 'if scope in ("global", "") and'),
 ("R4M1 any sandbox shape is one box", FLEET_D, "return scope in live or _FLEET_SCOPE.fullmatch(scope) is not None", 'return re.fullmatch(r"[a-z0-9][a-z0-9-]+", scope) is not None'),
 ("R4M1 live boxes not read", AF, "allow, frozenset(row.name for row in boxes))", "allow)"),
 ("R4M1 a wildcard host is placed", FLEET_D, "(not hosts or any(_PLAIN_HOST.fullmatch(host) is None for host in hosts)", "(not hosts"),
 ("H2 wildcard ignored", FLEET_D, ' or (pattern.startswith("*") and host.endswith(f".{base}"))', ""),
 ("H2 default allow not counted", FLEET_D, "for pattern in (*DEFAULT_ALLOW, *allow) for host", "for pattern in allow for host"),
 ("H2 custom hosts dropped", FLEET_D, "reaches(hosts or SERVICE_HOSTS.get(name, ()), allow)", "reaches(SERVICE_HOSTS.get(name, ()), allow)"),
 ("H2 service table not read", FLEET_D, "reaches(hosts or SERVICE_HOSTS.get(name, ()), allow)", "reaches(hosts, allow)"),
 ("H2 hosts not parsed", CLI, 'tuple(str(host) for host in cast(Sequence[Any], hosts)) if isinstance(hosts, list) else ()', "()"),
 ("H2 custom_secrets ignored", CLI, 'custom = typed.get("custom_secrets")', "custom = None"),
 ("H2 env-only ignored", CLI, 'if typed.get("env_only_count") else []', "if False else []"),
 ("H2 check: global-secrets always ok", CHK, 'return [Finding("global-secrets", not exposed, "; ".join(exposed)),\n            Finding("network-default", policy', 'return [Finding("global-secrets", True, "; ".join(exposed)),\n            Finding("network-default", policy'),
 ("H2 check: global-secrets never blocks", CHK, 'return [Finding("global-secrets", not exposed, "; ".join(exposed)),\n            Finding("network-default", policy', 'return [Finding("global-secrets", not exposed, "; ".join(exposed), Severity.WARN),\n            Finding("network-default", policy'),
 ("H2 check: network default always ok", CHK, 'Finding("network-default", policy.mode == "deny-all" and not open_hosts,', 'Finding("network-default", True,'),
 # review 2, H3: trust is bound to the project's repository
 ("H3 own work ignores the repository", ADO, 'rule = repo_rule(config.get("repo", ""), repo)', 'rule = ""'),
 ("H3 pull check ignores the flag", AT, "bound = repo_rule(self._rules.repo, repo)", 'bound = ""'),
 ("H3 decide ignores the base repository", TR, "bound = repo_rule(rules.repo, facts.base_repo)", 'bound = ""'),
 ("H3 no declared repository passes", TR, '    if not repo_id(project):\n        return "repo-not-declared"\n', ""),
 ("H3 repository case kept", TR, "clean = text.strip().lower()", "clean = text.strip()"),
 ("H3 rules drop the repository", ADO, 'frozenset(words(config.get("trust_logins", ""))), config.get("repo", ""))', 'frozenset(words(config.get("trust_logins", ""))), "")'),
 ("H3 onboard writes no repository", ONB, 'repo_id(str(det.get("remote", "")))', '""'),
 # review 2, mediums
 ("M1 archive size off", FILES, "        if self._read > self._limit:\n", "        if False:\n"),
 ("M1 disk size off", FILES, "if path.stat().st_size > MAX_ARCHIVE_BYTES:", "if False:"),
 ("M1 member count off", FILES, "if count > MAX_MEMBERS:", "if False:"),
 ("M1 memory error escapes", FILES, "UnreadableJunit, MemoryError, zlib.error) as exc:", "UnreadableJunit, zlib.error) as exc:"),
 ("M2 failed cases not red", FLEET_D, "    if result.failed:\n", "    if False:\n"),
 ("M2 all skipped not red", FLEET_D, "if result.skipped == result.tests else []", "if False else []"),
 ("M2 no-junit does not waive", FLEET_D, "    if not require_junit:\n        return []\n", ""),
 ("M2 failures not counted", FILES, 'outcomes[Outcome.FAILED] + outcomes[Outcome.ERROR],', "0,"),
 ("M3 any own_work value trusted", ADO, 'if config.get("own_work") != "trusted":', 'if not config.get("own_work"):'),
 ("M5 left behind exits zero", AF, "    code = 1 if left and code == 0 else code  # a box or a credential left behind is never green\n", ""),
 ("M5 secret said to bill", AF, 'if name.startswith("secret "):', "if False:"),
 ("M5 sweep forgets secrets", AF, '        left += [f"secret {row.name} of {row.scope}" for row in secrets if is_fleet_box(row.scope, project)]\n', ""),
 ("M6 unreadable snapshot raises", L + "sbx_drift.py", "except (ValueError, KeyError, TypeError):\n        return None\n    return version if", "except ZeroDivisionError:\n        return None\n    return version if"),
 ("M6 hung gh raises", GH, "    except CommandTimeout:\n        return None\n", "    except ZeroDivisionError:\n        return None\n"),
 ("M7 fatal not scrubbed", AF, "text = scrub(fatal or read.fatal or missing, self.hidden)", "text = fatal or read.fatal or missing"),
 ("M8 box exception escapes", AF, '        except Exception as exc:  # a full disk or a bad archive is this box\'s red: it must not skip the final proof\n            return BoxResult(index, fatal=scrub(f"failed on the host: {type(exc).__name__}: {exc}", self.hidden))\n', ""),
 ("M8 a signal skips the proof", AF, "    except KeyboardInterrupt:\n        run.stop.set()\n        return run.confirm_gone()\n\n\ndef _left_line", "    except ZeroDivisionError:\n        return []\n\n\ndef _left_line"),
 ("M8 git timeout escapes", F, "    except CommandTimeout as exc:  # a credential prompt", "    except ZeroDivisionError as exc:  # a credential prompt"),
 ("M10 partial refusal reads green", FLEET_D, "return 0 if len(ran) == total else 3", "return 0"),
 ("M10 partial refusal hides a failure", FLEET_D, "if any(_problem(result, total, require_junit) for result in ran):", "if False:"),
 ("M11 fleet plan always ok", CHK, 'Finding("fleet-plan", not refused,', 'Finding("fleet-plan", True,'),
 ("M11 sbx_check asks no plan", SBX_CHECK, """lambda: planned_refusals(config, f"https://{repo_id(config.get('repo', ''))}.git", commands), commands)]""", "lambda: [], commands)]"),
 ("L1 repo not quoted", FLEET_D, '"REPO": shlex.quote(request.repo)', '"REPO": request.repo'),
 ("L1 query string allowed", FLEET_D, r"""r"https://[^\s/@]+/[^\s?#@]+")""", r"""r"https://[^\s/@]+/\S+")"""),
 ("L2 no box count check", FLEET_D, '    if request.total < 1:\n        found.append("boxes must be at least 1")\n', ""),
 ("L2 negative stagger", FLEET_D, '    if not 0 <= request.stagger <= MAX_STAGGER_S:  # nan and 1e308 fail too: `time.sleep` would raise past the final proof\n        found.append(f"stagger {request.stagger}: must be a number of seconds, from 0 to {MAX_STAGGER_S}")\n', ""),
 ("L3 empty plan accepted", L + "sbx_shard.py", "    if not cases:\n        raise ValueError", "    if False:\n        raise ValueError"),
 ("L5 child keeps the token", F, 'return {"GH_TOKEN", args.secret_env} - set(args.env)', "return set()"),
 ("L10 local target runs in the cloud", F, 'if config.get("target", "cloud") != "cloud":', "if False:"),
 ("trust: no-rules grants", L + "sbxlib/domain/trust.py", '        return "no-rules"', '        return ""'),
 ("trust: sha change ignored", L + "sbxlib/domain/trust.py", '    if facts.head_sha != sha:\n        return "sha-changed"\n', ""),
 ("trust: foreign commit ignored", L + "sbxlib/domain/trust.py", "    if foreign:\n", "    if False:\n"),
 ("trust: adoption edit ignored", TR, 'return "adoption-file-changed" if touches((*facts.files, *facts.renamed_from), protected) else ""', 'return ""'),
 ("trust: read role counts", L + "sbxlib/domain/trust.py", 'TRUSTABLE_ROLES = frozenset({"admin", "maintain", "write"})', 'TRUSTABLE_ROLES = frozenset({"admin", "maintain", "write", "read"})'),
 ("trust: host error grants", AT, 'return untrusted(f"host-error:{exc.status}", **evidence, guide=GUIDE)', 'return TrustVerdict(untrusted("x").level.__class__("trusted"), "x", evidence)'),
 ("profile: untrusted takes secrets", L + "sbxlib/domain/fleet.py", "if profile.secrets is SecretPolicy.NONE and (secrets or request.clone == \"token\"):", "if False:"),
 ("profile: box cap off", L + "sbxlib/domain/fleet.py", "if profile.max_boxes is not None and request.total > profile.max_boxes:", "if False:"),
 ("fleet: collision check off", AF, "    found = _collisions(request, boxes, secrets) + open_account_hosts(policy.allow)\n", "    found = open_account_hosts(policy.allow)\n"),
 ("fleet: final check off", AF, "    left = _settle(run)\n", "    left: list[str] = []\n"),
 ("shard: hash for measured", DS, "    measured = sorted((u for u in units if u in weights and u not in alone), key=lambda u: (-weights[u], u))", "    measured = sorted((u for u in units if u in weights and u not in alone))"),
 ("shard: no own job", DS, 'alone = {u for u in units if u in own_job or (ceiling is not None and weights.get(u, 0.0) > ceiling)}', "alone = {u for u in units if u in own_job}"),
 ("files: logs come back", FILES, "if policy is OutputPolicy.EVERYTHING or _allowed(member):", "if True:"),
 # round 8: adapter list JSON branches, transcript scoring, validator, live contract, version manifest checker
 ("ls array shape rejected", CLI, '        if not isinstance(rows, list):\n            raise Unreadable("sbx ls --json has an unknown shape")', '        if isinstance(rows, list):\n            raise Unreadable("sbx ls --json has an unknown shape")'),
 ("ls wrapped sandboxes shape ignored", CLI, 'if isinstance(wrapped, list):\n                rows = cast(list[Any], wrapped)', 'if False:\n                rows = cast(list[Any], wrapped)'),
 ("ls unknown shape reads as empty", CLI, '        if not isinstance(rows, list):\n            raise Unreadable("sbx ls --json has an unknown shape")', '        if not isinstance(rows, list):\n            rows = []'),
 ("transcript ordered commands not checked", L + "eval_scenarios.py", '        found = next((index for index in range(cursor, len(transcript)) if expected in transcript[index]), None)', '        found = next((index for index in range(len(transcript)) if expected in transcript[index]), None)'),
 ("transcript forbid list ignored", L + "eval_scenarios.py", 'problems.extend(f"forbidden: {item}" for item in scenario["forbid"] if item.lower() in joined)', 'problems.extend([])'),
 ("transcript missing command accepted", L + "eval_scenarios.py", '            problems.append(f"missing or out of order: {expected}")', '            pass'),
 ("validator compatibility pin missing accepted", V, 'if not fields.get("compatibility") or "sbx" not in fields.get("compatibility", "").lower():', 'if False:'),
 ("validator undated current/latest accepted", V, '        if current_word and not literal_reference:', '        if False and current_word and not literal_reference:'),
 ("validator routing description unchecked", V, '    if WORKFLOW_WORDS.search(description):', '    if False:'),
 ("live contract drops --app-name", "tests/test_contract.py", '[argv[0], "--app-name", "sbx-skill-contract", *argv[1:]]', '[argv[0], *argv[1:]]'),
 ("manifest plugin list unchecked", "scripts/check_versions.py", '_marketplaces(root, problems, "ffroliva-skills")', 'pass'),
]
SNAP = None


def run(item):
    label, file, old, new = item
    with tempfile.TemporaryDirectory(prefix="mut", ignore_cleanup_errors=True) as t:
        dst = Path(t) / "r"
        shutil.copytree(SNAP, dst)
        p = dst / file
        src = p.read_text(encoding="utf-8")
        if old not in src:
            return ("NOT-APPLIED", label, file)
        p.write_text(src.replace(old, new, 1), encoding="utf-8", newline="\n")
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        try:
            r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-f", "-s", "tests"], cwd=dst, capture_output=True, text=True, timeout=280, env=env, encoding="utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            return ("killed(timeout)", label, "")
        names = [line.split()[1] for line in r.stderr.splitlines() if line.startswith(("FAIL:", "ERROR:"))][:2]
        return ("SURVIVED" if r.returncode == 0 else "killed", label, " ".join(names))


def failures(res):
    """What fails the run: a survivor leaves a guard untested, and a stale anchor tests nothing, so neither passes silently."""
    return [f"{st} {label}" for st, label, _ in res if st in ("SURVIVED", "NOT-APPLIED")]


if __name__ == "__main__":
    SNAP = tempfile.mkdtemp(prefix="snap")
    shutil.rmtree(SNAP)
    # what git would not publish: a tool's cache in the tree reads as content once .git is gone
    shutil.copytree(BASE, SNAP, ignore=shutil.ignore_patterns(".git", "__pycache__", ".ruff_cache", ".pytest_cache", ".serena"))
    control = run(("control", F, "", ""))
    if control[0] != "SURVIVED":  # a suite already red would count every mutant as killed
        print(f"CONTROL RED, no mutant counts: {control[2]}")
        sys.exit(2)
    print("control: the unmutated suite passes")
    which = M + EXTRA if len(sys.argv) < 2 else [m for m in M + EXTRA if sys.argv[1] in m[0]]
    with cf.ThreadPoolExecutor(5) as pool:
        res = list(pool.map(run, which))
    for i, (st, label, info) in enumerate(res):
        print(f"{'R' if i < len(M) else 'X'} {st:16} {label} | {info[:110]}")
    review = res[: len(M)] if len(which) == len(M + EXTRA) else res
    from collections import Counter
    print("REVIEW", Counter(r[0].split("(")[0] for r in review))
    print("EXTRA", Counter(r[0].split("(")[0] for r in res[len(M):]))
    for line in failures(res):
        print("FAILS THE RUN:", line)
    sys.exit(1 if failures(res) else 0)
