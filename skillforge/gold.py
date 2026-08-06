"""Gold 样本管理（F1 调度反事实模拟的评估集）。

- 内置 ≥20 条「用户 query → 正确技能」合成+典型样本，覆盖主流 WorkBuddy 内置技能。
- 文件优先：DATA_DIR/gold_samples.json 存在则读取，否则回退内置并落盘。
- set_gold() 校验后写入（缺 query / skill_id 即抛 ValueError，由 server 转 400）。
"""
from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone

from .config import GOLD_PATH

# 内置默认集：覆盖常见 query→skill 映射（含易冲突对 office-writer/docx-editor、pdf-extract/pdf-reader）
DEFAULT_GOLD: list[dict] = [
    {"id": "g01", "query": "把本地 Word 文档改成可编辑内容并保存", "skill_id": "docx-editor"},
    {"id": "g02", "query": "解析 PDF 提取里面的表格和文字", "skill_id": "pdf-reader"},
    {"id": "g03", "query": "用 Python 跑一个定时爬虫抓取网页数据", "skill_id": "web-crawler"},
    {"id": "g04", "query": "上网搜索最新的行业新闻并汇总", "skill_id": "web-search"},
    {"id": "g05", "query": "把 Excel 表格里的数据按条件筛选并生成透视表", "skill_id": "xlsx-editor"},
    {"id": "g06", "query": "把这份 PPT 的配色和版式统一一下", "skill_id": "pptx-editor"},
    {"id": "g07", "query": "提交代码到 git 并解决合并冲突", "skill_id": "git-helper"},
    {"id": "g08", "query": "用 Docker 把服务打包成镜像并启动容器", "skill_id": "docker-helper"},
    {"id": "g09", "query": "写一条 SQL 查询统计每个用户的订单总额", "skill_id": "sql-query"},
    {"id": "g10", "query": "根据文案生成一张产品宣传图", "skill_id": "image-gen"},
    {"id": "g11", "query": "把这段英文技术文档翻译成中文", "skill_id": "translate"},
    {"id": "g12", "query": "把这篇长文章压缩成三段摘要", "skill_id": "summarize"},
    {"id": "g13", "query": "审查我刚写的 Python 函数有没有潜在 bug", "skill_id": "code-review"},
    {"id": "g14", "query": "分析这份销售数据找出增长最快的品类", "skill_id": "data-analysis"},
    {"id": "g15", "query": "帮我起草一封委婉拒绝合作的邮件", "skill_id": "email-draft"},
    {"id": "g16", "query": "把会议录音整理成带待办的纪要", "skill_id": "meeting-notes"},
    {"id": "g17", "query": "把桌面上一堆下载文件按类型归类整理", "skill_id": "file-organize"},
    {"id": "g18", "query": "用正则从日志里提取所有的报错时间", "skill_id": "regex-extract"},
    {"id": "g19", "query": "测试这个 REST 接口在不同参数下的返回", "skill_id": "api-tester"},
    {"id": "g20", "query": "把 Markdown 笔记转成带目录的 HTML 页面", "skill_id": "markdown-convert"},
    {"id": "g21", "query": "根据这些数据画一张柱状趋势图", "skill_id": "chart-gen"},
    {"id": "g22", "query": "起草一篇从零开始的周报，偏生成风格", "skill_id": "office-writer"},
    {"id": "g23", "query": "从 PDF 中抽取关键字段做结构化提取", "skill_id": "pdf-extract"},
    {"id": "g24", "query": "帮我做一份 SMART 拆解的每日学习计划", "skill_id": "task-planner"},
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_gold() -> list[dict]:
    """读取 gold 样本；文件缺失或损坏则回退内置默认并落盘。"""
    if GOLD_PATH.exists():
        try:
            data = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                return data
        except Exception:
            pass
    GOLD_PATH.write_text(
        json.dumps(DEFAULT_GOLD, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return [dict(s) for s in DEFAULT_GOLD]


def set_gold(samples) -> list[dict]:
    """校验并覆盖写入 gold 样本。非法（非数组 / 缺 query 或 skill_id）抛 ValueError。"""
    if not isinstance(samples, list):
        raise ValueError("gold 样本必须为数组")
    out: list[dict] = []
    for i, s in enumerate(samples):
        if not isinstance(s, dict):
            raise ValueError(f"样本 #{i} 格式错误，必须为对象")
        q = (s.get("query") or "").strip()
        sid = (s.get("skill_id") or "").strip()
        if not q or not sid:
            raise ValueError(f"样本 #{i} 缺少 query 或 skill_id，已拒绝")
        out.append({
            "id": (s.get("id") or f"g{i + 1:02d}"),
            "query": q,
            "skill_id": sid,
        })
    GOLD_PATH.write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return out
