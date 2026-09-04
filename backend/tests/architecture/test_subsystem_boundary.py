"""Unit 20 (MEADOWOPS-API-004, DD-2): enforces the Subsystem 2 service-layer
import boundary two ways — a pure AST checker (proven discriminating against
synthetic source first, then run against the real `app/services/subsystem2`
tree) and a route-inventory test proving the internal-service credential's
actual reachable route set matches an explicit, consciously-maintained
allowlist, not an assumption about what `require_authenticated` covers.

Pre-implementation security review of this unit found that Query Playground
routes (require_authenticated, not require_admin) do real work — commit
confirmed SQL, refresh the sandbox as the owner role — before a route body
ever notices the internal-service credential's non-UUID user_id. The route-
inventory test below is what actually proves that hole is closed: a route
added later with bare `require_authenticated` automatically joins the
"service-allowed" set, and this test fails with a clear diff instead of
silently over-granting, forcing a conscious choice (allow it, or add
`reject_service_role`) rather than an accident of argument-evaluation order.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.routing import APIRoute

from app.core.auth import reject_service_role, require_admin, require_authenticated
from app.core.config import Settings
from app.domain.subsystem_boundary import check_directory, check_source
from app.main import create_app

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SUBSYSTEM2_DIR = _REPO_ROOT / "app" / "services" / "subsystem2"


class TestCheckSourceIsDiscriminating:
    """Proven against synthetic source first — never trust an enforcement
    check that's only ever been run against the (currently near-empty) real
    tree, which would pass vacuously regardless of whether the check itself
    works (the exact failure mode Unit 19's security review caught once
    already, see this file's own module docstring)."""

    def test_clean_source_has_no_violations(self) -> None:
        source = (
            "from app.db.scenario import Scenario\n"
            "from app.core.internal_client import build_subsystem2_client\n"
            "\n"
            "def do_something(client):\n"
            "    return client.get('/api/v1/dashboard/executive')\n"
        )
        assert check_source(source) == []

    def test_flags_a_plain_import_of_the_session_module(self) -> None:
        violations = check_source("import app.db.session\n")
        assert len(violations) == 1
        assert violations[0].forbidden_module == "app.db.session"

    def test_flags_from_import_of_a_name_from_the_session_module(self) -> None:
        violations = check_source("from app.db.session import make_engine\n")
        assert len(violations) == 1
        assert violations[0].forbidden_module == "app.db.session"

    def test_flags_from_app_db_import_session(self) -> None:
        violations = check_source("from app.db import session\n")
        assert len(violations) == 1
        assert violations[0].forbidden_module == "app.db.session"

    def test_flags_a_live_schema_orm_model_import(self) -> None:
        violations = check_source("from app.db.dimensions import Product\n")
        assert len(violations) == 1
        assert violations[0].forbidden_module == "app.db.dimensions"

    def test_does_not_flag_subsystem_2s_own_engine_schema_orm(self) -> None:
        assert check_source("from app.db.scenario import Scenario\n") == []

    def test_does_not_flag_the_shared_chat_schema_orm(self) -> None:
        """Unit 21a (MEADOWOPS-DOM-014): pre-implementation security review
        of that unit considered and deliberately did not add app.db.chat to
        FORBIDDEN_MODULES — `chat` is PRD §7's second named exception (a
        store both subsystems' own API layer reads/writes), the same
        category this boundary already exempts `engine` from above, not
        Subsystem 1's protected `live` data this checker actually polices.
        A positive test, not just a docstring claim: proves the exemption
        is intentional and stays intentional if FORBIDDEN_MODULES is ever
        edited without re-reading this reasoning."""
        assert check_source("from app.db.chat import ChatThread\n") == []

    def test_does_not_flag_the_internal_client_helper_itself(self) -> None:
        assert check_source("from app.core.internal_client import build_subsystem2_client\n") == []

    def test_reports_the_correct_line_number(self) -> None:
        source = "import os\nimport sys\nimport app.db.session\n"
        violations = check_source(source)
        assert violations[0].line == 3

    def test_flags_a_relative_import_reaching_the_forbidden_module(self) -> None:
        """Code review of this unit, LOW: `node.module` for a relative
        import never carries the `app.` prefix, so an exact-string match
        alone silently let `from ...db.session import make_engine` through.
        `owning_module` (as `app.services.subsystem2.foo` would resolve to,
        for a hypothetical file at that path) lets the resolver reconstruct
        the real absolute target the same way Python itself would."""
        violations = check_source(
            "from ...db.session import make_engine\n",
            owning_module="app.services.subsystem2",
        )
        assert len(violations) == 1
        assert violations[0].forbidden_module == "app.db.session"

    def test_a_relative_import_with_no_owning_module_is_flagged_not_assumed_safe(self) -> None:
        violations = check_source("from . import something\n")
        assert len(violations) == 1
        assert violations[0].forbidden_module == "<unresolvable relative import>"


class TestRealSubsystem2Tree:
    def test_the_real_app_services_subsystem2_tree_has_no_violations(self) -> None:
        assert _SUBSYSTEM2_DIR.is_dir(), (
            "app/services/subsystem2 is the concrete namespace this boundary "
            "polices - it must exist, even as an empty scaffold, for this "
            "test to mean anything."
        )
        assert check_directory(_SUBSYSTEM2_DIR) == []


def _collect_dependency_calls(dependant) -> set:
    """Walks a FastAPI route's full dependency graph (require_admin's own
    Depends(require_authenticated) sub-dependency included), returning every
    distinct callable reachable from it."""
    calls: set = set()
    stack = [dependant]
    while stack:
        current = stack.pop()
        if current.call is not None:
            calls.add(current.call)
        stack.extend(current.dependencies)
    return calls


def _api_routes(app) -> list[APIRoute]:
    """This FastAPI version wraps `app.include_router(...)` results as lazy
    `_IncludedRouter` objects in `app.routes` that never flatten to their
    real `APIRoute`s until a request is actually dispatched through the app
    (a false alarm already hit once during Unit 19's live verification,
    mistaken there for a missing router registration) - `original_router`
    holds the real `APIRouter` with its own `.routes` regardless, so this
    reads through it directly instead of relying on dispatch-time
    resolution just to enumerate what's registered."""
    routes: list[APIRoute] = []
    for route in app.routes:
        original_router = getattr(route, "original_router", None)
        if original_router is not None:
            routes.extend(r for r in original_router.routes if isinstance(r, APIRoute))
        elif isinstance(route, APIRoute):
            routes.append(route)
    return routes


def _classify_routes() -> dict[tuple[str, str], str]:
    app = create_app(
        settings=Settings(
            session_secret_key="test-session-secret-value-at-least-32-bytes-long",
            internal_service_token="test-internal-service-token-value-at-least-32-bytes",
            database_url="postgresql+psycopg://placeholder/placeholder",
            sandbox_role_password="placeholder-password",
        )
    )
    result: dict[tuple[str, str], str] = {}
    for route in _api_routes(app):
        calls = _collect_dependency_calls(route.dependant)
        if require_admin in calls:
            classification = "admin_only"
        elif reject_service_role in calls:
            classification = "service_rejected"
        elif require_authenticated in calls:
            classification = "service_allowed"
        else:
            classification = "public"
        for method in route.methods - {"HEAD", "OPTIONS"}:
            result[(method, route.path)] = classification
    return result


# The explicit, consciously-maintained allowlist (security review of this
# unit, point 2): every route the internal-service credential can actually
# reach today. A new require_authenticated route joins "service_allowed"
# automatically the moment it's registered - if it shouldn't be reachable by
# Subsystem 2 (it does a write, or something else non-read), it needs
# reject_service_role, and this test's diff is what forces that decision.
EXPECTED_SERVICE_ALLOWED_ROUTES = {
    ("GET", "/api/v1/me"),
    ("GET", "/api/v1/admin/customers"),
    ("GET", "/api/v1/admin/products"),
    ("GET", "/api/v1/admin/warehouses"),
    ("GET", "/api/v1/admin/suppliers"),
    ("GET", "/api/v1/admin/carriers"),
    ("GET", "/api/v1/dashboard/executive"),
    ("GET", "/api/v1/dashboard/executive/trend"),
    ("GET", "/api/v1/dashboard/inventory"),
    ("GET", "/api/v1/dashboard/inventory/{product_id}/{warehouse_id}/transactions"),
    ("GET", "/api/v1/dashboard/suppliers"),
    ("GET", "/api/v1/dashboard/suppliers/{supplier_id}/purchase-orders"),
    ("GET", "/api/v1/dashboard/orders/purchase"),
    ("GET", "/api/v1/dashboard/orders/purchase/{purchase_order_id}"),
    ("GET", "/api/v1/dashboard/orders/sales"),
    ("GET", "/api/v1/dashboard/orders/sales/{sales_order_id}"),
    ("GET", "/api/v1/dashboard/shipments"),
    ("GET", "/api/v1/dashboard/exceptions"),
    ("GET", "/api/v1/dashboard/exceptions/{exception_flag_id}"),
}


class TestServiceCredentialRouteAllowlist:
    def test_service_allowed_routes_match_the_explicit_allowlist_exactly(self) -> None:
        classified = _classify_routes()
        actual_allowed = {path for path, cls in classified.items() if cls == "service_allowed"}
        assert actual_allowed == EXPECTED_SERVICE_ALLOWED_ROUTES

    def test_every_query_playground_route_is_explicitly_service_rejected(self) -> None:
        classified = _classify_routes()
        query_playground_routes = {
            path: cls for path, cls in classified.items() if path[1].startswith("/api/v1/query/")
        }
        assert query_playground_routes == {
            ("POST", "/api/v1/query/execute"): "service_rejected",
            ("POST", "/api/v1/query/cancel-confirmation"): "service_rejected",
            ("POST", "/api/v1/query/refresh-sandbox"): "service_rejected",
            ("GET", "/api/v1/query/history"): "service_rejected",
        }

    def test_every_chat_route_is_explicitly_classified(self) -> None:
        """Unit 21a (MEADOWOPS-DOM-014): the internal-service credential has
        no legitimate reason to touch chat at all (pre-implementation
        security review) — every route is service_rejected except thread
        creation, which is admin_only (DD-25: the Builder picks which
        thread to open), a stricter bucket that also excludes role=service
        (require_admin's own check). The `/ws/chat` WebSocket route isn't
        enumerable by `_classify_routes` (FastAPI dependency injection
        doesn't apply to WS routes at all) — its own auth story is proven
        directly in tests/api/test_chat_api.py's TestWebSocketConnection,
        not here."""
        classified = _classify_routes()
        chat_routes = {
            path: cls for path, cls in classified.items() if path[1].startswith("/api/v1/chat/")
        }
        assert chat_routes == {
            ("POST", "/api/v1/chat/ws-ticket"): "service_rejected",
            ("POST", "/api/v1/chat/threads"): "admin_only",
            ("GET", "/api/v1/chat/threads"): "service_rejected",
            ("GET", "/api/v1/chat/threads/{thread_id}/messages"): "service_rejected",
            ("POST", "/api/v1/chat/threads/{thread_id}/messages"): "service_rejected",
            # Unit 21 (MEADOWOPS-DOM-015): mark-thread-read, same
            # reasoning as every other chat route — no legitimate reason
            # for the internal-service credential to touch it.
            ("POST", "/api/v1/chat/threads/{thread_id}/read"): "service_rejected",
        }

    def test_health_and_login_are_public_not_service_allowed(self) -> None:
        classified = _classify_routes()
        assert classified[("GET", "/health")] == "public"
        assert classified[("POST", "/api/v1/auth/login")] == "public"

    def test_public_routes_match_the_explicit_allowlist_exactly(self) -> None:
        """Security review of this unit: the first three checks above only
        ever spot-checked that specific routes fall into a bucket, never
        that a bucket contains *only* what's expected. A route registered
        with no auth dependency at all (or a future router-level
        `dependencies=[...]` refactor that silently drops one) lands in
        "public" - reachable by literally anyone, the internal-service
        credential included - and every other test here still passes,
        since none of them assert the public set is closed. This is the
        same "route nobody enumerated" failure this unit exists to prevent,
        just in the one bucket the first pass left unpinned."""
        classified = _classify_routes()
        actual_public = {path for path, cls in classified.items() if cls == "public"}
        assert actual_public == {("GET", "/health"), ("POST", "/api/v1/auth/login")}
