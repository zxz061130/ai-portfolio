# -*- coding: utf-8 -*-
"""run_hallucination.py —— 幻觉对照表的“机器填表”脚本

一条问题跑 4 次，把答案原样落地，交给后面人工判「谁对谁错、差在哪」：
    ① 裸答 · 本地 qwen2.5:0.5b   （不给资料、不加限定语）
    ② 裸答 · 云端 deepseek-chat  （同上，只是换了模型）
    ③ RAG  · 本地 qwen2.5:0.5b   （给检索到的 3 段 + 出处要求）
    ④ RAG  · 云端 deepseek-chat

每格都带两行机器证据：命中段（检索到哪几块）与数字校验（答案里的数字是否真在资料里）。
写进 hallucination_raw.md；人工结论写在 幻觉对照表.md，两者互相印证。

用法：
    python run_hallucination.py                # 4 组全跑
    python run_hallucination.py --only 1,3     # 只跑第 1、3 题
    python run_hallucination.py --skip-api     # 没配云端密钥时只跑本地两列
"""
from __future__ import annotations

import argparse
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import weekpath                       # noqa: E402
weekpath.load_env()

import rag_qa                         # noqa: E402

# (编号, 问题, 资料里能查到的关键事实——用于人眼核对与机器数字校验)
QUESTIONS = [
    ("Q1", "HSK 四级（中等四级）累计词汇量是多少？本级新增多少？", "1000/3245"),
    ("Q2", "完成初等阶段的学习，应掌握多少个词语？", "2245"),
    ("Q3", "高等（七至九级）新增汉字多少个？累计多少个？", "1200/3000"),
    ("Q4", "三级累计语法点多少个？", "210"),
    ("Q5", "中等阶段新增词语多少个？", "3211"),
    ("Q6", "《国际中文教育中文水平等级标准》是哪一年发布、哪一年实施的？", "2021"),
]


def _clean(text: str, limit: int = 400) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit] + "…"


def _cell(result: dict) -> str:
    body = _clean(result["answer"])
    tag = f"`{result['engine']}` {result['seconds']:.1f}s"
    if result["rag"]:
        files = "、".join(f"《{d.metadata['文件']}》第{d.metadata['段号']}段" for d in result["docs"])
        tag += f"；命中：{files}"
        if result["unverified"]:
            tag += f"；数字校验✗ {'、'.join(result['unverified'])}"
    return f"{body}<br><sub>{tag}</sub>"


def collect(questions, k: int = rag_qa.TOP_K, skip_api: bool = False, quiet: bool = False):
    """跑 4 列，返回每题一条记录。make_run_log.py 也调它，保证两边是同一套逻辑。"""
    base = rag_qa.RAG(k=k)
    base.store()                       # 先建好，后面每个问题复用同一个库

    rows = []
    for qid, question, truth in questions:
        if not quiet:
            print(f"\n[{qid}] {question}")
        rec = {"id": qid, "q": question, "truth": truth}

        for key, prefer, use_rag in (("bare_local", "local", False),
                                     ("bare_api", "api", False),
                                     ("rag_local", "local", True),
                                     ("rag_api", "api", True)):
            if skip_api and prefer == "api":
                rec[key] = None
                continue
            # 裸答与 RAG 各用一个干净会话：不能把上一题的答案带进下一题
            session = rag_qa.RAG(k=k, prefer=prefer)
            session._vs = base._vs
            try:
                rec[key] = session.ask(question, rag=use_rag, remember=False)
                if not quiet:
                    print(f"   {key:<10} ✓ {rec[key]['seconds']:.1f}s")
            except Exception as exc:          # noqa: BLE001  某一列失败不该毁掉整张表
                if not quiet:
                    print(f"   {key:<10} ✗ {type(exc).__name__}: {exc}")
                rec[key] = {"error": f"{type(exc).__name__}: {exc}"}
        rows.append(rec)
    return rows


def render_markdown(rows, k: int = rag_qa.TOP_K, when: str = "") -> str:
    """把一次运行渲染成 hallucination_raw.md。make_run_log.py 复用同一份，保证两文件同源。"""
    lines = [
        "# 幻觉对照表 · 机器原始记录",
        "",
        f"> 由 `run_hallucination.py` 生成（{when or time.strftime('%Y-%m-%d %H:%M')}）——"
        "本文件只放模型原话和检索证据，**不做人工润色**；结论与反思在 `幻觉对照表.md`。",
        "",
        f"- 生成方式：`python run_hallucination.py`（k={k}，chunk=500/50，"
        f"嵌入 {rag_qa.EMBED_MODEL}，temperature=0.1）",
        f"- 裸答：只发问题，不给资料、不加「资料中没有就说未提及」的限定语",
        "- 数字校验：答案里出现的数字是否真在检索到的资料文本里；"
        "命中段说明这 3 块里有没有那句原文",
        "",
        "| # | 问题 | 裸答 · 本地 0.5b | 裸答 · 云端 | RAG 答 · 本地 0.5b | RAG 答 · 云端 |",
        "|---|---|---|---|---|---|",
    ]
    for rec in rows:
        cells = [rec["id"], rec["q"]]
        for key in ("bare_local", "bare_api", "rag_local", "rag_api"):
            val = rec[key]
            if val is None:
                cells.append("未测")
            elif "error" in val:
                cells.append(f"失败：{_clean(val['error'], 80)}")
            else:
                cells.append(_cell(val))
        lines.append("| " + " | ".join(cells) + " |")

    lines += ["", "## 资料里的正确答案（人眼核对用）", "", "| # | 关键事实 | 出处 |", "|---|---|---|"]
    for rec in rows:
        got = rec.get("rag_api") or rec.get("rag_local") or {}
        src = ""
        if isinstance(got, dict) and got.get("docs"):
            src = "、".join(f"《{d.metadata['文件']}》第{d.metadata['段号']}段" for d in got["docs"])
        lines.append(f"| {rec['id']} | {rec['truth']} | {src or '—'} |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="run_hallucination.py")
    parser.add_argument("--only", default="", help="只跑指定题号，如 1,3")
    parser.add_argument("--skip-api", action="store_true", help="跳过云端两列")
    parser.add_argument("--k", type=int, default=rag_qa.TOP_K)
    parser.add_argument("--out", default=os.path.join(_HERE, "hallucination_raw.md"))
    args = parser.parse_args(argv)

    picked = {s.strip() for s in args.only.split(",") if s.strip()}
    questions = [q for q in QUESTIONS if not picked or q[0].lstrip("Q") in picked]
    if not questions:
        print("没有匹配的题目", file=sys.stderr)
        return 2

    print("[建库/复用]")
    started = time.perf_counter()
    rows = collect(questions, k=args.k, skip_api=args.skip_api)

    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render_markdown(rows, k=args.k))

    print(f"\n[saved] {args.out} ｜ 总耗时 {time.perf_counter() - started:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
