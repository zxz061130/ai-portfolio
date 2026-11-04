# -*- coding: utf-8 -*-
"""make_run_log.py —— 把一次真实运行落成可直接截图/存档的文本记录（运行记录.txt）

为什么不用截图：截图不可检索、不能 diff，老师也无法核对是不是真跑过。
这份记录包含完整环境（系统/依赖/模型/分块参数）+ 每题四列原话 + 命中段 + 耗时，
换台机器跑同一条命令就能对照。

它不自带任何业务逻辑：题目与四列由 run_hallucination.collect() 跑，避免两份实现走偏。

用法：
    python make_run_log.py                # 6 题 × 4 列，写到 week07_RAG/运行记录.txt
    python make_run_log.py --skip-api     # 没配云端密钥时只跑本地两列
    python make_run_log.py --out D:/x.txt
"""
from __future__ import annotations

import argparse
import importlib.metadata as md
import os
import platform
import sys
import time
import unicodedata

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import weekpath                        # noqa: E402
weekpath.load_env()

import rag_qa                          # noqa: E402
from run_hallucination import QUESTIONS, collect, render_markdown   # noqa: E402

WIDTH = 96
RULE = "=" * WIDTH
THIN = "-" * WIDTH
MAX_CHARS = 300                        # 单格答案上限：日志要能截图，超长就截断并注明
COLS = (("bare_local", "裸答 · 本地 0.5b"), ("bare_api", "裸答 · 云端"),
        ("rag_local", "RAG  · 本地 0.5b"), ("rag_api", "RAG  · 云端"))


def _ver(name: str) -> str:
    try:
        return md.version(name)
    except Exception:                 # noqa: BLE001  没装的包不该让记录生成失败
        return "未安装"


def _ollama() -> list:
    """[版本, 模型清单]；连不上就如实写，不假装。"""
    try:
        import requests
        s = requests.Session()
        s.trust_env = False           # 系统代理会劫持 127.0.0.1（W5 踩过）
        base = f"http://{rag_qa.local_host()}"
        ver = s.get(f"{base}/api/version", timeout=5).json().get("version", "?")
        tags = s.get(f"{base}/api/tags", timeout=5).json().get("models", [])
        names = [m.get("name", "?") for m in tags]
        return [f"{ver} @ {rag_qa.local_host()}", "、".join(names) or "（无模型）"]
    except Exception as exc:          # noqa: BLE001
        return ["未连接", f"（{type(exc).__name__}）"]


def _git() -> str:
    """不乱起子进程，直接读 .git；读不到就写「未知」。"""
    try:
        head = open(os.path.join(_ROOT, ".git", "HEAD"), encoding="utf-8").read().strip()
        if not head.startswith("ref:"):
            return head[:12]
        ref = head.split(":", 1)[1].strip()
        path = os.path.join(_ROOT, ".git", *ref.split("/"))
        if os.path.exists(path):
            return f"{ref.split('/')[-1]}@{open(path, encoding='utf-8').read()[:12]}"
        for line in open(os.path.join(_ROOT, ".git", "packed-refs"), encoding="utf-8"):
            if line.strip().endswith(ref):
                return f"{ref.split('/')[-1]}@{line.split()[0][:12]}"
        return "未知（浅克隆或 ref 未落盘）"
    except Exception:                 # noqa: BLE001
        return "未知"


def _w(text: str) -> int:
    """显示宽度：中文/全角算 2 格，其它算 1 格（终端里对齐靠它，不能按字符数算）。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def _pad(label: str, width: int = 12) -> str:
    return label + " " * max(1, width - _w(label))


def _center(text: str, width: int = WIDTH) -> str:
    return " " * max(0, (width - _w(text)) // 2) + text


def _wrap(text: str, indent: str = " " * 6, width: int = WIDTH - 4) -> list:
    """按显示宽度折行，宁可窄一点也不越界（方便截图）。"""
    text = " ".join((text or "").split())
    if not text:
        return [indent + "（空）"]
    lines, cur = [], ""
    for ch in text:
        if _w(indent + cur + ch) > width:
            lines.append(indent + cur)
            cur = ch
        else:
            cur += ch
    lines.append(indent + cur)
    return lines


def _trunc(text: str, limit: int = 0) -> str:
    """答案太长就截断——日志是给截图/存档用的，一屏能扫完比全量更重要。"""
    limit = limit or MAX_CHARS
    body = " ".join((text or "").split())
    if len(body) <= limit:
        return body
    return body[:limit] + f"……〔截断，全文 {len(body)} 字；完整原话见 hallucination_raw.md〕"


def _cell(rec: dict) -> list:
    """一列的输出：状态行 + 答案折行 + 检索证据。"""
    out = []
    if rec is None:
        return ["    未测（--skip-api）"]
    if "error" in rec:
        return ["    ✗ 调用失败：" + rec["error"]]

    mark = "·"        # 只标“这一格有答案”，对错由人判：机器不给对错打勾
    head = (f"    {mark} {rec['engine']:<5} {rec['seconds']:>5.2f}s"
            f"  回退:{'是' if rec.get('fallback') else '否'}")
    if rec.get("rag"):
        hits = "、".join(f"{d.metadata['文件']}#{d.metadata['段号']}" for d in rec["docs"])
        head += f"  命中 {len(rec['docs'])} 段"
    out.append(head)
    out.extend(_wrap(_trunc(rec["answer"])))
    if rec.get("rag"):
        out.append("      检索：" + hits)
        if rec.get("unverified"):
            out.append("      数字校验：✗ 资料里查无此数 → " + "、".join(rec["unverified"]))
        else:
            out.append("      数字校验：✓ 答案里的数字都能在资料里对上")
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="make_run_log.py")
    parser.add_argument("--skip-api", action="store_true")
    parser.add_argument("--k", type=int, default=rag_qa.TOP_K)
    parser.add_argument("--out", default=os.path.join(_HERE, "运行记录.txt"))
    args = parser.parse_args(argv)

    rag_qa._utf8_stdout()
    t0 = time.perf_counter()
    stamp_start = time.strftime("%Y-%m-%d %H:%M:%S")

    print("[1/2] 采集环境信息…")
    docs = rag_qa.load_documents()
    chunks = rag_qa.split_documents(docs)
    ollama_ver, ollama_models = _ollama()

    meta = [
        ("记录生成", f"{stamp_start}（本机时区）"),
        ("仓库状态", _git()),
        ("主机", f"{platform.platform()} / {platform.machine()}"),
        ("Python", platform.python_version()),
        ("Ollama", ollama_ver),
        ("已装模型", ollama_models),
        ("嵌入模型", f"{rag_qa.EMBED_MODEL}（768 维，离线哈希兜底可用）"),
        ("语料", f"{len(docs)} 个文件 / {sum(len(d.page_content) for d in docs)} 字 → "
                 f"{len(chunks)} 块（正文按句切 + 量化表按行切）"),
        ("检索参数", f"k={args.k}｜chunk={rag_qa.CHUNK_SIZE}/{rag_qa.CHUNK_OVERLAP}｜"
                     f"重排=hybrid｜表格分块=开"),
        ("依赖", f"langchain {_ver('langchain')} / langchain-chroma {_ver('langchain-chroma')}"
                 f" / langchain-ollama {_ver('langchain-ollama')} / chromadb {_ver('chromadb')}"),
        ("被测模型", "本地 qwen2.5:0.5b   ｜   云端 deepseek-chat"),
        ("采样参数", "temperature=0.1（四列一致，唯一变量是「给不给资料」）"),
        ("同源文件", "本记录与 hallucination_raw.md 来自同一次运行，可逐题对照"),
    ]

    print("[2/2] 跑 6 题 × 4 列（约 25 秒）…")
    started = time.perf_counter()
    rows = collect(QUESTIONS, k=args.k, skip_api=args.skip_api, quiet=True)
    elapsed = time.perf_counter() - started

    # 同一次运行的表格版（幻觉对照表的引用来源），保证两份文件不会各说各话
    raw_path = os.path.join(_HERE, "hallucination_raw.md")
    with open(raw_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render_markdown(rows, k=args.k, when=stamp_start))
    print(f"[saved] {raw_path}")

    # ---------------- 组装文本 ----------------
    L = [RULE,
         _center("W7 幻觉对照实验 · 完整运行记录"),
         RULE, ""]
    for key, val in meta:
        L.append(f"  {_pad(key, 11)}：{val}")
    L += ["", THIN,
          "  说明：本记录由 make_run_log.py 真实运行生成，不含任何密钥；",
          "        每格都带引擎、耗时、命中段落与数字校验，可逐条核对。",
          THIN, ""]

    for i, rec in enumerate(rows, 1):
        L.append(f"[{rec['id']}] {rec['q']}")
        L.append(f"      资料里的关键事实：{rec['truth']}")
        L.append("")
        for key, label in COLS:
            L.append(f"  {label}")
            L.extend(_cell(rec[key]))
            L.append("")
        L.append(THIN)

    # ---------------- 汇总 ----------------
    def ok_count(key):
        n = 0
        for rec in rows:
            val = rec.get(key)
            if isinstance(val, dict) and "error" not in val:
                body = rag_qa.CITED_RE.sub(" ", val["answer"])
                if all(t in body or t in val["answer"] for t in rec["truth"].split("/")):
                    n += 1
        return n

    L += ["", "汇总（“字样命中”= 关键事实出现在答案里，仅供速览，最终判定见 幻觉对照表.md）", ""]
    for key, label in COLS:
        vals = [r[key] for r in rows if isinstance(r.get(key), dict) and "error" not in r[key]]
        if not vals:
            L.append(f"  {_pad(label, 20)}未测")
            continue
        avg = sum(v["seconds"] for v in vals) / len(vals)
        L.append(f"  {_pad(label, 20)}字样命中 {ok_count(key)}/{len(rows)}"
                 f"   平均耗时 {avg:>5.2f}s")
    L += ["",
          f"  四列总调用 {sum(1 for r in rows for k, _ in COLS if isinstance(r.get(k), dict))} 次"
          f"   实验耗时 {elapsed:.1f}s   记录生成总耗时 {time.perf_counter() - t0:.1f}s",
          "",
          "  注：字样命中只比字符串，会把「数字对、位置错」也算进去（例：Q1 把新增/累计读反），",
          "      所以它 ≥ 人工判定的正确数；正确率一律以 幻觉对照表.md 为准。",
          "",
          THIN,
          "  复现：cd week07_RAG && python make_run_log.py",
          "  附表：hallucination_raw.md（逐题表格）｜幻觉对照表.md（人工结论与反思）",
          f"  结束时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
          RULE]

    text = "\n".join(L) + "\n"
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print(f"[saved] {args.out}（{len(text)} 字节，{len(L)} 行）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
