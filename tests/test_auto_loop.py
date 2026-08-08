"""B-1 / B-2 / C-1 / C-2：后台周期自动循环 start/stop/status、互斥锁、run_once 写盘、文件锁。"""
import asyncio

import pytest

from skillforge import auto_loop

pytestmark = pytest.mark.c


def test_auto_loop_start_stop_status(skillforge_env):
    # C-1：start() 改为 asyncio.get_running_loop().create_task，需在运行中的事件循环内调用
    async def go():
        assert auto_loop.status()["running"] is False
        auto_loop.start()
        assert auto_loop.status()["running"] is True
        auto_loop.stop()
        assert auto_loop.status()["running"] is False

    asyncio.run(go())


def test_run_once_writes_auto_loop_trigger(skillforge_env):
    from skillforge import simbank
    skillforge_env.make_skill("my-alpha", "处理用户订单退款与售后流程")
    skillforge_env.make_skill("my-beta", "生成Python数据可视化图表脚本")

    async def go():
        return await auto_loop.run_once("auto_loop")

    res = asyncio.run(go())
    assert "ledger_new" in res
    # 自动循环条目 trigger=auto_loop
    ledger = simbank.get_ledger(action_type="gold_seed", limit=50)
    assert any(e["trigger"] == "auto_loop" for e in ledger["entries"])


def test_mutex_serializes_concurrent_runs(skillforge_env):
    from skillforge import evolve
    skillforge_env.make_skill("my-alpha", "处理用户订单退款与售后流程")
    skillforge_env.make_skill("my-beta", "生成Python数据可视化图表脚本")

    async def two():
        r1 = asyncio.ensure_future(
            auto_loop.run_protected(lambda: evolve.run_evolve(trigger="t1")))
        r2 = asyncio.ensure_future(
            auto_loop.run_protected(lambda: evolve.run_evolve(trigger="t2")))
        return await asyncio.gather(r1, r2)

    res1, res2 = asyncio.run(two())
    # 互斥锁保证同时仅一个 run_evolve 真正执行，另一个被跳过
    executed = [r for r in (res1, res2) if not r.get("skipped")]
    assert len(executed) == 1
