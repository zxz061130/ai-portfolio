#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""jsonpick.py —— 把 Ollama /api/chat 的响应读成人能看的东西（替代 jq）

用法：
    python bin/jsonpick.py 响应.json --mode content      # 只要答案正文
    python bin/jsonpick.py 响应.json --mode metrics      # 速度指标
    python bin/jsonpick.py 响应.json --mode row          # 一行 TSV，给 compare.sh 拼表

Windows 上必须带 PYTHONUTF8=1 运行（脚本里已设），否则中文会按 GBK 读坏。
"""
from __future__ import annotations

import argparse
import json
import sys


def load(path: str) -> dict:
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        return json.load(handle)


def _force_utf8_stdout() -> None:
    """Windows + Git Bash：默认 GBK 输出会让中文变乱码。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            if (stream.encoding or "").lower() not in ("utf-8", "utf8"):
                stream.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[attr-defined]
        except Exception:
            pass


_force_utf8_stdout()


def sec(ns) -> float:
    return (ns or 0) / 1e9


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--mode", choices=("content", "metrics", "row"), default="content")
    parser.add_argument("--width", type=int, default=40, help="摘要截断宽度（row 模式）")
    args = parser.parse_args()

    try:
        data = load(args.path)
    except json.JSONDecodeError:
        print("[ERROR] 响应不是合法 JSON（服务可能返回了 HTML 错误页）", file=sys.stderr)
        return 2

    if "error" in data:
        print(f"[ERROR] {data['error']}", file=sys.stderr)
        return 2

    answer = (data.get("message") or {}).get("content") or ""
    answer = answer.strip()
    count = data.get("eval_count") or 0
    gen = sec(data.get("eval_duration"))
    total = sec(data.get("total_duration"))
    load_s = sec(data.get("load_duration"))
    prompt_n = data.get("prompt_eval_count") or 0
    tok_s = count / gen if gen > 0 else 0.0
    model = data.get("model", "?")

    if args.mode == "content":
        print(answer)
        return 0

    if args.mode == "metrics":
        print("-" * 62)
        print(f"模型 {model} | 输出 {count} token | 生成 {gen:.1f}s | 约 {tok_s:.0f} tok/s")
        print(f"首次装载 {load_s:.1f}s | 端到端 {total:.1f}s | 输入 {prompt_n} token")
        return 0

    summary = " ".join(answer.split())
    if len(summary) > args.width:
        summary = summary[: args.width] + "…"
    print("\t".join([
        summary,
        str(count),
        f"{tok_s:.0f}",
        f"{load_s:.1f}",
        f"{total:.1f}",
        model,
    ]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
