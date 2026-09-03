"""Unit 20 (MEADOWOPS-API-004, DD-2): pure AST-based checker enforcing the
Subsystem 2 service-layer import boundary — nothing under
`app.services.subsystem2` may import `app.db.session` or a `live`-schema ORM
model module directly to read Subsystem 1's data (PRD 376, S1-FR-6); it must
go through `request.app.state.subsystem2_client`
(app.core.internal_client) instead, the same real HTTP path an external
caller would use. Pure and unit-tested directly against synthetic source
strings first, in both a compliant and a violating direction — Unit 19's own
security review already caught one enforcement test that could never fail
regardless of what it checked (`test_sandbox_refresh.py`'s prior
`names.isdisjoint(EXCLUDED_TABLES)`), so this doesn't repeat that shape.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

# Subsystem 1's own session/engine construction, plus every live-schema ORM
# model module (mirrors app/db/__init__.py's own registration list).
# Deliberately excludes app.db.scenario (and any future Evaluation/Portfolio
# module) — that's Subsystem 2's own `engine`-schema data, not Subsystem 1's,
# and this boundary was never meant to block a subsystem from its own data.
FORBIDDEN_MODULES = frozenset(
    {
        "app.db.session",
        "app.db.auth",
        "app.db.dimensions",
        "app.db.exception_flags",
        "app.db.exception_rules",
        "app.db.facts",
        "app.db.kpi",
        "app.db.ledger",
        "app.db.query_log",
        "app.db.reporting",
        "app.db.scheduling",
        "app.db.world_state",
    }
)


@dataclass(frozen=True)
class BoundaryViolation:
    file: str
    forbidden_module: str
    line: int


def _resolve_relative_module(owning_module: str, level: int, module: str | None) -> str | None:
    """Mirrors Python's own relative-import resolution (PEP 328): `level=1`
    is the current package, `level=2` is one above it, etc. `owning_module`
    must already be the *package* dotted name (an `__init__.py`'s own
    module, or a regular module's parent) - see `_module_name_for_file`.
    Returns None if `level` climbs above the package root (nothing left to
    resolve against)."""
    parts = owning_module.split(".")
    drop = level - 1
    if drop > len(parts):
        return None
    base = parts[: len(parts) - drop]
    if module:
        base = base + module.split(".")
    return ".".join(base)


def _module_name_for_file(file_path: Path, package_root: Path) -> str:
    """The dotted *package* name relative imports inside `file_path`
    resolve against - e.g. `backend/app/services/subsystem2/foo.py` (a
    regular module) resolves against `app.services.subsystem2`;
    `backend/app/services/subsystem2/__init__.py` resolves against
    `app.services.subsystem2` too (a package's own `__init__` IS that
    package, per PEP 328)."""
    rel_parts = list(file_path.relative_to(package_root).with_suffix("").parts)
    return ".".join(rel_parts[:-1])


def check_source(
    source: str, *, file_label: str = "<source>", owning_module: str | None = None
) -> list[BoundaryViolation]:
    """Flags every import form that can reach a forbidden module: plain
    `import app.db.session`, `from app.db.session import make_engine` /
    `from app.db import session`, and a relative `from ...db.session import
    make_engine` resolved against `owning_module` (code review of this
    unit, LOW: an exact-string match on `node.module` alone silently passed
    every relative-import form, since `ast.ImportFrom.module` never carries
    the `app.` prefix for those). When `owning_module` isn't supplied (the
    synthetic-source unit tests below, which never use relative imports),
    any relative import is flagged outright rather than assumed safe -
    unresolvable is not the same as compliant."""
    tree = ast.parse(source, filename=file_label)
    violations: list[BoundaryViolation] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in FORBIDDEN_MODULES:
                    violations.append(BoundaryViolation(file_label, alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                resolved = (
                    _resolve_relative_module(owning_module, node.level, node.module)
                    if owning_module is not None
                    else None
                )
                if resolved is None:
                    violations.append(
                        BoundaryViolation(
                            file_label, "<unresolvable relative import>", node.lineno
                        )
                    )
                    continue
                module = resolved
            else:
                module = node.module
            if module is None:
                continue
            if module in FORBIDDEN_MODULES:
                violations.append(BoundaryViolation(file_label, module, node.lineno))
            for alias in node.names:
                full = f"{module}.{alias.name}"
                if full in FORBIDDEN_MODULES:
                    violations.append(BoundaryViolation(file_label, full, node.lineno))
    return violations


def check_directory(root: Path, *, package_root: Path | None = None) -> list[BoundaryViolation]:
    """`package_root` is the directory containing the top-level `app`
    package (i.e. `backend/`) - defaults to `root`'s own great-grandparent
    when `root` is `backend/app/services/subsystem2`, but callers checking a
    differently-nested directory should pass it explicitly."""
    resolved_package_root = package_root or root.parents[2]
    violations: list[BoundaryViolation] = []
    for path in sorted(root.rglob("*.py")):
        violations.extend(
            check_source(
                path.read_text(),
                file_label=str(path),
                owning_module=_module_name_for_file(path, resolved_package_root),
            )
        )
    return violations
