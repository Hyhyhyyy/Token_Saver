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

from .config import VECTORIZER_PATH

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


def get_vectorizer(backend_name: str | None = None) -> VectorizerBackend:
    """取得向量后端实例。

    backend_name 为 None 时读 vectorizer.json；为 'embedding' 且已配 api_url 才启用远程，
    否则回退 LocalTfidfBackend（保证零依赖可运行）。
    """
    cfg = _load_vectorizer_config()
    name = backend_name or cfg.get("backend", "local-tfidf")
    if name == "embedding":
        emb = cfg.get("embedding", {}) or {}
        if emb.get("api_url"):
            return EmbeddingBackend(
                api_url=emb["api_url"],
                api_key_env=emb.get("api_key_env", "EMBEDDING_API_KEY"),
                model=emb.get("model", "text-embedding-3-small"),
            )
        # 未配置 api_url → 回退本地
        return LocalTfidfBackend()
    return LocalTfidfBackend()
