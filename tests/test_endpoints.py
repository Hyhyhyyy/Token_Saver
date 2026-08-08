"""C-2 / D-2：ledger 过滤；GET/PUT /api/config/vectorizer 返回/接受 provider + backend_source。"""
import pytest

from fastapi.testclient import TestClient

from skillforge import evolve, server

pytestmark = pytest.mark.d


def test_ledger_filter_by_action_type(skillforge_env):
    skillforge_env.make_skill("my-alpha", "处理用户订单退款与售后流程")
    skillforge_env.make_skill("my-beta", "生成Python数据可视化图表脚本")
    evolve.run_evolve(trigger="t")
    client = TestClient(server.app)
    r = client.get("/api/evolve/ledger?action_type=gold_seed")
    assert r.status_code == 200
    entries = r.json()["entries"]
    assert entries, "应有 gold_seed 条目"
    assert all(e["action_type"] == "gold_seed" for e in entries)


def test_ledger_filter_by_time_window(skillforge_env):
    skillforge_env.make_skill("my-alpha", "处理用户订单退款与售后流程")
    evolve.run_evolve(trigger="t")
    client = TestClient(server.app)
    # 未来时间窗：不应返回任何历史条目
    r = client.get("/api/evolve/ledger?since=2999-01-01T00:00:00+00:00")
    assert r.status_code == 200
    assert r.json()["entries"] == []


def test_config_vectorizer_returns_provider(skillforge_env):
    client = TestClient(server.app)
    r = client.get("/api/config/vectorizer")
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "local-st"
    assert body["backend"] == "embedding"
    # D-2：新增 backend_source + ollama_available
    assert body["backend_source"] == "local-st"
    assert "ollama_available" in body

    # PUT 持久化 provider
    r2 = client.put(
        "/api/config/vectorizer",
        json={
            "backend": "embedding",
            "provider": "local-st",
            "embedding": {"api_url": skillforge_env.mock_url, "model": "nomic-embed-text"},
        },
    )
    assert r2.status_code == 200
    assert r2.json()["provider"] == "local-st"
