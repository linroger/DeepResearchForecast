"""Legacy reflected FMP tools, bound to the trusted research run at preparation."""
from __future__ import annotations

_runtime = None
_fetch_runtime = None


def bind_runtime(callback, fetch_callback=None):
    global _runtime, _fetch_runtime
    _runtime = callback
    _fetch_runtime = fetch_callback


def read_capture(url):
    """Reserved correlation URLs never fall through to a public web request."""
    if _fetch_runtime is None:
        return "FETCH_FAILED(fmp_capture_corrupt): no trusted captured response."
    return _fetch_runtime(url)


def fmp_search_tools_impl(query: str) -> str:
    """Discover official FMP MCP names and input schemas for financial data and news."""
    if _runtime is None:
        return "FMP_UNAVAILABLE[disabled]: no trusted research run."
    return _runtime("fmp_search_tools", query=query)


def fmp_call_impl(tool: str, arguments: str) -> str:
    """Call a discovered official FMP tool using a JSON object argument string."""
    if _runtime is None:
        return "FMP_UNAVAILABLE[disabled]: no trusted research run."
    return _runtime("fmp_call", tool=tool, arguments=arguments)


def __getattr__(name):
    implementations = {"fmp_search_tools_tool": ("fmp_search_tools", fmp_search_tools_impl),
                       "fmp_call_tool": ("fmp_call", fmp_call_impl)}
    if name not in implementations:
        raise AttributeError(name)
    try:
        from langchain_core.tools import StructuredTool
    except ImportError:
        return None
    tool_name, function = implementations[name]
    result = StructuredTool.from_function(function, name=tool_name)
    globals()[name] = result
    return result


def register(client, *, enabled):
    """Augment old native configurations, preserving custom tools and explicit denies."""
    names = ("fmp_search_tools", "fmp_call")
    app = getattr(client, "_app_config", None)
    configs = getattr(app, "tools", None)
    agents = getattr(getattr(app, "subagents", None), "custom_agents", None)
    if getattr(client, "_agent", None) is not None or not isinstance(configs, list) or agents is None:
        return {"status": "unavailable", "reason": "unsupported_or_started_config", "available_tools": []}
    requested = list(names) if enabled else []
    disabled = set(getattr(app, "_drf_disabled_fmp_tools", ()))
    disabled.update(r.name for r in configs if r.name in names
                    and r.use == f"fmp_tools:{r.name}_tool" and getattr(r, "enabled", True) is False)
    setattr(app, "_drf_disabled_fmp_tools", tuple(sorted(disabled)))
    requested = [name for name in requested if name not in disabled]
    guardrails = getattr(app, "guardrails", None)
    if getattr(guardrails, "enabled", False):
        provider = getattr(guardrails, "provider", None)
        if getattr(provider, "use", "") != "deerflow.guardrails.builtin:AllowlistProvider":
            requested = []
        else:
            policy = provider.config
            requested = [n for n in requested if n not in (policy.get("denied_tools") or ())
                         and (policy.get("allowed_tools") is None or n in policy["allowed_tools"])]
    scoped = agents.get("scoped-researcher")
    canonical = lambda row: row.name in names and row.use == f"fmp_tools:{row.name}_tool"
    configs[:] = [r for r in configs if not canonical(r) or r.name in requested]
    if scoped is not None and scoped.tools is not None:
        scoped.tools = [n for n in scoped.tools if n not in names or n in requested]
    if not requested:
        return {"status": "disabled", "reason": "no_permitted_fmp_tools", "available_tools": []}
    conflicts = [n for n in requested if sum(r.name == n for r in configs) > 1
                 or any(r.name == n and not canonical(r) for r in configs)]
    if conflicts:
        configs[:] = [r for r in configs if not canonical(r)]
        return {"status": "unavailable", "reason": "tool_name_conflict", "available_tools": []}
    if any(getattr(__getattr__(n + "_tool"), "name", None) != n for n in requested):
        configs[:] = [r for r in configs if not canonical(r)]
        return {"status": "unavailable", "reason": "implementation_unavailable", "available_tools": []}
    from deerflow.config.tool_config import ToolConfig
    configs.extend(ToolConfig(name=n, group="web", use=f"fmp_tools:{n}_tool")
                   for n in requested if not any(r.name == n for r in configs))
    scoped_names = []
    if scoped is not None:
        scoped_names = [n for n in requested if scoped.tools != [] and n not in (scoped.disallowed_tools or ())]
        if scoped.tools is not None:
            scoped.tools = [n for n in scoped.tools if n not in names or n in scoped_names]
            scoped.tools += [n for n in scoped_names if n not in scoped.tools]
        if scoped_names:
            try:
                from .fmp_research import GUIDANCE
            except ImportError:
                from fmp_research import GUIDANCE
            if GUIDANCE not in scoped.system_prompt:
                scoped.system_prompt += "\n\n" + GUIDANCE
    return {"status": "ready" if len(scoped_names) == len(requested) else "partial",
            "reason": "registered", "available_tools": requested, "scoped_tools": scoped_names}
