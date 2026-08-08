"""B-1 / B-2：趋势图前端渲染分支（单点参考线 / 样本不足 / 异常高亮）。

零新增依赖（不引入 jsdom/chart 库）。采用轻量字符串断言，校验 app.js 实现了
<2 点水平参考线 +「样本不足」提示、相邻点异常高亮（告警色描点 + <title> +
「存在 N 处异常」图例），以及 index.html / style.css 配套元素与 class。
"""
import pytest

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_JS = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
STYLE_CSS = (ROOT / "frontend" / "style.css").read_text(encoding="utf-8")

pytestmark = pytest.mark.b


def test_anomaly_constants_defined():
    assert "ANOMALY_F1_DROP" in APP_JS
    assert "ANOMALY_COV_DROP" in APP_JS


def test_ref_line_and_insufficient_for_few_points():
    # B-1：<2 点绘制水平参考线 +「样本不足」
    assert "trend-ref-line" in APP_JS
    assert "样本不足" in APP_JS


def test_anomaly_highlight_branch():
    # B-2：相邻点比较 + 告警色描点 + <title> + 「存在 N 处异常」图例
    assert "trend-anomaly" in APP_JS
    assert "存在" in APP_JS and "处异常" in APP_JS
    # 异常判定基于相邻点差值阈值
    assert "ANOMALY_F1_DROP" in APP_JS and "ANOMALY_COV_DROP" in APP_JS


def test_index_has_signature_option_and_backend_source():
    # A-1 筛选下拉 + D-2 后端来源元素
    assert 'value="skill_signature_change"' in INDEX_HTML
    assert 'id="backendSource"' in INDEX_HTML


def test_style_has_trend_classes():
    for cls in ("trend-ref-line", "trend-anomaly", "trend-insufficient", "backend-source"):
        assert f".{cls}" in STYLE_CSS
