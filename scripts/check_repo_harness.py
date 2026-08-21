#!/usr/bin/env python3
from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IGNORED_DIRECTORIES = {".git", ".pytest_cache", ".venv", "__pycache__"}

REQUIRED_PATHS = (
    "AGENTS.md",
    "ARCHITECTURE.md",
    "CONTRIBUTING.md",
    "docs/README.md",
    "docs/QUALITY.md",
    "docs/design-docs/core-beliefs.md",
    "docs/product-specs/benchmark-contract.md",
    "docs/exec-plans/README.md",
    "docs/exec-plans/template.md",
)

LAYERS = {
    "models": 0,
    "adapter": 1,
    "database": 1,
    "metrics": 1,
    "runner": 2,
    "main": 3,
    "cli": 4,
    "__main__": 5,
}


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def check_required_paths(errors: list[str]) -> None:
    for relative in REQUIRED_PATHS:
        if not (ROOT / relative).is_file():
            fail(errors, f"missing required repository record: {relative}")


def check_agent_map(errors: list[str]) -> None:
    path = ROOT / "AGENTS.md"
    if not path.exists():
        return
    line_count = len(path.read_text(encoding="utf-8").splitlines())
    if line_count > 120:
        fail(errors, f"AGENTS.md has {line_count} lines; keep the map at or below 120 lines")


def check_markdown_links(errors: list[str]) -> None:
    link_pattern = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
    for path in ROOT.rglob("*.md"):
        if IGNORED_DIRECTORIES.intersection(path.relative_to(ROOT).parts):
            continue
        text = path.read_text(encoding="utf-8")
        for raw_target in link_pattern.findall(text):
            target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
            if not target or target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            relative_target = target.split("#", 1)[0]
            if relative_target and not (path.parent / relative_target).resolve().exists():
                fail(errors, f"broken Markdown link in {path.relative_to(ROOT)}: {target}")


def regex_value(path: str, pattern: str, errors: list[str]) -> str | None:
    match = re.search(pattern, (ROOT / path).read_text(encoding="utf-8"), re.MULTILINE)
    if not match:
        fail(errors, f"could not read version from {path}")
        return None
    return match.group(1)


def check_versions(errors: list[str]) -> None:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        project_version = tomllib.load(handle)["project"]["version"]
    versions = {
        "pyproject.toml": project_version,
        "inferbench/__init__.py": regex_value(
            "inferbench/__init__.py", r'^__version__\s*=\s*"([^"]+)"', errors
        ),
        "inferbench/main.py": regex_value(
            "inferbench/main.py", r'^\s*version\s*=\s*"([^"]+)"', errors
        ),
        "scripts/build-multiarch.sh": regex_value(
            "scripts/build-multiarch.sh", r'^TAG="\$\{TAG:-v([^}]+)\}"', errors
        ),
    }
    for source, value in versions.items():
        if value is not None and value != project_version:
            fail(errors, f"version drift: {source} has {value}, expected {project_version}")


def imported_local_modules(tree: ast.AST) -> set[str]:
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level:
            if node.module:
                imported.add(node.module.split(".", 1)[0])
            else:
                imported.update(alias.name.split(".", 1)[0] for alias in node.names)
    return imported


def check_python_layers(errors: list[str]) -> None:
    for path in (ROOT / "inferbench").glob("*.py"):
        source = path.stem
        if source not in LAYERS:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for target in imported_local_modules(tree):
            if target in LAYERS and LAYERS[target] > LAYERS[source]:
                fail(
                    errors,
                    f"dependency direction violation: inferbench.{source} imports inferbench.{target}",
                )


def check_release_invariants(errors: list[str]) -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    if "COPY pyproject.toml README.md LICENSE ./" not in dockerfile:
        fail(errors, "Dockerfile must copy LICENSE before installing the package")

    workflow = (ROOT / ".github/workflows/build_images.yaml").read_text(encoding="utf-8")
    for expected in ('- "v*"', "linux/amd64,linux/arm64", "openbayes_common/inferbench"):
        if expected not in workflow:
            fail(errors, f"image workflow is missing invariant: {expected}")
    if ":latest" in workflow:
        fail(errors, "image workflow must not publish latest")


def main() -> int:
    errors: list[str] = []
    check_required_paths(errors)
    check_agent_map(errors)
    check_markdown_links(errors)
    check_versions(errors)
    check_python_layers(errors)
    check_release_invariants(errors)

    if errors:
        print("[harness] repository checks failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print("[harness] repository map, links, layers, versions and release invariants are valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
