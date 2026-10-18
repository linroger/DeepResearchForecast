"""Trusted-root legacy wrappers. Tool objects are constructed only on reflection."""
from __future__ import annotations

import json


def _client():
    if __package__:
        from .news_signals import get_context_client
    else:
        from news_signals import get_context_client
    return get_context_client()


def news_search_impl(query: str) -> str:
    """Discover dated news snippets; fetch publisher pages before full-text claims."""
    return json.dumps(_client().search_news(query), ensure_ascii=False, allow_nan=False)


def social_search_impl(query: str) -> str:
    """Find optional social discussion context, preserving provider availability."""
    return json.dumps(_client().search_social(query), ensure_ascii=False, allow_nan=False)


def market_compare_impl(query: str) -> str:
    """Compare attributed market candidates as context, without anchoring forecasts."""
    return json.dumps(_client().market_compare(query), ensure_ascii=False, allow_nan=False)


def __getattr__(name):
    functions = {"news_search_tool": ("news_search", news_search_impl),
                 "social_search_tool": ("social_search", social_search_impl),
                 "market_compare_tool": ("market_compare", market_compare_impl)}
    if name not in functions:
        raise AttributeError(name)
    try:
        from langchain_core.tools import StructuredTool
    except ImportError:
        return None
    tool_name, function = functions[name]
    tool = StructuredTool.from_function(function, name=tool_name)
    globals()[name] = tool
    return tool
