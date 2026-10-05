"""NeMo Agent Toolkit registration for the service-operations tools.

The tools in app/agent/tools.py are plain typed Python functions so they stay
testable and reusable. This module wraps them for NeMo Agent Toolkit (aiqtoolkit)
without changing them. If the toolkit is not installed, importing this module
does nothing and the agent runs on its own router - so the demo never depends on
the wrapper being present.
"""
from __future__ import annotations
from pydantic import BaseModel, Field

from app.agent import tools as T

try:
    # nvidia-nat is the package; `aiq` is a deprecated shim over it that warns
    # on every import. Prefer the real namespace, fall back for older installs.
    try:
        from nat.builder.builder import Builder
        from nat.builder.function_info import FunctionInfo
        from nat.cli.register_workflow import register_function
        from nat.data_models.function import FunctionBaseConfig
    except ImportError:
        from aiq.builder.builder import Builder
        from aiq.builder.function_info import FunctionInfo
        from aiq.cli.register_workflow import register_function
        from aiq.data_models.function import FunctionBaseConfig
    NAT_AVAILABLE = True
except ImportError:                                    # toolkit not installed
    NAT_AVAILABLE = False


# --- argument schemas -------------------------------------------------------
class RoInput(BaseModel):
    ro_number: str = Field(description="Repair order number, e.g. RO-26-08165")


class RoWindowInput(BaseModel):
    ro_number: str = Field(description="Repair order number")
    since_hours: int = Field(default=12, description="Look-back window in hours")


class ListInput(BaseModel):
    filter: str = Field(default="active",
                        description="active|blocked|at_risk|safety|waiter|all, "
                                    "or a lifecycle state such as PARTS_HOLD")
    limit: int = Field(default=25)


class StaffInput(BaseModel):
    staff_id: str = Field(description="Staff id, e.g. EMP014")
    days: int = Field(default=7)


class ShiftInput(BaseModel):
    shift: str = Field(default="AFTERNOON", description="MORNING or AFTERNOON")


class DaysInput(BaseModel):
    days: int = Field(default=7)


class SearchInput(BaseModel):
    query: str = Field(description="Natural-language search over technician updates")
    k: int = Field(default=4)
    ro_number: str | None = Field(default=None)


class OpInput(BaseModel):
    op_code: str = Field(description="Labour operation code, e.g. BRK-FR-PAD")


# Every tool, its schema, and a one-line description for the planner.
REGISTRY = [
    ("get_ro_state",            T.get_ro_state,            RoInput),
    ("get_ro_timeline",         T.get_ro_timeline,         RoInput),
    ("list_ros",                T.list_ros,                ListInput),
    ("get_technician_activity", T.get_technician_activity, StaffInput),
    ("generate_handover",       T.generate_handover,       ShiftInput),
    ("detect_anomalies",        T.detect_anomalies,        DaysInput),
    ("diff_ro",                 T.diff_ro,                 RoWindowInput),
    ("search_updates",          T.search_updates,          SearchInput),
    ("get_op_code_info",        T.get_op_code_info,        OpInput),
]


if NAT_AVAILABLE:

    class ServiceOpsConfig(FunctionBaseConfig, name="service_ops_tools"):
        """Configuration for the service-operations tool group."""
        db_path: str = Field(default="data/generated/service.sqlite",
                             description="SQLite database produced by notebook 01")

    @register_function(config_type=ServiceOpsConfig)
    async def service_ops_tools(config: ServiceOpsConfig, builder: Builder):
        """Expose every service-operations tool to NeMo Agent Toolkit."""
        import os
        os.environ.setdefault("ASOIA_DB", config.db_path)

        for name, fn, schema in REGISTRY:
            async def _run(payload, _fn=fn):
                return _fn(**payload.model_dump(exclude_none=True))

            yield FunctionInfo.from_fn(
                _run, input_schema=schema,
                description=(fn.__doc__ or name).strip())
