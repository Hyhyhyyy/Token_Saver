"""跨进程文件锁（C-2 / C-4 · 零依赖，仅标准库）。

- POSIX 用 fcntl.flock；Windows 用 msvcrt.locking。
- 锁文件默认 DATA_DIR/.skillforge.lock（由 config.LOCK_PATH 提供）。
- 仅包裹 run_evolve 整体（不锁读操作），与进程内 asyncio.Lock 共存。
- 获取超时（config.FILELOCK_TIMEOUT_SEC）后 __enter__ 返回 self 且 acquired=False，
  调用方据此安全跳过（不阻塞、不崩溃）。enabled=False 时直接 acquired=True（测试可禁用）。
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

logger = logging.getLogger("skillforge.filelock")

if sys.platform == "win32":  # pragma: no cover - 仅在 Windows 执行
    import msvcrt

    def _acquire(fh, timeout: float) -> bool:
        start = time.time()
        while True:
            try:
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                return True
            except OSError:
                if time.time() - start >= timeout:
                    return False
                time.sleep(0.05)

    def _release(fh) -> None:
        try:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass

else:  # pragma: no cover - 仅在 POSIX 执行
    import fcntl

    def _acquire(fh, timeout: float) -> bool:
        start = time.time()
        while True:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except OSError:
                if time.time() - start >= timeout:
                    return False
                time.sleep(0.05)

    def _release(fh) -> None:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass


class FileLock:
    """跨进程排他锁上下文管理器。

    用法：
        with FileLock(config.LOCK_PATH, timeout=config.FILELOCK_TIMEOUT_SEC) as fl:
            if not fl.acquired:
                return {"skipped": True, ...}  # 锁占用，安全跳过
            ...  # 运行 run_evolve
    """

    def __init__(self, lock_path: Path, timeout: float = 5.0, enabled: bool = True) -> None:
        self._lock_path = Path(lock_path)
        self._timeout = float(timeout)
        self._enabled = bool(enabled)
        self._fh = None
        self._acquired = False

    def __enter__(self) -> "FileLock":
        if not self._enabled:
            # 测试可禁用锁：直接视为已获取，不触碰文件系统
            self._acquired = True
            return self
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self._lock_path, "a+")
        if _acquire(self._fh, self._timeout):
            self._acquired = True
        else:
            # 超时未获取：占用中，安全跳过（C-4：记录 warning 便于排查并发争用）
            self._acquired = False
            logger.warning("跨进程锁获取超时，将安全跳过本轮")
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None
        return self

    def __exit__(self, *exc) -> None:
        if self._fh is not None:
            try:
                _release(self._fh)
            except OSError:
                pass
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None
        self._acquired = False

    @property
    def acquired(self) -> bool:
        """是否成功获取锁（超时/占用为 False；enabled=False 时为 True）。"""
        return self._acquired
