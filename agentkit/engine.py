"""Trace specifications, enforce declared actions, and bind test evidence to inputs."""
from __future__ import annotations

from pathlib import Path
import re
import shlex
import shutil
import sys
import uuid

from .core import (KitError, require, object_fields, strings, number, identifier, load_json,
                   digest, file_hash, text, expand, snapshot, confined, write_json,
                   ProjectLock, state_path, now, check_fingerprint)
from .runtime import execute, validate_command, argv_for, verify

CONFIG = ".agentkit/harness.json"
LEVELS = {"requirement": 0, "basic": 1, "detail": 2}
ROLES = {"implementation", "test", "configuration"}


def configuration(root):
    cfg = load_json(root, CONFIG)
    object_fields(cfg, ["schema_version", "documents", "managed", "require_tdd", "test_files", "verifier", "policy"])
    require(type(cfg["schema_version"]) is int and cfg["schema_version"] == 1, "Unsupported schema version")
    strings(cfg["documents"], "documents", allow_empty=False)
    strings(cfg["managed"], "managed")
    strings(cfg["test_files"], "test_files")
    require(type(cfg["require_tdd"]) is bool, "require_tdd must be boolean")
    object_fields(cfg["verifier"], ["command", "format"])
    validate_command(cfg["verifier"]["command"])
    require(cfg["verifier"]["format"] in ("exit", "junit"), "Invalid verifier format")
    if cfg["require_tdd"]:
        require(cfg["verifier"]["format"] == "junit" and cfg["test_files"],
                "TDD requires JUnit and an explicit test-file inventory")
    policy = cfg["policy"]
    object_fields(policy, ["allowed_roles", "forbid_git_push", "commands"])
    strings(policy["allowed_roles"], "allowed roles")
    require(set(policy["allowed_roles"]) <= {"read", "check", "write"}, "Unknown action role")
    require(type(policy["forbid_git_push"]) is bool, "forbid_git_push must be boolean")
    require(isinstance(policy["commands"], dict), "commands must be an object")
    for key, action in policy["commands"].items():
        identifier(key, "action name")
        object_fields(action, ["role", "command"])
        require(action["role"] in {"read", "check", "write", "publish"}, "Invalid action role")
        validate_command(action["command"])
    return cfg


def markdown(root, path):
    from ._vendor import yaml
    body = text(root, path, limit=1024 * 1024)
    match = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", body, re.S)
    require(match is not None and len(match[1].encode()) <= 128 * 1024,
            f"Missing/oversized YAML front matter: {path}")

    class UniqueSafeLoader(yaml.SafeLoader):
        def construct_mapping(self, node, deep=False):
            result = {}
            for key_node, value_node in node.value:
                key = self.construct_object(key_node, deep=deep)
                require(isinstance(key, str), "YAML mapping keys must be strings")
                require(key not in result, f"Duplicate YAML key: {key}")
                require(key != "<<", "YAML merge keys are not supported")
                result[key] = self.construct_object(value_node, deep=deep)
            return result
    try:
        depth = 0
        for event in yaml.parse(match[1]):
            require(not isinstance(event, yaml.AliasEvent), "YAML aliases are refused")
            if isinstance(event, (yaml.MappingStartEvent, yaml.SequenceStartEvent)):
                depth += 1
            elif isinstance(event, (yaml.MappingEndEvent, yaml.SequenceEndEvent)):
                depth -= 1
            require(depth <= 32, "YAML nesting exceeds limit")
        meta = yaml.load(match[1], Loader=UniqueSafeLoader)
    except (yaml.YAMLError, RecursionError) as exc:
        raise KitError(f"Invalid YAML metadata: {path}") from exc
    title = re.search(r"^# (.+)$", body, re.M)
    return meta, body, title[1] if title else path


def structure(root):
    cfg = configuration(root)
    nodes, artifacts = {}, {}
    for path in expand(root, cfg["documents"]):
        require(path.endswith(".md"), "Document patterns must select Markdown files")
        meta, body, title = markdown(root, path)
        object_fields(meta, ["id", "kind", "depends_on"], ["artifacts", "lifecycle", "planned_tests"], path)
        node_id = identifier(meta["id"], "document id")
        require(node_id not in nodes, f"Duplicate document id: {node_id}", "DUPLICATE_ID")
        require(meta["kind"] in LEVELS, f"Invalid document kind: {node_id}")
        strings(meta["depends_on"], "depends_on")
        lifecycle = meta.get("lifecycle", "implemented")
        require(lifecycle in ("planned", "implemented"), "Invalid lifecycle")
        if meta["kind"] == "requirement" and lifecycle == "planned":
            strings(meta.get("planned_tests"), "planned_tests", allow_empty=False)
        nodes[node_id] = {"id": node_id, "path": path, "kind": meta["kind"], "title": title,
                          "depends_on": meta["depends_on"], "lifecycle": lifecycle,
                          "own_hash": file_hash(root, path)}
        require(isinstance(meta.get("artifacts", []), list), "artifacts must be a list")
        for artifact in meta.get("artifacts", []):
            object_fields(artifact, ["path", "role"], ["verifies"], "artifact")
            file_path = artifact["path"]
            require(artifact["role"] in ROLES, "Invalid artifact role")
            require(file_path not in artifacts, f"Duplicate artifact owner: {file_path}", "DUPLICATE_OWNER")
            verification = strings(artifact.get("verifies", []), "verifies")
            require(not verification or artifact["role"] == "test", "Only test artifacts may verify requirements")
            artifacts[file_path] = {**artifact, "verifies": verification, "owner": node_id,
                                    "sha256": file_hash(root, file_path)}
    require(nodes and len(nodes) <= 1000, "Expected 1–1000 document nodes")
    for node in nodes.values():
        for dep in node["depends_on"]:
            require(dep in nodes, f"Dangling dependency: {node['id']} -> {dep}", "DANGLING_REFERENCE")
            require(LEVELS[nodes[dep]["kind"]] <= LEVELS[node["kind"]], "Reversed specification level")
    order, remaining = [], set(nodes)
    while remaining:
        ready = sorted(n for n in remaining if not set(nodes[n]["depends_on"]) & remaining)
        require(ready, "Specification dependency cycle", "CYCLE")
        order.extend(ready)
        remaining.difference_update(ready)
    ancestors = {}
    for key in order:
        ancestors[key] = set(nodes[key]["depends_on"])
        for dep in nodes[key]["depends_on"]:
            ancestors[key].update(ancestors[dep])
    verified = set()
    for artifact in artifacts.values():
        for target in artifact["verifies"]:
            require(target in nodes and nodes[target]["kind"] == "requirement",
                    f"Invalid requirement verification: {target}", "INVALID_VERIFICATION")
            verified.add(target)
    for node in nodes.values():
        if node["kind"] == "requirement" and node["lifecycle"] == "implemented":
            require(node["id"] in verified, f"Requirement has no registered test: {node['id']}", "UNCOVERED_REQUIREMENT")
    managed = expand(root, cfg["managed"], required=bool(cfg["managed"]))
    require(set(managed) <= artifacts.keys(), "Unregistered managed files: " + ", ".join(sorted(set(managed) - artifacts.keys())),
            "UNMANAGED_FILE")
    for key, node in nodes.items():
        descendants = {n for n in nodes if key in ancestors[n]} | {key}
        documents = ancestors[key] | descendants
        inputs = {"config": digest(cfg), **{f"doc:{n}": nodes[n]["own_hash"] for n in sorted(documents)},
                  **{f"file:{p}": a["sha256"] for p, a in sorted(artifacts.items()) if a["owner"] in descendants}}
        node["inputs"] = inputs
        node["fingerprint"] = digest(inputs)
    edges = [{"id": f"depends-{dep}-{key}", "from": dep, "to": key, "kind": "depends_on"}
             for key, node in nodes.items() for dep in node["depends_on"]]
    graph_nodes = [{k: n[k] for k in ("id", "path", "title", "kind", "lifecycle")} for n in nodes.values()]
    for path, artifact in artifacts.items():
        fid = "file:" + path
        graph_nodes.append({"id": fid, "title": path, "path": path, "kind": artifact["role"]})
        edges.append({"id": "owns:" + path, "from": artifact["owner"], "to": fid, "kind": "owns"})
        for target in artifact["verifies"]:
            edges.append({"id": f"verifies:{path}:{target}", "from": fid, "to": target, "kind": "verifies"})
    return {"configuration": cfg, "nodes": nodes, "artifacts": artifacts,
            "graph": {"nodes": graph_nodes, "edges": edges}}


def _reviews(root):
    path = state_path("harness", "reviews")
    if not confined(root, path).exists():
        return {"schema_version": 1, "reviews": {}, "history": []}
    value = load_json(root, path)
    object_fields(value, ["schema_version", "reviews", "history"])
    require(value["schema_version"] == 1 and isinstance(value["reviews"], dict) and isinstance(value["history"], list),
            "Invalid review state", "INVALID_STATE")
    return value


def inspect(root):
    report = structure(root)
    reviews = _reviews(root)
    findings = []
    for key in reviews["reviews"]:
        if key not in report["nodes"]:
            findings.append({"code": "RETIRED_REVIEW_REQUIRED", "id": key})
    for key, node in report["nodes"].items():
        previous = reviews["reviews"].get(key)
        node["status"] = "current" if previous and previous.get("fingerprint") == node["fingerprint"] else (
            "stale" if previous else "unreviewed")
        old_inputs = previous.get("inputs", {}) if previous else {}
        node["changed_inputs"] = sorted(k for k in old_inputs.keys() | node["inputs"].keys()
                                        if old_inputs.get(k) != node["inputs"].get(k))
        if node["status"] != "current":
            findings.append({"code": "STALE_REVIEW" if previous else "REVIEW_REQUIRED", "id": key,
                             "changed_inputs": node["changed_inputs"]})
    for node in report["graph"]["nodes"]:
        node["status"] = report["nodes"].get(node["id"], {}).get("status", "artifact")
    return {**report, "ok": not findings, "findings": findings}


def _code_snapshot(root, report):
    return {path: file_hash(root, path) for path, a in sorted(report["artifacts"].items())
            if a["role"] in ("implementation", "test", "configuration")}


def tdd(root, phase, change):
    require(phase in ("red", "green"), "Unknown TDD phase")
    identifier(change, "change id")
    with ProjectLock(root, "harness"):
        report = structure(root)
        cfg = report["configuration"]
        require(cfg["verifier"]["format"] == "junit" and cfg["test_files"], "TDD needs JUnit and test_files")
        tests = snapshot(root, cfg["test_files"])
        code = _code_snapshot(root, report)
        red_path, green_path = state_path("harness", "red-" + change), state_path("harness", "green-" + change)
        red = None
        if phase == "green":
            red = load_json(root, red_path)
            check_fingerprint(red.get("configuration_sha256"), digest(cfg), "TDD configuration")
            check_fingerprint(red.get("test_hashes"), tests, "tests since Red")
            if confined(root, green_path).exists():
                require(load_json(root, green_path).get("red_id") != red.get("id"),
                        "Red evidence was already consumed; obtain a new failing run", "STALE_EVIDENCE")
        result = verify(root, cfg["verifier"])
        check_fingerprint(tests, snapshot(root, cfg["test_files"]), "tests during verification")
        check_fingerprint(code, _code_snapshot(root, structure(root)), "artifacts during verification")
        require("junit" in result and not result.get("evidence_error"),
                "No valid assertion evidence: " + result.get("evidence_error", result["status"]), "INVALID_EVIDENCE")
        counts = result["junit"]["counts"]
        if phase == "red":
            require(result["status"] == "failed" and counts["failure"] > 0
                    and result["junit"]["assertion_failures"] == counts["failure"],
                    "Red requires an actual assertion failure", "INVALID_EVIDENCE")
        else:
            require(result["ok"] and counts["failure"] == 0 and counts["passed"] > 0,
                    "Green requires all tests passing", "INVALID_EVIDENCE")
            check_fingerprint(red.get("test_ids"), result["junit"]["test_ids"], "executed test identities")
        evidence = {"schema_version": 1, "id": uuid.uuid4().hex, "phase": phase, "change": change,
                    "created_at": now(), "configuration_sha256": digest(cfg), "test_hashes": tests,
                    "test_ids": result["junit"]["test_ids"], "code_hashes": code,
                    "red_id": red["id"] if red else None, "result": result}
        write_json(root, red_path if phase == "red" else green_path, evidence)
        return {"ok": True, "phase": phase, "change": change, "counts": counts,
                "evidence": red_path if phase == "red" else green_path}


def current_green(root, change, report):
    evidence = load_json(root, state_path("harness", "green-" + identifier(change)))
    cfg = report["configuration"]
    require(evidence.get("phase") == "green" and evidence.get("result", {}).get("ok") is True,
            "Invalid Green record", "INVALID_EVIDENCE")
    check_fingerprint(evidence.get("configuration_sha256"), digest(cfg), "Green configuration")
    check_fingerprint(evidence.get("test_hashes"), snapshot(root, cfg["test_files"]), "Green tests")
    check_fingerprint(evidence.get("code_hashes"), _code_snapshot(root, report), "Green artifacts")
    return evidence["id"]


def acknowledge(root, node_id, change, reason):
    require(isinstance(reason, str) and len(reason.strip()) >= 24, "Record a specific review reason (at least 24 characters)")
    identifier(change, "change id")
    with ProjectLock(root, "harness"):
        report = inspect(root)
        require(node_id in report["nodes"], "Unknown document id")
        node = report["nodes"][node_id]
        code_changed = any(k.startswith("file:") and report["artifacts"].get(k[5:], {}).get("role")
                           in ("implementation", "test") for k in node["changed_inputs"])
        evidence_id = current_green(root, change, report) if report["configuration"]["require_tdd"] and code_changed else None
        state = _reviews(root)
        entry = {"fingerprint": node["fingerprint"], "inputs": node["inputs"], "change": change,
                 "reason": reason.strip(), "green_id": evidence_id, "reviewed_at": now()}
        state["reviews"][node_id] = entry
        state["history"].append({"node": node_id, **entry})
        write_json(root, state_path("harness", "reviews"), state)
    return {"ok": True, "reviewed": node_id, "fingerprint": node["fingerprint"]}


def retire(root, node_id, reason):
    require(isinstance(reason, str) and len(reason.strip()) >= 24, "A specific retirement reason is required")
    with ProjectLock(root, "harness"):
        report = structure(root)
        require(node_id not in report["nodes"], "Document still exists")
        state = _reviews(root)
        require(node_id in state["reviews"], "No previous review for this id")
        del state["reviews"][node_id]
        state["history"].append({"node": node_id, "action": "retire", "reason": reason.strip(), "at": now()})
        write_json(root, state_path("harness", "reviews"), state)
    return {"ok": True, "retired": node_id}


def _permitted(root, cfg, name):
    policy = cfg["policy"]
    require(name in policy["commands"], f"Action is not registered: {name}", "POLICY_DENIED")
    action = policy["commands"][name]
    require(action["role"] in policy["allowed_roles"], "Action role is not permitted", "POLICY_DENIED")
    argv = argv_for(action["command"], root)
    if policy["forbid_git_push"] and Path(argv[0]).name.lower() in ("git", "git.exe"):
        require("push" not in argv[1:], "git push is denied by execution policy", "POLICY_DENIED")
    return action["command"]


def run_action(root, name):
    cfg = configuration(root)
    command = _permitted(root, cfg, name)
    with ProjectLock(root, "harness"):
        before = digest(cfg)
        result = execute(root, command)
        check_fingerprint(before, digest(configuration(root)), "execution policy")
        record = {"action": name, "configuration_sha256": before, "at": now(), "result": result}
        write_json(root, state_path("harness", "action-" + uuid.uuid4().hex), record)
    return {"ok": result["status"] == "passed", **record}


def _equivalent_executable(a, b):
    a_path, b_path = shutil.which(a), shutil.which(b)
    return bool(a_path and b_path and Path(a_path).resolve() == Path(b_path).resolve())


def hook(root, event, payload):
    """Use shared Codex/Claude command-hook JSON; never trusts/enables the hook itself."""
    def deny(message):
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                       "permissionDecisionReason": message}}
    if event == "PreToolUse":
        try:
            require(isinstance(payload, dict) and payload.get("tool_name") == "Bash", "Unsupported tool for shell policy")
            command = payload.get("tool_input", {}).get("command")
            require(isinstance(command, str) and not re.search(r"[;&|<>`$()\n\r]", command),
                    "Only one literal registered argv command is accepted")
            args = shlex.split(command, posix=True)
            require(args, "Empty shell command")
            cfg = configuration(root)
            for key in cfg["policy"]["commands"]:
                try:
                    expected = argv_for(_permitted(root, cfg, key), root)
                except KitError:
                    continue
                if len(args) == len(expected) and args[1:] == expected[1:] and _equivalent_executable(args[0], expected[0]):
                    # Abstain instead of returning allow: preserve the provider's own approval policy.
                    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                   "additionalContext": f"Registered action: {key}. Provider permissions still apply."}}
            return deny("Command is outside the registered action allowlist. No command was executed by this hook.")
        except (KitError, ValueError, AttributeError):
            return deny("Cannot validate this shell request; denied.")
    report = inspect(root)
    if event == "SessionStart":
        return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext":
                f"Specification trace: {len(report['nodes'])} documents, {len(report['findings'])} pending reviews. "
                "Written prohibitions are context; execution policy and external permissions enforce controls."}}
    require(event == "Stop", "Unsupported hook event")
    if report["ok"] or payload.get("stop_hook_active") is True:
        return {}
    return {"decision": "block", "reason": "Specification reviews are stale or missing. Inspect harness impact, "
            "verify changed work, and record a reasoned review. This hook continues at most once per turn."}
