"""A-1 / A-2 / A-3 / A-4：多 provider 后端注册、阈值分档、校准门控泛化、插件式注册。"""
import pytest

from skillforge import scorer

pytestmark = pytest.mark.d


def test_provider_local_st_returns_embedding_backend(skillforge_env):
    v = scorer.get_vectorizer()
    assert isinstance(v, scorer.EmbeddingBackend)
    assert scorer.is_dense_backend(v)


def test_provider_openai_without_api_url_falls_back(skillforge_env_openai_no_url):
    v = scorer.get_vectorizer("embedding", "openai")
    assert isinstance(v, scorer.LocalTfidfBackend)
    assert not scorer.is_dense_backend(v)


def test_register_vectorizer_custom(skillforge_env):
    class MyEmbed(scorer.EmbeddingBackend):
        pass

    scorer.register_vectorizer("my-embed", MyEmbed)
    assert "my-embed" in scorer._VECTORIZER_REGISTRY
    v = scorer.get_vectorizer("embedding", "my-embed")
    assert isinstance(v, MyEmbed)


def test_thresholds_embedding_tier(skillforge_env):
    # embedding 档（local-st 可用）→ 0.55 / 0.85
    assert scorer.conflict_default_threshold() == 0.55
    assert scorer.conflict_auto_deposit_threshold() == 0.85


def test_thresholds_local_tfidf_tier(skillforge_env_tfidf):
    # local-tfidf 档 → 0.7 / 0.9
    assert scorer.conflict_default_threshold() == 0.7
    assert scorer.conflict_auto_deposit_threshold() == 0.9


def test_calibrate_gating_local_st_available(skillforge_env):
    # A-3：local-st 指向本地推理端点，calibrate 门控不再看 api_url，直接 available:true
    from skillforge import evolve
    skillforge_env.make_skill("my-alpha", "处理用户订单退款与售后流程")
    skillforge_env.make_skill("my-beta", "生成Python数据可视化图表脚本")
    r = evolve.calibrate(limit=10)
    assert r.get("available") is True
    # 成功路径不应带 reason 字段（仅 available:false 才带 reason，且不再依赖 api_url 文案）
    assert r.get("reason") is None
