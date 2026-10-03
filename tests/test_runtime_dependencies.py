"""The API imports only runtime dependencies.

Vercel's build and the production image install `uv sync --no-dev`, so a package of the dev group (tests, notebooks,
scripts, training) is missing there. These tests walk every src module the API can reach from src.api.app, through
imports at module level or inside functions (a function's import runs on a request), and check that each third-party
package they import is a runtime dependency in uv.lock, directly or pulled in by one.
"""

import ast
import re
import sys
import tomllib
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def runtime_packages() -> set[str]:
    """The project's runtime dependencies in uv.lock plus everything they pull in, extras included; never the dev group."""
    entries: dict[str, list[dict]] = {}
    for package in tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))["package"]:
        entries.setdefault(package["name"], []).append(package)  # a package locked at two versions has two entries

    def requirements(deps: list[dict]) -> list[tuple[str, str | None]]:
        return [(dep["name"], extra) for dep in deps for extra in [None, *dep.get("extra", [])]]

    pending = requirements(entries["hackaton"][0]["dependencies"])
    seen: set[tuple[str, str | None]] = set()
    while pending:
        name, extra = pending.pop()
        if (name, extra) in seen:
            continue
        seen.add((name, extra))
        for package in entries[name]:
            deps = package.get("dependencies", []) if extra is None else package.get("optional-dependencies", {}).get(extra, [])
            pending.extend(requirements(deps))
    return {name for name, _ in seen}


def _module_file(name: str) -> Path | None:
    base = ROOT.joinpath(*name.split("."))
    for path in (base.with_suffix(".py"), base / "__init__.py"):
        if path.is_file():
            return path
    return None


def api_third_party_imports(start: str = "src.api.app") -> dict[str, set[str]]:
    """Top-level third-party module -> the src modules reachable from `start` that import it, anywhere in the file."""
    found: dict[str, set[str]] = {}
    pending, seen = [start], set()
    while pending:
        name = pending.pop()
        path = _module_file(name)
        if name in seen or path is None:
            continue
        seen.add(name)
        parts = name.split(".")
        pending.extend(".".join(parts[:i]) for i in range(1, len(parts)))  # importing a module runs its packages first
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):  # src has no relative imports
                targets = [node.module, *(f"{node.module}.{alias.name}" for alias in node.names)]
            else:
                continue
            for target in targets:
                top = target.split(".")[0]
                if top == "src":
                    pending.append(target)
                elif top not in sys.stdlib_module_names and top != "__future__":
                    found.setdefault(top, set()).add(name)
    return found


def test_the_walk_reaches_module_level_and_lazy_imports():
    # fastapi at module level; sklearn only when the risk model loads, psycopg only on the Postgres path
    assert {"fastapi", "duckdb", "sklearn", "psycopg"} <= set(api_third_party_imports())


def test_the_lock_separates_runtime_from_dev():
    runtime = runtime_packages()
    assert {"fastapi", "starlette", "cryptography", "psycopg-binary", "anthropic"} <= runtime  # direct, transitive, through extras
    assert not {"pytest", "mlflow-skinny", "ipykernel", "matplotlib"} & runtime


def test_the_api_imports_only_runtime_dependencies():
    runtime = runtime_packages()
    owners = metadata.packages_distributions()
    outside = sorted(
        f"{module} imports {top}"
        for top, modules in api_third_party_imports().items()
        if not any(_normalize(dist) in runtime for dist in owners.get(top, [top]))
        for module in modules
    )
    assert not outside, (
        "a dev-only package is reached from the API; import it inside a function the API never calls, "
        "or make it a runtime dependency: " + "; ".join(outside)
    )
