from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app.agents.registry import registry
from app.main import app

FRONTEND_AVATARS = Path(__file__).resolve().parents[2] / "frontend" / "public" / "agents"


def test_registry_loads_three_fixed_agents() -> None:
    registry.load()
    assert [p.id for p in registry.all()] == ["alex", "mia", "ethan"]
    assert registry.is_loaded()


def test_each_agent_has_independent_prompt_and_config() -> None:
    registry.load()
    prompts = [p.system_prompt for p in registry.all()]
    assert len(set(prompts)) == 3
    assert all(len(p) > 800 for p in prompts)
    assert len({p.system_prompt_path for p in registry.all()}) == 3
    assert len({p.runtime.temperature for p in registry.all()}) == 3
    assert len({p.runtime.max_output_tokens for p in registry.all()}) == 3
    assert len({f"agents/{p.id}/memories" for p in registry.all()}) == 3


def test_participant_validation_is_strict() -> None:
    registry.load()
    assert registry.validate_participants(["alex", "alex"]) == ["alex"]
    try:
        registry.validate_participants([])
    except ValueError:
        pass
    else:
        raise AssertionError("空参与者应被拒绝")
    try:
        registry.validate_participants(["alex", "unknown"])
    except ValueError:
        pass
    else:
        raise AssertionError("未知 Agent 应被拒绝")


def test_avatar_assets_exist_and_are_square_png() -> None:
    for agent_id in ("alex", "mia", "ethan"):
        path = FRONTEND_AVATARS / f"{agent_id}.png"
        assert path.exists(), path
        with Image.open(path) as img:
            assert img.format == "PNG"
            assert img.size == (1024, 1024)


def test_agents_api_matches_registry_and_avatar_paths() -> None:
    with TestClient(app) as client:
        resp = client.get("/api/agents")
        assert resp.status_code == 200
        agents = resp.json()
        assert [a["id"] for a in agents] == ["alex", "mia", "ethan"]
        for agent in agents:
            assert agent["avatar"] == f"/agents/{agent['id']}.png"
            assert (FRONTEND_AVATARS / f"{agent['id']}.png").exists()
            assert agent["skills"]
            assert all(skill["execution_logic"] for skill in agent["skills"])
            assert agent["tool_permissions"]
        assert client.get("/api/agents/unknown").status_code == 404
