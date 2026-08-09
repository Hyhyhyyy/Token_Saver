"""D-1 / D-2：probe_ollama / ensure_default_vectorizer / resolve_backend_source。

验证：ollama 可用探测为 True、不可用为 False；首次启动复制 local-st 预设、不可用回退
local-tfidf、已存在 vectorizer.json 不被覆盖；backend_source 解析正确。零新增依赖。
"""
import pytest

from skillforge import config, scorer

pytestmark = pytest.mark.d


def test_probe_ollama_true_when_server_up(skillforge_env):
    assert scorer.probe_ollama(skillforge_env.mock_url) is True


def test_probe_ollama_false_when_server_down(skillforge_env_tfidf):
    assert scorer.probe_ollama("http://127.0.0.1:1/v1/embeddings", timeout=0.5) is False


def test_ensure_default_copies_preset_when_ollama_available(skillforge_env):
    config.VECTORIZER_PATH.unlink()  # 模拟首次启动（无 vectorizer.json）
    scorer.set_ollama_available(True)
    cfg = scorer.ensure_default_vectorizer()
    assert cfg["provider"] == "local-st"
    assert config.VECTORIZER_PATH.exists()
    # 落地内容为预设模板（provider=local-st）
    assert "local-st" in config.VECTORIZER_PATH.read_text()


def test_ensure_default_falls_back_when_ollama_down(skillforge_env_tfidf):
    config.VECTORIZER_PATH.unlink()
    scorer.set_ollama_available(False)
    cfg = scorer.ensure_default_vectorizer()
    assert cfg["backend"] == "local-tfidf"
    assert config.VECTORIZER_PATH.exists()


def test_ensure_default_does_not_overwrite_existing(skillforge_env):
    before = config.VECTORIZER_PATH.read_text()
    scorer.set_ollama_available(True)
    scorer.ensure_default_vectorizer()
    after = config.VECTORIZER_PATH.read_text()
    assert before == after  # 尊重用户已有配置，不覆盖


def test_resolve_backend_source(skillforge_env):
    src = scorer.resolve_backend_source()
    assert src["backend_source"] == "local-st"
    assert "ollama_available" in src and "provider" in src and "backend" in src
    # ollama 缓存为 None 时字段存在（bool|None）
    assert src["ollama_available"] is None or isinstance(src["ollama_available"], bool)


def test_probe_candidates_returns_first_available(skillforge_env):
    """D-3：首个可达候选胜出，返回其 url（短路，不探测后续不可用者）。"""
    urls = [skillforge_env.mock_url, "http://127.0.0.1:1/v1/embeddings"]
    assert scorer.probe_candidates(urls) == skillforge_env.mock_url


def test_probe_candidates_returns_none_when_all_down(skillforge_env_tfidf):
    """D-3：全部不可达返回 None。"""
    urls = ["http://127.0.0.1:1/v1/embeddings", "http://127.0.0.1:2/v1/embeddings"]
    assert scorer.probe_candidates(urls) is None


def test_ensure_default_probes_when_cache_none_and_available(skillforge_env):
    """R-2：_ollama_available 为 None（独立路径）且未传 candidate_url → 先探测设置缓存。
    候选可用 → 落地 local-st，缓存置 True。
    """
    scorer._ollama_available = None
    config.VECTORIZER_PATH.unlink()  # 模拟首次启动（无 vectorizer.json）
    # 注入候选列表为 mock 端点（独立路径：不传 candidate_url，先探测）
    scorer.config.EMBEDDING_CANDIDATE_URLS = [skillforge_env.mock_url]
    cfg = scorer.ensure_default_vectorizer()
    assert cfg["provider"] == "local-st"
    assert scorer._ollama_available is True
    assert config.VECTORIZER_PATH.exists()


def test_ensure_default_probes_when_cache_none_and_down(skillforge_env_tfidf):
    """R-2：_ollama_available 为 None（独立路径）探测全不可达 → 缓存置 False，回退 local-tfidf。"""
    scorer._ollama_available = None
    config.VECTORIZER_PATH.unlink()  # 模拟首次启动（无 vectorizer.json）
    scorer.config.EMBEDDING_CANDIDATE_URLS = ["http://127.0.0.1:1/v1/embeddings"]
    cfg = scorer.ensure_default_vectorizer()
    assert cfg["backend"] == "local-tfidf"
    assert scorer._ollama_available is False
    assert config.VECTORIZER_PATH.exists()
