"""自进化后台自动循环控制器（B-1 / B-2 / B-3）。

设计要点（arch §3.2 / §7.4）：
- 进程内 asyncio 后台任务，按 EVOLVE_INTERVAL_MINUTES（默认 30）循环调用
  run_evolve(trigger="auto_loop")。
- 模块级互斥锁保证「手动触发 / 自动循环 / 开机钩子」三者同时仅一个 run_evolve 在跑；
  锁占用时新触发跳过（不写盘，防并发刷屏）。
- run_evolve 是同步阻塞函数，循环内用 asyncio.to_thread 包住，避免长任务阻塞事件循环。
- 状态单例通过 status() 只读暴露：running / last_run / next_run_in_sec / interval_min。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from . import config, evolve
from .filelock import FileLock

logger = logging.getLogger("skillforge.auto_loop")

# 模块级单例状态（arch §7.4）
_state: dict = {
    "enabled": False,
    "task": None,            # asyncio.Task | None
    "last_run": None,        # ISO-8601 UTC
    "interval_min": config.EVOLVE_INTERVAL_MINUTES,
}

# 互斥锁：延迟绑定到当前事件循环（避免跨 loop 绑定报错，见 _get_lock）。
_lock = None
_lock_loop = None


def _get_lock() -> asyncio.Lock:
    """取得当前事件循环的互斥锁（懒绑定，跨测试/多 loop 安全）。"""
    global _lock, _lock_loop
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if _lock is None or _lock_loop is not loop:
        _lock = asyncio.Lock()
        _lock_loop = loop
    return _lock


async def _loop() -> None:
    """后台周期任务：按 interval 循环调用 run_evolve(trigger='auto_loop')。

    任何异常吞掉仅记录，不中断循环；任务被 cancel 时正常退出。
    """
    global _state
    _state["enabled"] = True
    interval_min = _state["interval_min"]
    logger.info("自动循环已启动（周期 %d 分钟）", interval_min)
    while True:
        try:
            await asyncio.sleep(interval_min * 60)
            await run_once("auto_loop")
        except asyncio.CancelledError:
            break
        except Exception as e:  # noqa: BLE001
            logger.exception("自动循环本轮异常（已吞掉，继续循环）：%s", e)


async def _with_filelock(fn) -> dict:
    """跨进程文件锁包裹（C-2 / C-4）：先获取排他锁，占用则安全跳过（不阻塞不崩溃）。

    仅包裹 run_evolve 整体；获取成功后在进程内 asyncio.Lock 保护下 to_thread(fn)。
    锁占用（超时 FILELOCK_TIMEOUT_SEC）时返回跳过占位。
    """
    fl = FileLock(config.LOCK_PATH, timeout=config.FILELOCK_TIMEOUT_SEC)
    with fl:
        if not fl.acquired:
            logger.warning("跨进程锁获取超时，将安全跳过本轮")
            return {"ledger_new": [], "no_op": True, "skipped": True,
                    "reason": "cross-process lock occupied"}
        _state["last_run"] = datetime.now(timezone.utc).isoformat()
        async with _get_lock():
            return await asyncio.to_thread(fn)


async def run_once(trigger: str = "auto_loop") -> dict:
    """经锁保护运行一次 run_evolve（自动循环内部调用）。

    进程内 asyncio.Lock 占用（手动/开机钩子运行中）时立即跳过本轮（防并发，不写盘）；
    跨进程文件锁占用时由 _with_filelock 安全跳过。
    """
    lock = _get_lock()
    if lock.locked():
        return {"ledger_new": [], "no_op": True, "skipped": True,
                "reason": "run_evolve 已被手动/开机钩子占用，跳过本轮"}
    return await _with_filelock(lambda: evolve.run_evolve(None, trigger))


async def run_protected(fn) -> dict:
    """统一经锁保护调用任意 run_evolve 包装函数（手动/自动/开机三路共用）。

    fn 应为无参可调用，返回 run_evolve 结果 dict（在 to_thread 中同步执行）。
    进程内 asyncio.Lock 占用时立即跳过；跨进程文件锁占用时由 _with_filelock 安全跳过。
    所有 run_evolve 入口必须经此函数进入。
    """
    lock = _get_lock()
    if lock.locked():
        return {"ledger_new": [], "no_op": True, "skipped": True,
                "reason": "run_evolve 已被其它入口占用，跳过本次调用"}
    return await _with_filelock(fn)


def start() -> None:
    """启动后台周期任务（幂等：已在运行则直接返回）。

    C-1：改用 asyncio.get_running_loop().create_task(_loop())，符合 asyncio 规范，
    避免在无显式运行 loop 上下文时抛 DeprecationWarning。必须在运行中的事件循环内调用。
    """
    global _state
    task = _state.get("task")
    if task is not None and not task.done():
        return
    _state["interval_min"] = config.EVOLVE_INTERVAL_MINUTES
    _state["enabled"] = True
    _state["task"] = asyncio.get_running_loop().create_task(_loop())
    logger.info("自动循环启动请求已提交")


def stop() -> None:
    """取消后台周期任务。"""
    global _state
    _state["enabled"] = False
    task = _state.get("task")
    if task is not None and not task.done():
        task.cancel()
    _state["task"] = None
    logger.info("自动循环已停止")


def status() -> dict:
    """返回当前自动循环状态（只读暴露单例）。"""
    interval_min = _state["interval_min"]
    task = _state.get("task")
    running = bool(task is not None and not task.done())
    last_run = _state.get("last_run")
    next_run_in_sec = None
    if running and last_run:
        try:
            last_dt = datetime.fromisoformat(last_run)
            elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
            next_run_in_sec = max(0, int(interval_min * 60 - elapsed))
        except Exception:
            next_run_in_sec = None
    return {
        "running": running,
        "last_run": last_run,
        "next_run_in_sec": next_run_in_sec,
        "interval_min": interval_min,
    }
