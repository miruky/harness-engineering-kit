# Harness workflow

## Inspect specifications and changed inputs

```sh
python3 kit.py inspect
python3 kit.py impact
```

The untouched example has pending reviews and is expected to return a nonzero status. This is a truthful initial state. `demo` shows the whole lifecycle in a temporary project without modifying the checkout.

## Document metadata

Markdown documents use YAML front matter with `id`, `kind`, `depends_on`, and optional `artifacts`. Supported document kinds are `requirement`, `basic`, and `detail`. Artifacts have a project-relative `path`, a role (`implementation`, `test`, or `configuration`), and optional `verifies` requirement IDs for test artifacts.

The supplied documents are complete examples. Metadata has strict duplicate-key, alias, type and path checks. Unknown dependencies, cycles, reversed document levels, duplicate artifact owners, missing artifacts and unregistered managed files fail. An implemented requirement needs a registered test; a planned requirement needs explicit `planned_tests` and is not represented as implemented.

## Red, Green and review

```sh
python3 kit.py tdd red --change CHG-EXAMPLE
```

The initial example contains a real failing assertion. Change only `project/app/result.json` so `complete` is true, keeping the title unchanged. Then:

```sh
python3 kit.py tdd green --change CHG-EXAMPLE
python3 kit.py review DETAIL-RESULT --change CHG-EXAMPLE --reason "Checked both assertions and confirmed the implementation preserves the agreed title."
python3 kit.py review BASIC-RESULT --change CHG-EXAMPLE --reason "Checked the worker and independent verification responsibilities against the implementation."
python3 kit.py review REQ-RESULT --change CHG-EXAMPLE --reason "Confirmed the required result and unchanged title using the same two passing assertions."
python3 kit.py inspect
```

Review each document and its changed inputs before supplying your own specific reason. Do not copy an example reason for unrelated work.

TDD uses a fresh JUnit report per invocation. Red requires actual assertion failures, not startup errors, syntax failures, skipped tests or an empty report. A failure needs an assertion-identifying type (for example `AssertionError`, `AssertionFailedError`, `ComparisonFailure`) or explicit assertion text when the type is absent. A runner that does not emit this evidence needs an adapter; a generic failed exit is insufficient.

Green requires the same declared test files, exact executed test identities, verifier configuration and all assertions passing. One Red record cannot be consumed twice. Later code/config/test changes invalidate Green and reviews. Test registration and hashes do not prove that test assertions fully cover a requirement; that remains part of review.

## Declared execution policy

```sh
python3 kit.py run read-result
python3 kit.py run push
```

The second action is deliberately denied by the example policy before execution. Unknown actions are also denied. The allowlist accepts named commands, not arbitrary appended arguments. Trusted programs/scripts may have additional capabilities; a wrapper cannot inspect and constrain every operation they perform.

## Optional Git/provider hooks

`python3 kit.py install-git-hooks` installs new project-local pre-commit/pre-push hooks only when existing hooks and `core.hooksPath` will not be replaced. The commit gate rejects unstaged/untracked work, checks the specification state, runs the verifier and verifies that the index did not change during the check. Push is denied by default; if an operator changes that policy, only the verified HEAD may be sent. Local hooks can be bypassed by their owner, so use server-side rules/credential restrictions when enforcement must survive a local bypass.

`python3 kit.py integration codex` or `integration claude` prints hook JSON for the selected checkout. Inspect it and merge it into the provider's project configuration without replacing existing hooks. Codex separately requires review/trust of the exact hook definition; generating this JSON does not grant trust or enable it. No global settings are changed.

The `PreToolUse` hook accepts only a literal command matching a registered permitted argv; compound commands, expansion and unsupported shell syntax are denied. It abstains from approval for an accepted command, preserving the provider's own checks. `Stop` requests continuation at most once, avoiding an endless refusal to stop. Provider tool coverage and hook failure behavior remain governed by the provider.

## Workbench

```sh
python3 kit.py view --serve
```

Open the reported loopback URL. The workbench is read-only and serves an explicit asset allowlist. It has search, node details, fit/reset controls and complete text tables. `view` without `--serve` exports an offline snapshot. A snapshot does not update by itself; export it again after changes.
