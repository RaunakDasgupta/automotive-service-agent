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


class ShiftActivityInput(BaseModel):
    day_offset: int = Field(default=0,
                            description="0 today, -1 yesterday, -2 the day before")
    shift: str = Field(default="", description="MORNING, AFTERNOON, or empty for both")
    view: str = Field(default="people",
                      description="people = who worked; vehicles = which cars")


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
    ("get_shift_activity",      T.get_shift_activity,      ShiftActivityInput),
]


if NAT_AVAILABLE:
    import os
    import types

    def _register(tool_name, fn, schema):
        """One NAT function type per tool.

        The previous shape - one registered type yielding ten FunctionInfo -
        exposed exactly one of them. `register_function` wraps an ASYNC
        GENERATOR whose single yield is the context-manager boundary: what
        comes before it is setup, what comes after is teardown, and the yielded
        value is THE function. Yielding ten does not register ten; it registers
        the first and drops the rest, and the agent is then told to call a tool
        name that resolves to nothing.

        The config class is built with types.new_class because
        FunctionBaseConfig takes its registered name as a class keyword, which
        the three-argument form of type() cannot pass.
        """
        cfg_cls = types.new_class(
            f"{tool_name.title().replace('_', '')}Config",
            (FunctionBaseConfig,),
            {"name": f"asoia_{tool_name}"},
            lambda ns: ns.update({
                "__doc__": f"Configuration for the {tool_name} tool.",
                "__annotations__": {"db_path": str},
                "db_path": Field(
                    default="data/generated/service.sqlite",
                    description="SQLite database produced by notebook 01"),
            }),
        )

        async def _build(config, builder: "Builder", _fn=fn, _schema=schema,
                         _name=tool_name):
            os.environ.setdefault("ASOIA_DB", config.db_path)

            async def _run(payload):
                return _fn(**payload.model_dump(exclude_none=True))

            _run.__annotations__ = {"payload": _schema, "return": dict}

            yield FunctionInfo.from_fn(
                _run, input_schema=_schema,
                description=(_fn.__doc__ or _name).strip())

        register_function(config_type=cfg_cls)(_build)
        return cfg_cls

    NAT_TYPES = {name: _register(name, fn, schema)
                 for name, fn, schema in REGISTRY}
