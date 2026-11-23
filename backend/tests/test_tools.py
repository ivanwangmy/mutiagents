from __future__ import annotations

import asyncio

import pytest

from app.agents.registry import registry
from app.skills.registry import (
    SkillInputError,
    SkillPermissionError,
    skills_registry,
)
from app.tools.base import ToolContext
from app.tools.builtin.calculator import calculate
from app.tools.builtin.datetime_tool import datetime_tool
from app.tools.builtin.python_sandbox import SandboxValidationError, run_python
from app.tools.permissions import tool_permission_manager
from app.tools.registry import tool_registry


def _profile(agent_id: str):
    registry.load()
    return registry.get(agent_id)


def test_tool_registry_has_three_real_tools() -> None:
    assert set(tool_registry.names()) == {"calculator", "datetime", "python_sandbox"}
    schemas = tool_registry.to_openai_tools()
    assert all(schema["type"] == "function" for schema in schemas)
    assert {schema["function"]["name"] for schema in schemas} == set(tool_registry.names())


def test_calculator_evaluates_real_expression() -> None:
    result = asyncio.run(calculate({"expression": "(123*45+678)/3"}))
    assert result == {"expression": "(123*45+678)/3", "value": 2071}
    with pytest.raises(ValueError):
        asyncio.run(calculate({"expression": "__import__('os')"}))
    with pytest.raises(ValueError):
        asyncio.run(calculate({"expression": ""}))


def test_datetime_returns_real_clock_data() -> None:
    result = asyncio.run(datetime_tool({"action": "now", "timezone": "Asia/Shanghai"}))
    assert result["timezone"] == "Asia/Shanghai"
    assert len(result["date"]) == 10
    assert result["weekday"].startswith("周")
    assert result["timestamp"] > 1700000000


def test_python_sandbox_executes_in_subprocess() -> None:
    result = asyncio.run(run_python({"code": "print(sum(range(10)))\nprint(__name__)"}))
    assert result["output"].splitlines() == ["45", "__sandbox__"]
    assert result["memory_limit_mb"] == 256
    assert result["timeout_seconds"] == 5.0


def test_python_sandbox_blocks_os_and_file_access() -> None:
    with pytest.raises(SandboxValidationError):
        asyncio.run(run_python({"code": "import os\nprint(os.getcwd())"}))
    with pytest.raises(SandboxValidationError):
        asyncio.run(run_python({"code": "print(open('secret.txt').read())"}))


def test_tool_permissions_match_personas() -> None:
    alex_tools = set(tool_permission_manager.tools_for(_profile("alex")))
    mia_tools = set(tool_permission_manager.tools_for(_profile("mia")))
    ethan_tools = set(tool_permission_manager.tools_for(_profile("ethan")))
    assert alex_tools == {"calculator", "datetime", "python_sandbox", "use_skill"}
    assert mia_tools == {"calculator", "datetime", "use_skill"}
    assert ethan_tools == {"calculator", "datetime", "python_sandbox", "use_skill"}


def test_tool_context_enforces_call_limits() -> None:
    context = ToolContext(
        agent_id="alex",
        task_id="t",
        conversation_id="c",
        max_calls={"calculator": 1},
    )
    assert context.can_call("calculator") == (True, None)
    context.record("calculator")
    allowed, reason = context.can_call("calculator")
    assert allowed is False and "上限" in (reason or "")
    assert context.can_call("python_sandbox")[0] is False


def test_skills_load_execute_and_are_permission_scoped() -> None:
    registry.load()
    skills_registry.load()
    alex = _profile("alex")
    execution = skills_registry.execute(alex, "concept_explanation", {"concept": "机会成本"})
    payload = execution.to_payload()
    assert payload["skill"] == "concept_explanation"
    assert len(payload["steps"]) >= 3
    assert "definition" in payload["output_fields"]
    assert [skill.name for skill in skills_registry.for_agent("mia")] == [
        "knowledge_organization",
        "problem_decomposition",
        "learning_assistance",
        "information_summarization",
        "knowledge_gap_detection",
        "explanation_adaptation",
    ]
    with pytest.raises(SkillPermissionError):
        skills_registry.execute(_profile("mia"), "concept_explanation", {"concept": "x"})
    with pytest.raises(ValueError):
        skills_registry.execute(alex, "concept_explanation", {})
    for profile in registry.all():
        assert all(skill.execution_logic for skill in profile.skills)


def test_skill_specs_have_complete_metadata() -> None:
    registry.load()
    skills_registry.load()
    for profile in registry.all():
        for skill in profile.skills:
            assert skill.id
            assert skill.version
            assert skill.category != "method"
            assert skill.trigger_conditions
            assert skill.limitations
            assert skill.error_handling
            assert skill.required_inputs


def test_skill_matching_prefers_concept_skill_for_definition_question() -> None:
    registry.load()
    skills_registry.load()
    alex = _profile("alex")
    matches = skills_registry.match(alex, "请解释什么是边际成本，并举例说明", limit=3)
    assert matches
    assert matches[0].skill.name == "concept_explanation"
    assert "concept" in [item.skill.category for item in matches]


def test_skill_missing_input_reports_required_field() -> None:
    registry.load()
    skills_registry.load()
    with pytest.raises(SkillInputError) as exc:
        skills_registry.execute(_profile("alex"), "concept_explanation", {})
    assert "concept" in str(exc.value)


def test_agent_behavior_policies_are_distinct() -> None:
    registry.load()
    alex = registry.get("alex")
    mia = registry.get("mia")
    ethan = registry.get("ethan")
    assert alex.behavior.decision_style != mia.behavior.decision_style
    assert mia.behavior.decision_style != ethan.behavior.decision_style
    assert alex.behavior.preferred_skills != ethan.behavior.preferred_skills
    assert "定义" in alex.system_prompt
    assert "拆解" in mia.system_prompt
    assert "反例" in ethan.system_prompt
