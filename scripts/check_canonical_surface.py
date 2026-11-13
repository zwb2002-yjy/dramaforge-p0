#!/usr/bin/env python3
"""Fail when a retired product surface is reintroduced."""

from __future__ import annotations

import ast
import json
import re
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = (
    ROOT / "backend" / "app",
    ROOT / "frontend" / "src",
    ROOT / "scripts",
    ROOT / "fixtures",
)

# Match active identifiers and exact contract strings, not prose substrings.
FORBIDDEN_TEXT = (
    "LEGACY_" + "COMPAT",
    "AUDIO_" + "TTS",
    "audio." + "tts",
    "TTS" + "Request",
    "fallback_" + "policy",
    "/director/turns/{turn_id}/" + "decision",
    "/director/turns/{turn_id}/" + "resume",
    "/director/turns/{turn_id}/" + "stop",
    "litellm/text-" + "llm",
    "shot_" + "experiment_id",
    "translate_" + "v2",
    "/projects/" + "$projectId/quick",
    "p0_" + "10_shots",
    "/creation/" + "start-project",
    "creation-" + "state",
    "produce-" + "golden",
    "confirm_" + "plan_and_materialize",
    "characters/" + "lead",
    "production_" + "batch_id",
    "budget_" + "reservation_id",
    "app." + "creation",
    "Director" + "WorkflowRun",
    "Character" + "Reference",
    "experience_" + "mode",
    "PROVIDER_" + "UNIFIED_PATH_ENABLED",
    "TEXT_" + "V3_ROUTER_ENABLED",
    "start_" + "shot_nodes",
    "upload_" + "manual_media",
    "allow_" + "trial_without_quality_gate",
    "professional_" + "trial_bootstrap_allowed",
    "trial_" + "quality_gate_exception",
    "audited_" + "manual_upload",
    "manual_" + "media",
    "/projects/" + "{project_id}/generations",
    "/generations/" + "{operation_id}/cancel",
    "provider-" + "credentials",
    "settings_for_workspace_" + "provider",
    "Experiment" + "Service",
    "ExperimentCreate" + "Input",
    "ExecuteKeyframe" + "Result",
    "/projects/" + "{project_id}/dispatch",
    "/projects/" + "{project_id}/node-runs/{node_run_id}/enqueue",
    "Agnes" + "HubClient",
    "MiniMax" + "HubClient",
    "Ark" + "HubClient",
)
FORBIDDEN_FILES = (
    ROOT / "backend" / "app" / "production" / "archive_models.py",
    ROOT / "backend" / "app" / "providers" / "generation_service.py",
    ROOT / "backend" / "app" / "providers" / "model_system_models.py",
    ROOT / "backend" / "app" / "providers" / "binding_cutover.py",
    ROOT / "backend" / "app" / "production" / "cutover_identity.py",
    ROOT / "backend" / "app" / "production" / "policy_models.py",
    ROOT / "backend" / "app" / "providers" / "catalog_seed_data.py",
    ROOT / "backend" / "app" / "providers" / "workspace_router.py",
    ROOT / "backend" / "app" / "creation",
    ROOT / "backend" / "app" / "shared" / "ids.py",
    ROOT / "backend" / "app" / "providers" / "connection.py",
    ROOT / "backend" / "app" / "api" / "v1" / "characters.py",
    ROOT / "backend" / "app" / "api" / "v1" / "credentials.py",
    ROOT
    / "frontend"
    / "src"
    / "components"
    / "provider"
    / "WorkspaceTextCredentialSettings.tsx",
    ROOT / "backend" / "app" / "api" / "v1" / "shot_ops.py",
    ROOT / "backend" / "app" / "director" / "business_checkpoints.py",
    ROOT / "backend" / "app" / "director" / "next_action.py",
    ROOT / "backend" / "app" / "director" / "legacy_guard.py",
    ROOT / "backend" / "app" / "director" / "execution_guard.py",
    ROOT / "backend" / "app" / "director" / "registry.py",
    ROOT / "backend" / "app" / "director" / "enums.py",
    ROOT / "backend" / "app" / "providers" / "flux.py",
    ROOT / "backend" / "app" / "providers" / "kling.py",
    ROOT / "backend" / "app" / "execution" / "shot_review.py",
    ROOT / "backend" / "app" / "delivery" / "export_service.py",
    ROOT / "backend" / "app" / "delivery" / "export_local.py",
    ROOT / "scripts" / "rerun_drift_blocks.py",
    ROOT / "frontend" / "src" / "routes" / "projects.$projectId.quick.tsx",
)
FORBIDDEN_PATH_TEXT = {
    ROOT / "backend" / "app" / "production" / "models.py": (
        "Graph = Production" + "Graph",
    ),
    ROOT / "backend" / "app" / "director" / "editing_suggestion.py": (
        "def suggestion(",
    ),
    ROOT / "backend" / "app" / "providers" / "intents.py": (
        "ReferenceRole = ReferenceRole" + "Value",
    ),
    ROOT / "backend" / "app" / "providers" / "models.py": (
        "pricing_" + "snapshot_json",
    ),
    ROOT / "backend" / "app" / "providers" / "connection_service.py": (
        "set_binding_" + "pricing",
        "PROBE_PRICING_" + "CURRENCY",
    ),
    ROOT / "backend" / "app" / "execution" / "media_submission.py": (
        "_binding_pricing_" + "currency",
    ),
    ROOT / "backend" / "app" / "api" / "v1" / "experiments.py": (
        "accepted_" + "without_candidate",
    ),
    ROOT / "backend" / "app" / "editing" / "proposal_plan.py": (
        '"session_' + 'id"',
        '"timeline_' + 'plan"',
        'aliases = ("kind", "type", "op")',
    ),
    ROOT / "backend" / "app" / "production" / "repair_service.py": (
        "def execute_" + "repair(",
        "def create_and_" + "execute_first_step(",
    ),
    ROOT / "backend" / "app" / "director" / "business_checkpoints.py": (
        "def track_" + "execution(",
    ),
}

IGNORED_PARTS = {".git", ".venv", "node_modules", "__pycache__", "dist", "tmp"}
SOURCE_SUFFIXES = {".py", ".js", ".jsx", ".mjs", ".ts", ".tsx", ".json", ".ps1", ".sh"}


def _assignment(target: ast.AST, value: ast.AST) -> str | None:
    if isinstance(target, ast.Name):
        return f"assign:{target.id}:{ast.dump(value, include_attributes=False)}"
    return None


def _policy_reference(value: str) -> str:
    if value.startswith("def "):
        return value[4:].split("(", 1)[0]
    if "=" in value:
        node = ast.parse(value).body[0]
        if isinstance(node, ast.Assign):
            return _assignment(node.targets[0], node.value) or value
    return value.strip('"')


def _javascript_references(source: str, *, jsx: bool) -> set[str]:
    """Lex references without treating regexes, template bodies or JSX copy as code.

    This is a reference lexer, not a replacement for the TypeScript compiler.
    Dynamic string construction still needs behavioral review.
    """
    references: set[str] = set()
    size = len(source)
    name_pattern = re.compile(r"[$A-Za-z_][\w$]*(?:\.[$A-Za-z_][\w$]*)*")

    def decode(raw: str) -> str:
        escapes = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}

        def replace(match: re.Match[str]) -> str:
            value = match.group(1)
            if value.startswith("u{"):
                return chr(int(value[2:-1], 16))
            if value.startswith(("u", "x")) and len(value) > 1:
                return chr(int(value[1:], 16))
            return escapes.get(value, "" if value in {"\n", "\r\n"} else value)

        return re.sub(r"\\(u\{[0-9a-fA-F]{1,6}\}|u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|\r\n|.)", replace, raw, flags=re.DOTALL)

    def quoted(position: int) -> int:
        quote = source[position]
        position += 1
        start = position
        parts: list[str] = []
        interpolated = False
        while position < size:
            if source[position] == "\\":
                position += 2
            elif quote == "`" and source.startswith("${", position):
                interpolated = True
                parts.append(source[start:position])
                position = code(position + 2, "}")
                start = position
            elif source[position] == quote:
                parts.append(source[start:position])
                if not interpolated:
                    references.add(decode("".join(parts)))
                return position + 1
            else:
                position += 1
        raise ValueError("Unterminated JavaScript string")

    def element(position: int) -> int:
        # Opening tag names and attributes are code; text children are prose.
        position = code(position + 1, ">")
        if source[position - 2:position] == "/>":
            return position
        while position < size:
            if source.startswith("</", position):
                return code(position + 2, ">")
            if source[position] == "<":
                position = element(position)
            elif source[position] == "{":
                position = code(position + 1, "}")
            else:
                position += 1
        raise ValueError("Unterminated JSX element")

    def code(position: int, end: str = "") -> int:
        expression_start = True
        control_parenthesis = False
        while position < size:
            char = source[position]
            if end and char == end:
                return position + 1
            if char.isspace():
                position += 1
                continue
            if source.startswith("//", position):
                newline = source.find("\n", position + 2)
                position = size if newline < 0 else newline + 1
                continue
            if source.startswith("/*", position):
                close = source.find("*/", position + 2)
                if close < 0:
                    raise ValueError("Unterminated JavaScript comment")
                position = close + 2
                continue
            if char in "\"'`":
                position = quoted(position)
                expression_start = False
                continue
            if char == "/" and expression_start and end != ">":
                position += 1
                in_class = False
                while position < size:
                    current = source[position]
                    if current == "\\":
                        position += 2
                        continue
                    if current == "[":
                        in_class = True
                    elif current == "]":
                        in_class = False
                    elif current == "/" and not in_class:
                        position += 1
                        break
                    position += 1
                expression_start = False
                continue
            if jsx and char == "<" and expression_start and end != ">":
                tag = re.match(r"<([A-Za-z][\w.:-]*)?\s*(?:>|/|[A-Za-z{])", source[position:])
                if tag and (tag.group(1) is None or f"</{tag.group(1)}" in source[position:] or "/>" in source[position:source.find(">", position) + 1]):
                    position = element(position)
                    expression_start = False
                    continue
            if char in "{([":
                after_control = char == "(" and control_parenthesis
                position = code(position + 1, {"{": "}", "(": ")", "[": "]"}[char])
                expression_start = after_control
                control_parenthesis = False
                continue
            if char == "<" and end == ">":
                # Type arguments on JSX components are inside the opening tag.
                position = code(position + 1, ">")
                continue
            if match := name_pattern.match(source, position):
                name = match.group()
                references.add(name)
                references.update(name.split("."))
                position = match.end()
                control_parenthesis = name in {"if", "while", "for", "with", "switch", "catch"}
                expression_start = name in {"return", "throw", "case", "yield", "await", "typeof", "void", "delete", "new"}
                continue
            expression_start = char in "=,:;!?&|+-*%~<>"
            position += 1
        return position

    code(0)
    return references


def code_references(source: str, suffix: str) -> set[str]:
    """Static references only; runtime registration and reflection still need behavior tests."""
    references: set[str] = set()
    if suffix == ".py":
        tree = ast.parse(source.removeprefix("\ufeff"))
        prose = {
            id(node.value) for node in ast.walk(tree)
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                references.add(node.id)
            elif isinstance(node, ast.Attribute):
                references.add(node.attr)
                references.add(ast.unparse(node))
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                references.add(node.name)
            elif isinstance(node, ast.arg):
                references.add(node.arg)
            elif isinstance(node, ast.Import):
                references.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                references.add(node.module or "")
                for alias in node.names:
                    references.add(alias.name)
                    references.add(f"{node.module}.{alias.name}")
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) not in prose:
                    references.add(node.value)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if token := _assignment(target, node.value):
                        references.add(token)
            elif (
                isinstance(node, ast.AnnAssign) and node.value is not None
                and (token := _assignment(node.target, node.value))
            ):
                references.add(token)
        return references
    if suffix in {".js", ".jsx", ".mjs", ".ts", ".tsx"}:
        return _javascript_references(source, jsx=suffix in {".jsx", ".tsx"})
    if suffix in {".ps1", ".sh"}:
        # Lex strings before inspecting their contents, so URL // is not a comment.
        comments = r"#[^\n]*|<\#.*?\#>" if suffix in {".ps1", ".sh"} else r"//[^\n]*|/\*.*?\*/"
        pattern = re.compile(
            rf"(?P<comment>{comments})|"
            r'''(?P<string>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)|'''
            r"(?P<name>[$A-Za-z_][\w$]*(?:\.[$A-Za-z_][\w$]*)*)", re.DOTALL,
        )
        for match in pattern.finditer(source):
            if name := match.group("name"):
                references.add(name)
                if suffix in {".ps1", ".sh"}:
                    references.add(name.lstrip("$"))
                references.update(name.split("."))
            elif literal := match.group("string"):
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", SyntaxWarning)
                        value = json.loads(literal) if literal.startswith('"') else ast.literal_eval(literal)
                except (ValueError, SyntaxError):
                    value = literal[1:-1]
                references.add(value)
                if literal.startswith("`"):
                    for expression in re.findall(r"\$\{([^{}]*)\}", value):
                        references.update(code_references(expression, ".ts"))
        return references
    if suffix == ".json":
        def visit(value: object) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    references.add(key)
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)
            elif isinstance(value, str):
                references.add(value)
        visit(json.loads(source))
    return references


def contains_reference(references: set[str], token: str) -> bool:
    expected = _policy_reference(token)
    return expected in references or (
        expected.startswith("app.")
        and any(value.startswith(expected + ".") for value in references)
    )


def _files() -> list[Path]:
    return [
        path
        for root in SCAN_ROOTS
        for path in root.rglob("*")
        if path.is_file() and path.suffix in SOURCE_SUFFIXES
        and not IGNORED_PARTS.intersection(path.parts)
    ]


def main() -> int:
    failures: list[str] = []
    for path in FORBIDDEN_FILES:
        source_exists = (
            path.is_file()
            or path.is_dir()
            and any(
                child.is_file()
                and child.suffix == ".py"
                and not IGNORED_PARTS.intersection(child.parts)
                for child in path.rglob("*.py")
            )
        )
        if source_exists:
            failures.append(f"retired file/directory exists: {path.relative_to(ROOT)}")
    for path in _files():
        if path.resolve() == Path(__file__).resolve():
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        try:
            references = code_references(source, path.suffix)
        except (SyntaxError, ValueError) as exc:
            failures.append(f"cannot inspect {path.relative_to(ROOT)}: {exc}")
            continue
        for token in FORBIDDEN_TEXT:
            if contains_reference(references, token):
                failures.append(
                    f"{path.relative_to(ROOT)} contains retired token {token!r}"
                )
    for path, tokens in FORBIDDEN_PATH_TEXT.items():
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        references = code_references(source, path.suffix)
        for token in tokens:
            if contains_reference(references, token):
                failures.append(
                    f"{path.relative_to(ROOT)} contains retired compatibility token {token!r}"
                )
    if failures:
        print("Canonical surface check FAILED:", file=sys.stderr)
        print(
            "\n".join(f"  - {failure}" for failure in sorted(set(failures))),
            file=sys.stderr,
        )
        return 1
    print("Canonical surface check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
