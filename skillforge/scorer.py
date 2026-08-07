"""统一向量/打分后端（F1 调度模拟 与 F3 冲突检测 共用）。

设计要点：
- 抽象接口 `VectorizerBackend`：score(query, desc) 与 similarity(a, b)、shared_keywords(a, b)。
- `LocalTfidfBackend`（默认）：字符 2~3 gram + TF-IDF + 余弦，纯 Python（仅 math / re），零依赖。
- `EmbeddingBackend`（可选）：标准库 urllib 调用可配置 embedding API，失败回退本地。
- `get_vectorizer()`：读 DATA_DIR/vectorizer.json 选择后端；默认 local-tfidf。
所有打分确定性（同输入同输出），F1 控制变量下前后两次使用同一向量化器实例。
"""
from __future__ import annotations

import json
import math
import os
import re
import urllib.request

from .config import (
    VECTORIZER_PATH,
    EMBEDDING_API_URL,
    CONFLICT_DEFAULT_THRESHOLD,
    CONFLICT_DEFAULT_THRESHOLD_EMBEDDING,
    CONFLICT_AUTO_DEPOSIT_THRESHOLD,
    CONFLICT_AUTO_DEPOSIT_THRESHOLD_EMBEDDING,
)

_NORM_RE = re.compile(r"\s+")


def _norm(text: str) -> str:
    """小写并折叠空白，作为 n-gram 提取前的归一。"""
    return _NORM_RE.sub("", (text or "").lower())


def _ngrams(text: str, ns=(2, 3)) -> list[str]:
    """字符 n-gram（默认 2 与 3），中英文混合通用。"""
    t = _norm(text)
    grams = []
    for n in ns:
        for i in range(len(t) - n + 1):
            grams.append(t[i:i + n])
    return grams


def _cosine(a: dict, b: dict) -> float:
    """两个稀疏向量（dict）的余弦相似度，落在 [0,1]。"""
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    if not common:
        return 0.0
    num = sum(a[k] * b[k] for k in common)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0 or nb == 0:
        return 0.0
    return num / (na * nb)


def _cosine_vec(a: list, b: list) -> float:
    """两个稠密向量（list）的余弦相似度。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    num = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return num / (na * nb)


def _shared_ngrams(a: str, b: str, top: int = 5) -> list[str]:
    """取两文本共享的 n-gram（按长度降序，优先更具区分度的长片断）。"""
    shared = set(_ngrams(a)) & set(_ngrams(b))
    if not shared:
        return []
    return sorted(shared, key=lambda g: len(g), reverse=True)[:top]


class VectorizerBackend:
    """打分后端抽象接口。"""

    def fit(self, documents):  # noqa: D401
        """用语料拟合 IDF（embedding 后端为 no-op）。"""
        return self

    def score(self, query: str, description: str) -> float:
        raise NotImplementedError

    def similarity(self, a: str, b: str) -> float:
        raise NotImplementedError

    def shared_keywords(self, a: str, b: str) -> list[str]:
        return _shared_ngrams(a, b)


class LocalTfidfBackend(VectorizerBackend):
    """本地字符 n-gram 余弦打分器：确定、可复现、零依赖（仅 math / re）。

    采用「纯 TF（词频）余弦」而非 IDF 加权：技能集通常很小（几十个），
    在小语料上 IDF 会稀释共享词、使所有相似度趋近 0，导致冲突检测失效。
    纯 TF 余弦对短文本更稳定：近重复 ≈1.0、同主题 ≈0.4、无关 ≈0.2。
    """

    def __init__(self):
        pass

    def fit(self, documents):
        # 纯 TF 余弦无需语料拟合；保留接口以便与 embedding 后端统一调用
        return self

    def _vec(self, text: str) -> dict[str, float]:
        grams = _ngrams(text)
        tf: dict[str, int] = {}
        for g in grams:
            tf[g] = tf.get(g, 0) + 1
        norm = math.sqrt(sum(v * v for v in tf.values())) or 1.0
        return {g: v / norm for g, v in tf.items()}

    def score(self, query: str, description: str) -> float:
        return _cosine(self._vec(query), self._vec(description))

    def similarity(self, a: str, b: str) -> float:
        return _cosine(self._vec(a), self._vec(b))

    def shared_keywords(self, a: str, b: str) -> list[str]:
        shared = set(_ngrams(a)) & set(_ngrams(b))
        if not shared:
            return []
        # 仅保留「纯中文」或「纯字母数字」片断，丢弃中英文混杂碎片（如 "d文档"）
        def _clean(g: str) -> bool:
            if all("一" <= ch <= "鿿" for ch in g):
                return True
            if all(ch.isascii() and ch.isalnum() for ch in g):
                return True
            return False

        clean = [g for g in shared if _clean(g)]
        ranked = sorted(clean, key=lambda g: (len(g), g), reverse=True)
        return ranked[:5]


class EmbeddingBackend(VectorizerBackend):
    """可选 embedding 后端：标准库 urllib 调用 OpenAI 兼容 embeddings API。"""

    def __init__(self, api_url: str = "", api_key_env: str = "EMBEDDING_API_KEY",
                 model: str = "text-embedding-3-small"):
        self.api_url = api_url
        self.api_key = os.environ.get(api_key_env, "")
        self.model = model
        self._cache: dict[str, list[float]] = {}

    def fit(self, documents):
        return self

    def _emb(self, text: str) -> list[float]:
        if text in self._cache:
            return self._cache[text]
        if not self.api_url:
            raise RuntimeError("embedding api_url 未配置，回退 local-tfidf")
        payload = {"input": text, "model": self.model}
        req = urllib.request.Request(
            self.api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
        vec = data["data"][0]["embedding"]
        self._cache[text] = vec
        return vec

    def score(self, query: str, description: str) -> float:
        return _cosine_vec(self._emb(query), self._emb(description))

    def similarity(self, a: str, b: str) -> float:
        return _cosine_vec(self._emb(a), self._emb(b))


def _load_vectorizer_config() -> dict:
    if VECTORIZER_PATH.exists():
        try:
            data = json.loads(VECTORIZER_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {
        "backend": "local-tfidf",
        "embedding": {
            "api_url": "",
            "api_key_env": "EMBEDDING_API_KEY",
            "model": "text-embedding-3-small",
        },
    }


# --------------------------------------------------------------------------- #
# 后端注册表（A-1 / A-4 · provider 可插拔）
# --------------------------------------------------------------------------- #
# 同一个 EmbeddingBackend 类映射多个 provider：openai（远程 OpenAI 兼容 API）
# 与 local-st（本地 OpenAI 兼容服务，如 ollama / text-embeddings-inference）
# 仅默认 api_url / model 不同；local-tfidf 为纯本地零依赖后端。
_VECTORIZER_REGISTRY: dict[str, type[VectorizerBackend]] = {
    "openai": EmbeddingBackend,
    "local-st": EmbeddingBackend,
    "local-tfidf": LocalTfidfBackend,
}


def register_vectorizer(provider: str, cls: type[VectorizerBackend]) -> None:
    """注入自定义向量后端（P1 · A-4）。

    自定义 cls 构造函数签名应与 EmbeddingBackend(api_url=, model=, api_key_env=) 兼容，
    以便 get_vectorizer 统一构造。内置 provider 不受影响。
    """
    if not (isinstance(cls, type) and issubclass(cls, VectorizerBackend)):
        raise TypeError("cls 必须是 VectorizerBackend 的子类")
    _VECTORIZER_REGISTRY[provider] = cls


def _resolve_embedding_cfg(provider: str | None = None) -> tuple[str, str, str]:
    """解析 embedding 后端连接参数，返回 (api_url, model, api_key_env)。

    - provider 缺省由 vectorizer.json 推断：backend==embedding 时默认 openai，否则 local-tfidf。
    - local-st：默认 api_url=EMBEDDING_API_URL（http://localhost:11434/v1/embeddings），
      model=nomic-embed-text（可被 embedding.model 覆盖）。
    - openai：api_url 取向量配置中的 api_url（缺省空 → 触发回退），model=text-embedding-3-small。
    """
    cfg = _load_vectorizer_config()
    emb = cfg.get("embedding", {}) or {}
    provider = provider or cfg.get("provider")
    if provider is None:
        provider = "openai" if cfg.get("backend") == "embedding" else "local-tfidf"
    if provider == "local-st":
        api_url = emb.get("api_url") or EMBEDDING_API_URL
        model = emb.get("model") or "nomic-embed-text"
    else:
        # openai 与自定义 provider 均从 embedding 段取，缺省空（将回退 local-tfidf）
        api_url = emb.get("api_url") or ""
        model = emb.get("model") or "text-embedding-3-small"
    api_key_env = emb.get("api_key_env", "EMBEDDING_API_KEY")
    return api_url, model, api_key_env


def _effective_is_embedding() -> bool:
    """当前 vectorizer.json 是否真正解析为稠密 embedding 后端。

    判定口径与 get_vectorizer() 一致：backend==embedding 且能解析出 api_url，
    否则视为 local-tfidf（稀疏）。阈值函数据此切换分档（A-2 / A-5）。
    """
    cfg = _load_vectorizer_config()
    if cfg.get("backend") != "embedding":
        return False
    provider = cfg.get("provider") or "openai"
    api_url, _, _ = _resolve_embedding_cfg(provider)
    return bool(api_url)


def is_dense_backend(vec: VectorizerBackend) -> bool:
    """是否为稠密向量后端（embedding 类）。calibrate 门控使用（A-3）。"""
    return isinstance(vec, EmbeddingBackend)


def conflict_default_threshold() -> float:
    """冲突检测默认阈值（A-2）。

    embedding 档 → 0.55；local-tfidf 档 → 0.7。
    vectorizer.json 的 thresholds.{backend}.conflict_threshold 可覆盖（A-5）。
    """
    cfg = _load_vectorizer_config()
    thresholds = cfg.get("thresholds", {}) or {}
    if _effective_is_embedding():
        t = (thresholds.get("embedding", {}) or {}).get("conflict_threshold")
        return float(t) if t is not None else CONFLICT_DEFAULT_THRESHOLD_EMBEDDING
    t = (thresholds.get("local-tfidf", {}) or {}).get("conflict_threshold")
    return float(t) if t is not None else CONFLICT_DEFAULT_THRESHOLD


def conflict_auto_deposit_threshold() -> float:
    """冲突规则自动沉淀阈值（A-2）。

    embedding 档 → 0.85；local-tfidf 档 → 0.9。
    vectorizer.json 的 thresholds.{backend}.auto_deposit_threshold 可覆盖（A-5）。
    """
    cfg = _load_vectorizer_config()
    thresholds = cfg.get("thresholds", {}) or {}
    if _effective_is_embedding():
        t = (thresholds.get("embedding", {}) or {}).get("auto_deposit_threshold")
        return float(t) if t is not None else CONFLICT_AUTO_DEPOSIT_THRESHOLD_EMBEDDING
    t = (thresholds.get("local-tfidf", {}) or {}).get("auto_deposit_threshold")
    return float(t) if t is not None else CONFLICT_AUTO_DEPOSIT_THRESHOLD


def get_vectorizer(backend_name: str | None = None,
                   provider: str | None = None) -> VectorizerBackend:
    """取得向量后端实例（A-1 · provider 解析）。

    backend_name 为 None 时读 vectorizer.json；为 'embedding' 时按 provider
    （openai / local-st / 自定义）解析 api_url 与 model 构造 EmbeddingBackend；
    api_url 缺失则回退 LocalTfidfBackend（保证零依赖可运行）。
    """
    cfg = _load_vectorizer_config()
    name = backend_name or cfg.get("backend", "local-tfidf")
    if name == "embedding":
        provider = provider or cfg.get("provider") or "openai"
        api_url, model, api_key_env = _resolve_embedding_cfg(provider)
        if not api_url:
            # 未解析出 api_url（如 openai 未配 api_url）→ 回退本地
            return LocalTfidfBackend()
        cls = _VECTORIZER_REGISTRY.get(provider, EmbeddingBackend)
        try:
            return cls(api_url=api_url, model=model, api_key_env=api_key_env)
        except TypeError:
            # 自定义 provider 构造函数签名不兼容时回退标准 EmbeddingBackend
            return EmbeddingBackend(api_url=api_url, model=model, api_key_env=api_key_env)
    return LocalTfidfBackend()
