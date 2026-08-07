"""SkillForge v2.2 测试 fixtures（D-2 · 全量回归）。

全部用例固定合成 fixture、mock embedding（stdlib http.server + threading，零新增依赖），
不依赖真实 ~/.workbuddy/skills 与真实远程 API。每个测试前重置 DATA_DIR 并重新导入 skillforge 包，
确保隔离与可重复。
"""
from __future__ import annotations

import json
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest


def _deterministic_vec(text: str, dim: int = 128) -> list[float]:
    """确定性稠密向量：按字符 codepoint 落入 dim 个桶计数，L2 归一化。

    相同文本 → 相同向量（cosine=1.0，用于冲突命中）；不同文本（字符集不同）→ 近正交
    （cosine≈0，用于无冲突 / no-op 场景）。
    """
    vec = [0.0] * dim
    for ch in text or "":
        vec[ord(ch) % dim] += 1.0
    norm = sum(v * v for v in vec) ** 0.5
    if norm == 0:
        return [0.0] * dim
    return [v / norm for v in vec]


class MockEmbeddingServer:
    """OpenAI 兼容 embeddings mock（仅返回确定性稠密向量，零依赖）。"""

    def __init__(self):
        self._server = None
        self._thread = None
        self._port = 0

    def _make_handler(self):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(handler):
                length = int(handler.headers.get("Content-Length", 0) or 0)
                body = handler.rfile.read(length) if length else b""
                try:
                    payload = json.loads(body) if body else {}
                except Exception:
                    payload = {}
                inp = payload.get("input", "")
                texts = inp if isinstance(inp, list) else [inp]
                data = [
                    {"object": "embedding", "index": i,
                     "embedding": _deterministic_vec(str(t))}
                    for i, t in enumerate(texts)
                ]
                out = json.dumps(
                    {"object": "list", "data": data,
                     "model": payload.get("model", "mock")}
                ).encode("utf-8")
                handler.send_response(200)
                handler.send_header("Content-Type", "application/json")
                handler.send_header("Content-Length", str(len(out)))
                handler.end_headers()
                handler.wfile.write(out)

            def log_message(self, *args):
                pass

        return Handler

    def start(self):
        self._server = HTTPServer(("127.0.0.1", 0), self._make_handler())
        self._port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        if self._server is not None:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:
                pass

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._port}/v1/embeddings"


def _reset_skillforge():
    """删除已缓存的 skillforge 子模块并重新导入，使 config 重新读取当前 DATA_DIR 环境变量。"""
    import sys
    for name in list(sys.modules):
        if name == "skillforge" or name.startswith("skillforge."):
            del sys.modules[name]
    import skillforge  # noqa: F401
    import skillforge.config  # noqa: F401
    import skillforge.scorer  # noqa: F401
    import skillforge.simulator  # noqa: F401
    import skillforge.simbank  # noqa: F401
    import skillforge.gold  # noqa: F401
    import skillforge.budget  # noqa: F401
    import skillforge.custom_rules  # noqa: F401
    import skillforge.evolve  # noqa: F401
    import skillforge.auto_loop  # noqa: F401
    import skillforge.server  # noqa: F401
    return skillforge


def _make_env(tmp_path, monkeypatch, mock_url, backend_cfg_factory):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("USER_SKILLS_DIR", str(skills_dir))
    monkeypatch.setenv("SKILLS_DIRS", str(skills_dir))
    monkeypatch.setenv("AUTO_EVOLVE_LOOP", "false")
    monkeypatch.setenv("AUTO_EVOLVE_ON_START", "false")
    (data_dir / "vectorizer.json").write_text(
        json.dumps(backend_cfg_factory(mock_url), ensure_ascii=False), encoding="utf-8"
    )
    pkg = _reset_skillforge()

    ns = types.SimpleNamespace()
    ns.pkg = pkg
    ns.skills_dir = skills_dir
    ns.data_dir = data_dir
    ns.mock_url = mock_url

    def make_skill(name, desc, body="示例正文内容"):
        d = skills_dir / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {desc}\n---\n{body}\n",
            encoding="utf-8",
        )
        return d

    ns.make_skill = make_skill
    return ns


@pytest.fixture
def skillforge_env(tmp_path, monkeypatch):
    """embedding 后端（provider=local-st 指向 MockEmbeddingServer）。"""
    srv = MockEmbeddingServer().start()
    try:
        def cfg(mock_url):
            return {
                "backend": "embedding",
                "provider": "local-st",
                "embedding": {"api_url": mock_url, "model": "nomic-embed-text"},
            }

        yield _make_env(tmp_path, monkeypatch, srv.url, cfg)
    finally:
        srv.stop()


@pytest.fixture
def skillforge_env_tfidf(tmp_path, monkeypatch):
    """local-tfidf 后端（稀疏，无 embedding，阈值分档为 tfidf 档）。"""
    def cfg(_mock_url):
        return {"backend": "local-tfidf"}

    yield _make_env(tmp_path, monkeypatch, "", cfg)
