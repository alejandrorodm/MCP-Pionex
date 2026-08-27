"""Every registered tool must declare MCP annotations consistent with its role."""

import asyncio

import pytest

from mcp_pionex.server import mcp

EXPECTED_TOOL_COUNT = 56


@pytest.fixture(scope="module")
def tools():
    return {t.name: t for t in asyncio.run(mcp.list_tools())}


def test_tool_count(tools):
    assert len(tools) == EXPECTED_TOOL_COUNT


def test_every_tool_has_annotations(tools):
    missing = [name for name, t in tools.items() if t.annotations is None]
    assert missing == []


def test_prepare_tools_are_non_destructive_and_not_read_only(tools):
    for name, t in tools.items():
        if name.startswith("prepare_"):
            a = t.annotations
            assert a.read_only_hint is False, name
            assert a.destructive_hint is False, name
            assert a.idempotent_hint is False, name


def test_executing_tools_are_destructive(tools):
    for name in ("confirm_action", "cancel_order"):
        a = tools[name].annotations
        assert a.read_only_hint is False
        assert a.destructive_hint is True
        assert a.idempotent_hint is True  # single-use token / already-cancelled


def test_reads_are_read_only(tools):
    for name, t in tools.items():
        if name.startswith(("get_", "list_", "detect_", "check_", "query_", "compute_")):
            assert t.annotations.read_only_hint is True, name
            assert t.annotations.destructive_hint is False, name


def test_meta_tools_are_closed_world(tools):
    for name in ("get_server_status", "get_safety_rules"):
        assert tools[name].annotations.open_world_hint is False


def test_every_description_documents_returns_and_args(tools):
    for name, t in tools.items():
        desc = t.description or ""
        assert "Returns" in desc, f"{name} lacks a Returns section"
        if (t.input_schema or {}).get("properties"):
            assert "Args" in desc, f"{name} lacks an Args section"
