"""C-1 / B-2：evolution_metrics 表写入 + GET /api/evolve/trends 升序 + 空数据。"""
import pytest

from fastapi.testclient import TestClient

from skillforge import evolve, server, simbank

pytestmark = pytest.mark.b


def test_metrics_empty_initially(skillforge_env):
    assert simbank.get_evolution_metrics() == []


def test_metrics_written_and_ascending(skillforge_env):
    skillforge_env.make_skill("my-alpha", "处理用户订单退款与售后流程")
    skillforge_env.make_skill("my-beta", "生成Python数据可视化图表脚本")
    evolve.run_evolve(trigger="t")
    pts = simbank.get_evolution_metrics()
    assert len(pts) == 1
    assert 0 <= pts[0]["gold_coverage"] <= 100
    assert "f1_acc_before" in pts[0] and "f1_acc_after" in pts[0]

    # 新增一个技能触发第二轮（非 no-op）→ 第二行指标
    skillforge_env.make_skill("my-gamma", "整理会议纪要与待办清单")
    evolve.run_evolve(trigger="t")
    pts2 = simbank.get_evolution_metrics()
    assert len(pts2) == 2
    # 按 ts 升序
    assert pts2[0]["ts"] <= pts2[1]["ts"]


def test_trends_endpoint(skillforge_env):
    skillforge_env.make_skill("my-alpha", "处理用户订单退款与售后流程")
    skillforge_env.make_skill("my-beta", "生成Python数据可视化图表脚本")
    evolve.run_evolve(trigger="t")
    client = TestClient(server.app)
    r = client.get("/api/evolve/trends?limit=10")
    assert r.status_code == 200
    points = r.json()["points"]
    assert len(points) >= 1
    assert "gold_coverage" in points[0]
    assert "f1_acc_before" in points[0]
