from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Callable


logger = logging.getLogger(__name__)


@dataclass
class DashboardStore:
    """Dashboard definition cache with a best-effort persistent backing store."""

    definitions: dict[str, dict]
    code_dashboards: dict[str, dict[str, Any]]
    create_dashboard: Callable[..., dict]
    get_dashboard: Callable[[str], dict | None]
    update_dashboard: Callable[..., dict | None]

    @staticmethod
    def tenant_id(payload: dict) -> str:
        return str(payload.get("tenant_id") or payload.get("owner_tenant_id") or "system").strip() or "system"

    @staticmethod
    def definition_from_code(dashboard: dict[str, Any]) -> dict:
        data_contract = dashboard.get("data_contract") or {}
        if not isinstance(data_contract, dict):
            data_contract = {}
        definition = {
            "dashboard_id": dashboard.get("dashboard_id"),
            "title": dashboard.get("title"),
            "description": dashboard.get("description"),
            "data_sources": data_contract.get("data_sources") or {},
            "metrics": data_contract.get("metrics") or {},
            "stages": data_contract.get("stages") or [],
            "widgets": data_contract.get("widgets") or [],
            "runtime_queries": data_contract.get("runtime_queries") or data_contract.get("queries") or {},
            "formulas": data_contract.get("formulas") or {},
            "filters": data_contract.get("filters") or [],
            "interactions": data_contract.get("interactions") or [],
            "layout": data_contract.get("layout") or {},
        }
        formulas = definition["formulas"]
        if isinstance(formulas, dict):
            for metric_id, formula in formulas.items():
                if metric_id not in definition["metrics"]:
                    expression = formula.get("expression") if isinstance(formula, dict) else str(formula)
                    definition["metrics"][metric_id] = {"source": "formula", "expression": expression}
        return definition

    def save_definition(self, definition: dict, dashboard_id: str | None = None) -> dict:
        resolved_id = str(dashboard_id or definition.get("dashboard_id") or "custom_dashboard")
        saved_definition = {**definition, "dashboard_id": resolved_id}
        self.definitions[resolved_id] = saved_definition
        self._persist_definition(saved_definition)
        return saved_definition

    def save_code(self, dashboard: dict[str, Any], dashboard_id: str | None = None) -> dict:
        resolved_id = str(dashboard_id or dashboard.get("dashboard_id") or "custom_code_dashboard")
        saved_dashboard = {**dashboard, "dashboard_id": resolved_id}
        self.code_dashboards[resolved_id] = saved_dashboard
        if isinstance(saved_dashboard.get("data_contract"), dict):
            self.definitions[resolved_id] = self.definition_from_code(saved_dashboard)
        self._persist_code(saved_dashboard)
        return saved_dashboard

    def _persist_definition(self, definition: dict) -> None:
        if not definition.get("dashboard_id"):
            return
        config = {
            "render_mode": "manifest",
            "definition": definition,
            "filters": definition.get("filters") or [],
            "data_sources": definition.get("data_sources") or {},
            "metrics": definition.get("metrics") or {},
            "charts": definition.get("charts") or [],
            "stages": definition.get("stages") or [],
            "widgets": definition.get("widgets") or [],
            "layout": definition.get("layout") or {},
            "interactions": definition.get("interactions") or [],
            "runtime_queries": definition.get("runtime_queries") or {},
            "formulas": definition.get("formulas") or {},
        }
        self._upsert(definition, config)

    def _persist_code(self, dashboard: dict) -> None:
        if not dashboard.get("dashboard_id"):
            return
        self._upsert(dashboard, {
            "render_mode": "code",
            "html": dashboard.get("html") or "",
            "css": dashboard.get("css") or "",
            "javascript": dashboard.get("javascript") or "",
            "data_contract": dashboard.get("data_contract") or {},
        })

    def _upsert(self, payload: dict, config: dict) -> None:
        tenant_id = self.tenant_id(payload)
        dashboard_id = str(payload.get("dashboard_id") or "")
        try:
            existing = self.get_dashboard(dashboard_id)
            if existing:
                self.update_dashboard(
                    str(existing.get("tenant_id") or tenant_id),
                    dashboard_id,
                    {
                        "title": payload.get("title"),
                        "description": payload.get("description"),
                        "config": config,
                        "refresh_policy": {"mode": "manual"},
                        "status": "active",
                    },
                )
                return
            self.create_dashboard(
                tenant_id=tenant_id,
                title=str(payload.get("title") or dashboard_id),
                description=payload.get("description"),
                config=config,
                snapshot={},
                refresh_policy={"mode": "manual"},
                dashboard_id=dashboard_id,
            )
        except Exception:
            logger.warning("Dashboard persistence failed for %s", dashboard_id, exc_info=True)

    def stored_row(self, dashboard_id: str) -> dict | None:
        try:
            row = self.get_dashboard(dashboard_id)
        except Exception:
            logger.warning("Dashboard lookup failed for %s", dashboard_id, exc_info=True)
            return None
        if not row or row.get("status") == "deleted":
            return None
        return row

    def stored_definition(self, dashboard_id: str) -> dict | None:
        row = self.stored_row(dashboard_id)
        config = (row or {}).get("config") or {}
        if config.get("render_mode") == "manifest" and isinstance(config.get("definition"), dict):
            return config["definition"]
        if config.get("render_mode") == "code":
            return self.definition_from_code({
                "dashboard_id": dashboard_id,
                "title": row.get("title"),
                "description": row.get("description"),
                "data_contract": config.get("data_contract") or {},
            })
        return None

    def stored_code(self, dashboard_id: str) -> dict | None:
        row = self.stored_row(dashboard_id)
        config = (row or {}).get("config") or {}
        if config.get("render_mode") != "code":
            return None
        return {
            "dashboard_id": dashboard_id,
            "title": row.get("title"),
            "description": row.get("description"),
            "html": config.get("html") or "",
            "css": config.get("css") or "",
            "javascript": config.get("javascript") or "",
            "data_contract": config.get("data_contract") or {},
        }

    def get_definition(self, dashboard_id: str) -> dict | None:
        return self.definitions.get(dashboard_id) or self.stored_definition(dashboard_id)

    def get_code(self, dashboard_id: str) -> dict | None:
        return self.code_dashboards.get(dashboard_id) or self.stored_code(dashboard_id)

    def runtime_definition(self, dashboard_id: str, default_definition: dict, context: dict | None = None) -> dict:
        if context and isinstance(context.get("manifest"), dict):
            definition = dict(context["manifest"])
            definition["dashboard_id"] = dashboard_id or definition.get("dashboard_id")
            return definition
        if context and isinstance(context.get("data_contract"), dict):
            return self.definition_from_code({"dashboard_id": dashboard_id, "data_contract": context["data_contract"]})
        definition = self.get_definition(dashboard_id)
        if definition:
            return definition
        code_dashboard = self.get_code(dashboard_id)
        if code_dashboard:
            return self.definition_from_code(code_dashboard)
        return {**default_definition, "dashboard_id": dashboard_id or default_definition["dashboard_id"]}

