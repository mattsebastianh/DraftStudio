#!/usr/bin/env python3
"""Validate an n8n workflow JSON file for the DraftStudio pipeline (stdlib only).

Usage: python3 scripts/validate_n8n_workflow.py <workflow.json>
Prints each error and exits 1 if any; otherwise prints "OK: <n> nodes" and exits 0.
"""
import json
import re
import sys
from collections import deque

ALLOWED_PREFIXES = ("n8n-nodes-base.", "@n8n/n8n-nodes-langchain.")
FORBIDDEN_TYPES = {
    "n8n-nodes-base.code",
    "n8n-nodes-base.function",
    "n8n-nodes-base.functionItem",
    "n8n-nodes-base.executeCommand",
}
CONNECTION_TYPES = {"main", "ai_languageModel", "ai_outputParser", "ai_tool", "ai_memory"}
STICKY_TYPE = "n8n-nodes-base.stickyNote"
SECRET_RE = re.compile(r"gsk_[A-Za-z0-9]{10,}|tvly-[A-Za-z0-9]{10,}|sk-[A-Za-z0-9]{20,}")


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_trigger(node_type):
    return "webhook" in node_type or "Trigger" in node_type


def _walk_strings(obj, path):
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for key, value in obj.items():
            yield from _walk_strings(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            yield from _walk_strings(value, f"{path}[{i}]")


def _check_nodes(nodes, errors):
    names, ids = set(), set()
    for i, node in enumerate(nodes):
        if not isinstance(node, dict):
            errors.append(f"node[{i}]: not an object")
            continue
        label = node.get("name", f"node[{i}]")
        name = node.get("name")
        if not isinstance(name, str) or not name:
            errors.append(f"node[{i}]: missing name")
        elif name in names:
            errors.append(f"duplicate node name: {name!r}")
        else:
            names.add(name)
        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id:
            errors.append(f"{label}: missing id")
        elif node_id in ids:
            errors.append(f"duplicate node id: {node_id!r} ({label})")
        else:
            ids.add(node_id)

        node_type = node.get("type")
        if not isinstance(node_type, str) or not node_type:
            errors.append(f"{label}: missing type")
        else:
            if not node_type.startswith(ALLOWED_PREFIXES):
                errors.append(f"{label}: non-native node type {node_type!r}")
            if node_type in FORBIDDEN_TYPES:
                errors.append(f"{label}: forbidden node type {node_type!r}")

        if not _is_number(node.get("typeVersion")):
            errors.append(f"{label}: typeVersion must be a number")
        pos = node.get("position")
        if not (isinstance(pos, list) and len(pos) == 2 and all(_is_number(p) for p in pos)):
            errors.append(f"{label}: position must be two numbers")
        if not isinstance(node.get("parameters"), dict):
            errors.append(f"{label}: parameters must be an object")

        creds = node.get("credentials")
        if creds is not None:
            if not isinstance(creds, dict):
                errors.append(f"{label}: credentials must be an object")
            else:
                for cred_type, cred in creds.items():
                    if not isinstance(cred, dict):
                        errors.append(f"{label}: credential {cred_type!r} must be an object")
                        continue
                    for field in ("id", "name"):
                        if not cred.get(field):
                            errors.append(f"{label}: credential {cred_type!r} missing {field}")
    return names


def _check_connections(connections, names, errors):
    """Validate connections; return undirected adjacency map over node names."""
    adjacency = {name: set() for name in names}
    if not isinstance(connections, dict):
        errors.append("connections must be an object")
        return adjacency
    for source, by_type in connections.items():
        if source not in names:
            errors.append(f"connection from unknown source node {source!r}")
        if not isinstance(by_type, dict):
            errors.append(f"connections[{source!r}] must be an object")
            continue
        for conn_type, outputs in by_type.items():
            if conn_type not in CONNECTION_TYPES:
                errors.append(f"{source}: invalid connection type {conn_type!r}")
            for output in outputs or []:
                for target in output or []:
                    target_name = target.get("node") if isinstance(target, dict) else None
                    if target_name not in names:
                        errors.append(
                            f"{source}: connection to unknown target node {target_name!r}")
                        continue
                    target_type = target.get("type")
                    if target_type is not None and target_type not in CONNECTION_TYPES:
                        errors.append(
                            f"{source} -> {target_name}: invalid connection type {target_type!r}")
                    if source in names:
                        adjacency[source].add(target_name)
                        adjacency[target_name].add(source)
    return adjacency


def _check_reachability(nodes, adjacency, errors):
    typed = {n["name"]: n.get("type", "") for n in nodes
             if isinstance(n, dict) and isinstance(n.get("name"), str)}
    roots = [name for name, t in typed.items() if isinstance(t, str) and _is_trigger(t)]
    if not roots:
        errors.append("no trigger node (webhook or *Trigger) found")
    seen = set(roots)
    queue = deque(roots)
    while queue:
        for nxt in adjacency.get(queue.popleft(), ()):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    for name, node_type in typed.items():
        if node_type != STICKY_TYPE and name not in seen:
            errors.append(f"unreachable node (not connected to a trigger): {name!r}")


def validate(workflow):
    """Return a list of error strings; an empty list means the workflow is valid."""
    errors = []
    if not isinstance(workflow, dict):
        return ["workflow must be a JSON object"]
    for key in ("name", "nodes", "connections"):
        if key not in workflow:
            errors.append(f"missing top-level key: {key}")

    nodes = workflow.get("nodes", [])
    if not isinstance(nodes, list):
        errors.append("nodes must be a list")
        nodes = []
    names = _check_nodes(nodes, errors)
    adjacency = _check_connections(workflow.get("connections", {}), names, errors)
    if nodes:
        _check_reachability(nodes, adjacency, errors)

    match = SECRET_RE.search(json.dumps(workflow))
    if match:
        errors.append(f"possible secret in workflow JSON: {match.group(0)[:6]}...")

    for path, text in _walk_strings(workflow, "$"):
        opens, closes = text.count("{{"), text.count("}}")
        if opens != closes:
            errors.append(
                f"unbalanced expression braces at {path}: {opens} '{{{{' vs {closes} '}}}}'")
    return errors


def main(argv):
    if len(argv) != 2:
        print(f"usage: {argv[0]} <workflow.json>")
        return 2
    try:
        with open(argv[1], encoding="utf-8") as fh:
            workflow = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"cannot load {argv[1]}: {exc}")
        return 1
    errors = validate(workflow)
    for err in errors:
        print(err)
    if errors:
        return 1
    print(f"OK: {len(workflow.get('nodes', []))} nodes")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
