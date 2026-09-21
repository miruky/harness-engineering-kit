import json
from pathlib import Path
import shutil
import subprocess
import sys
from agentkit import engine
from agentkit.core import KitError, load_json, write_json, atomic_write, digest
from agentkit.integrations import install_git_hooks, hooks_configuration
from test_core import ProjectCase, REPO


class HarnessWorkflow(ProjectCase):
    def green(self):
        engine.tdd(self.root, "red", "CHG-TEST")
        value = load_json(self.root, "project/app/result.json")
        value["complete"] = True
        write_json(self.root, "project/app/result.json", value)
        return engine.tdd(self.root, "green", "CHG-TEST")
    def review_all(self):
        for key in engine.structure(self.root)["nodes"]:
            engine.acknowledge(self.root, key, "CHG-TEST", "Reviewed the exact contract, preserved title and the two successful assertions.")
    def test_initial_missing_reviews_are_not_success(self):
        report = engine.inspect(self.root)
        self.assertFalse(report["ok"])
        self.assertEqual(len(report["findings"]), 3)
    def test_real_red_green_review_and_drift_lifecycle(self):
        self.green()
        self.review_all()
        self.assertTrue(engine.inspect(self.root)["ok"])
        p = self.root / "project/app/result.json"
        p.write_text(p.read_text() + " ")
        self.assertFalse(engine.inspect(self.root)["ok"])
        self.assertCode("STALE_INPUTS", lambda: engine.current_green(self.root, "CHG-TEST", engine.structure(self.root)))
    def test_changed_test_cannot_reuse_red(self):
        engine.tdd(self.root, "red", "CHG-TEST")
        p = self.root / "project/checks/verify.py"
        p.write_text(p.read_text() + "\n# changed assertion contract\n")
        self.assertCode("STALE_INPUTS", lambda: engine.tdd(self.root, "green", "CHG-TEST"))
    def test_green_cannot_consume_the_same_red_twice(self):
        self.green()
        self.assertCode("STALE_EVIDENCE", lambda: engine.tdd(self.root, "green", "CHG-TEST"))
    def test_retained_report_is_required_and_cannot_be_replaced(self):
        self.green()
        evidence = load_json(self.root, ".agentkit/state/harness/green-CHG-TEST.json")
        path = evidence["result"]["junit"]["report_path"]
        self.assertTrue((self.root / path).is_file())
        atomic_write(self.root, path, b'<testsuite><testcase name="different"/></testsuite>')
        self.assertCode("STALE_INPUTS", lambda: engine.current_green(self.root, "CHG-TEST", engine.structure(self.root)))
    def test_startup_failure_is_not_red(self):
        p = self.root / "project/checks/verify.py"
        p.write_text("syntax error without a valid report!\n")
        self.assertCode("INVALID_EVIDENCE", lambda: engine.tdd(self.root, "red", "CHG-TEST"))
    def test_syntax_error_mislabeled_as_failure_is_not_red(self):
        p = self.root / "project/checks/verify.py"
        p.write_text("import sys\nfrom pathlib import Path\nPath(sys.argv[1]).write_text('<testsuite><testcase name=\"a\"><failure type=\"SyntaxError\">bad</failure></testcase></testsuite>')\nsys.exit(1)\n")
        self.assertCode("INVALID_EVIDENCE", lambda: engine.tdd(self.root, "red", "CHG-TEST"))
    def test_short_review_reason_is_rejected(self):
        with self.assertRaises(KitError):
            engine.acknowledge(self.root, "REQ-RESULT", "CHG-TEST", "ok")
    def test_duplicate_yaml_and_aliases_are_rejected(self):
        p = self.root / "project/docs/requirements.md"
        for header in ("id: A\nid: B\nkind: requirement\ndepends_on: []", "id: REQ-X\nkind: requirement\na: &a [x]\ndepends_on: *a"):
            p.write_text("---\n" + header + "\n---\n# Example\n")
            with self.assertRaises(KitError):
                engine.structure(self.root)
    def test_dangling_reference_and_cycle_are_rejected(self):
        p = self.root / "project/docs/design.md"
        original = p.read_text()
        p.write_text(original.replace("REQ-RESULT", "MISSING"))
        self.assertCode("DANGLING_REFERENCE", lambda: engine.structure(self.root))
        p.write_text(original.replace("[REQ-RESULT]", "[BASIC-RESULT]"))
        self.assertCode("CYCLE", lambda: engine.structure(self.root))
    def test_unregistered_file_is_detected(self):
        atomic_write(self.root, "project/app/new.any-language", b"changed product")
        self.assertCode("UNMANAGED_FILE", lambda: engine.structure(self.root))
    def test_execution_policy_denies_push_without_running_it(self):
        self.assertCode("POLICY_DENIED", lambda: engine.run_action(self.root, "push"))
        self.assertCode("POLICY_DENIED", lambda: engine.run_action(self.root, "arbitrary"))
        self.assertTrue(engine.run_action(self.root, "read-result")["ok"])
    def test_hook_does_not_approve_or_rewrite_commands(self):
        for cmd in ("git push", "python -c 'print(1)'; git push", "$(git push)", "git -c x=y push"):
            result = engine.hook(self.root, "PreToolUse", {"tool_name": "Bash", "tool_input": {"command": cmd}})
            self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(engine.hook(self.root, "PreToolUse", {})["hookSpecificOutput"]["permissionDecision"], "deny")
    def test_stop_hook_continues_at_most_once(self):
        self.assertEqual(engine.hook(self.root, "Stop", {})["decision"], "block")
        self.assertEqual(engine.hook(self.root, "Stop", {"stop_hook_active": True}), {})
    def test_hook_configuration_does_not_enable_trust(self):
        for provider in ("codex", "claude"):
            value = hooks_configuration(self.root, REPO / "kit.py", provider)
            self.assertEqual(set(value["hooks"]), {"SessionStart", "PreToolUse", "Stop"})
            self.assertNotIn("bypass", json.dumps(value))
    def test_real_git_pre_push_hook_blocks_local_remote_update(self):
        if not shutil.which("git"):
            self.skipTest("Git is unavailable")
        remote = Path(self.tmp.name) / "remote.git"
        def git(*args, cwd=None, check=True):
            return subprocess.run(["git", *args], cwd=cwd or self.root, capture_output=True, text=True, check=check)
        git("init", "--initial-branch=main")
        git("config", "user.name", "Kit Test")
        git("config", "user.email", "test@example.invalid")
        git("add", ".")
        git("commit", "-m", "Initial test fixture")
        git("init", "--bare", str(remote))
        git("remote", "add", "origin", str(remote))
        install_git_hooks(self.root, REPO / "kit.py")
        pushed = git("push", "origin", "HEAD:main", check=False)
        self.assertNotEqual(pushed.returncode, 0)
        self.assertIn("POLICY_DENIED", pushed.stderr)
        self.assertEqual(git("show-ref", cwd=remote, check=False).returncode, 1)
    def test_existing_git_hooks_are_never_overwritten(self):
        if not shutil.which("git"):
            self.skipTest("Git is unavailable")
        subprocess.run(["git", "init", str(self.root)], check=True, capture_output=True)
        p = self.root / ".git/hooks/pre-commit"
        p.write_text("existing")
        self.assertCode("ALREADY_EXISTS", lambda: install_git_hooks(self.root, REPO / "kit.py"))
        self.assertEqual(p.read_text(), "existing")
