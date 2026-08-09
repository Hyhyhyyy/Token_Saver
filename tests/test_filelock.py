"""C-2 / C-4：跨进程文件锁获取/释放/占用跳过/超时降级/禁用。

纯 Python 标准库（fcntl/msvcrt）行为验证，零新增依赖。同进程内第二个 fd 持锁时
第二个 FileLock 会阻塞至超时（acquired=False），与跨进程语义一致。
"""
import logging

import pytest

from skillforge import filelock

pytestmark = pytest.mark.c


def test_acquire_and_release(tmp_path):
    p = tmp_path / ".skillforge.lock"
    fl = filelock.FileLock(p, timeout=1.0)
    with fl:
        assert fl.acquired is True
    # 释放后可再次获取
    with fl:
        assert fl.acquired is True


def test_enabled_false_does_not_block(tmp_path):
    p = tmp_path / ".skillforge.lock"
    fl = filelock.FileLock(p, timeout=1.0, enabled=False)
    with fl:
        assert fl.acquired is True


def test_occupied_returns_skipped(tmp_path):
    p = tmp_path / ".skillforge.lock"
    fl1 = filelock.FileLock(p, timeout=2.0)
    fl1.__enter__()
    try:
        fl2 = filelock.FileLock(p, timeout=0.3)
        with fl2:
            # 锁被占用 → 超时后 acquired=False（安全跳过，不崩溃）
            assert fl2.acquired is False
    finally:
        fl1.__exit__(None, None, None)
    # 释放后再次获取应成功
    with filelock.FileLock(p, timeout=1.0) as fl3:
        assert fl3.acquired is True


def test_timeout_logs_warning(caplog, tmp_path):
    """C-4：锁获取超时（acquired=False）应记录 logger.warning，且不崩溃（降级跳过）。"""
    p = tmp_path / ".skillforge.lock"
    fl1 = filelock.FileLock(p, timeout=2.0)
    fl1.__enter__()
    try:
        with caplog.at_level(logging.WARNING, logger="skillforge.filelock"):
            fl2 = filelock.FileLock(p, timeout=0.3)
            with fl2:
                assert fl2.acquired is False
            # 超时降级分支已记录 warning（便于排查并发争用）
            assert any("跨进程锁获取超时" in rec.message for rec in caplog.records)
    finally:
        fl1.__exit__(None, None, None)
    # 释放后再次获取应成功（降级返回跳过占位，不破坏后续运行）
    with filelock.FileLock(p, timeout=1.0) as fl3:
        assert fl3.acquired is True


def test_lock_path_used(tmp_path):
    p = tmp_path / "sub" / ".lock"
    with filelock.FileLock(p, timeout=1.0) as fl:
        assert fl.acquired is True
        assert p.exists()
