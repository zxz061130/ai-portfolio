# -*- coding: utf-8 -*-
"""bench_models.py —— 同一组学科问题，跑两个本地模型，量出「质量提升值不值那点内存」

用法：
    python bench_models.py                     # 默认 qwen2.5:0.5b 与 qwen3:4b
    python bench_models.py --models qwen2.5:0.5b,qwen3:4b --limit 5
    python bench_models.py --out 对比.md

它测三样，不测「感觉」：
    ① 速度：冷启动（首次装载 + 首答）与热调用耗时、每秒 token 数
    ② 质量：同一问题的答案原文（打印出来自己判）
    ③ 占用：/api/ps 里的显存占用（模型常驻时），以及磁盘体积（/api/tags）

为什么不走 llm.py：这里要的是 Ollama 响应里的 eval_count/eval_duration 做精确统计，
和「调用方式」无关；llm.py 负责统一接口，脚本负责测量，各管一件事。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests

BASE = "http://127.0.0.1:11434"
NUM_PREDICT = 2400      # qwen3 会先自言自语上千 token，额度太小就只剩思考没有答案
QUESTIONS = [
    "给《愚公移山》出一道 HSK4 阅读理解题，只要题干和四个选项",
    "解释「把字句」的构成条件，各给一个正确例句和一个错句",
    "把这段教案要点扩成完整教案：初级口语，自我介绍，45 分钟",
    "给一篇中级留学生作文写三段式评语：优点、问题、下一步练习，各一句",
    "用三句话解释什么是「量化」，对象是刚接触 AI 的中学老师",
]


def session() -> requests.Session:
    s = requests.Session()
    s.trust_env = False            # 别让系统代理劫持本机请求
    return s


def tags(s: requests.Session) -> dict:
    try:
        return {m["name"]: m.get("size", 0) for m in s.get(f"{BASE}/api/tags", timeout=10).json()["models"]}
    except Exception:
        return {}


def ps_vram(s: requests.Session, model: str) -> float | None:
    """返回该模型常驻占用的显存（MB），未加载返回 None。"""
    try:
        for m in s.get(f"{BASE}/api/ps", timeout=5).json().get("models", []):
            names = {m.get("name", ""), m.get("model", "")}
            if model in names or any(n.split(":")[0] == model.split(":")[0] and n for n in names):
                return round(m.get("size_vram", 0) / 1024 / 1024, 0)
    except Exception:
        pass
    return None


def unload(s: requests.Session, model: str, wait: float = 20.0) -> None:
    """把模型从显存卸下，并等到 /api/ps 里真的消失，保证下一次是真正的冷启动。"""
    try:
        s.post(f"{BASE}/api/generate", json={"model": model, "keep_alive": 0}, timeout=60)
        deadline = time.time() + wait
        while time.time() < deadline:
            if ps_vram(s, model) is None:
                return
            time.sleep(0.5)
    except Exception:
        pass


def ask(s: requests.Session, model: str, question: str, timeout: float = 240.0) -> dict:
    started = time.perf_counter()
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": question}],
        "options": {"temperature": 0.7, "num_predict": NUM_PREDICT},
        "stream": False,
        "keep_alive": "5m",                                    # 别答完就卸，否则量不到显存

    }
    if model.lower().startswith("qwen3"):
        payload["think"] = False
    resp = s.post(f"{BASE}/api/chat", json=payload, timeout=timeout)
    wall = time.perf_counter() - started
    resp.raise_for_status()
    data = resp.json()
    content = ((data.get("message") or {}).get("content") or "").strip()
    had_marker = "</think>" in content
    if had_marker:                                             # 只留最终答案
        content = content.rsplit("</think>", 1)[1].strip()
    count = data.get("eval_count") or 0
    gen_ns = data.get("eval_duration") or 0
    return {
        "answer": content,
        "wall": wall,
        "tokens": count,
        "tok_s": count / (gen_ns / 1e9) if gen_ns else 0.0,
        "load_s": (data.get("load_duration") or 0) / 1e9,
        "done_reason": data.get("done_reason") or "",
        # 没见到 </think> 又刚好用满额度 = 思考途中被截断，答案没写出来
        "truncated": (not had_marker) and count >= NUM_PREDICT,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", default="qwen2.5:0.5b,qwen3:4b")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 个问题（0=全部）")
    parser.add_argument("--out", default="模型对比_0.5b_vs_4b.md")
    args = parser.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    questions = QUESTIONS[: args.limit] if args.limit else QUESTIONS

    s = session()
    try:
        s.get(f"{BASE}/api/version", timeout=5).raise_for_status()
    except Exception as exc:      # noqa: BLE001
        print(f"[FAIL] 连不上 Ollama（{BASE}）：{exc}\n先启动 Ollama 再跑。", file=sys.stderr)
        return 1

    installed = tags(s)
    missing = [m for m in models if m not in installed]
    if missing:
        print(f"[FAIL] 本机没有这些模型：{', '.join(missing)}", file=sys.stderr)
        print(f"       先拉：ollama pull {missing[0]}", file=sys.stderr)
        return 1

    rows: list[str] = []
    summary: list[str] = []
    answers: dict[tuple[str, str], dict] = {}

    for model in models:
        unload(s, model)                     # 保证冷启动
        size_mb = installed[model] / 1024 / 1024
        print(f"== {model}（磁盘 {size_mb:.0f} MB）==", flush=True)

        first = ask(s, model, questions[0])
        vram = ps_vram(s, model)
        cold = first["wall"]
        load = first["load_s"]
        print(f"   冷启动：装载 {load:.1f}s，首答端到端 {cold:.1f}s，"
              f"{first['tok_s']:.0f} tok/s，显存 {vram or '?'} MB", flush=True)

        warm_times, warm_tok, all_tokens = [], [], [first["tokens"]]
        for i, q in enumerate(questions):
            data = first if i == 0 else ask(s, model, q)
            answers[(model, q)] = data
            all_tokens.append(data["tokens"])
            if i > 0:
                warm_times.append(data["wall"])
                warm_tok.append(data["tok_s"])
                print(f"   [{i + 1}/{len(questions)}] {data['wall']:.1f}s "
                      f"{data['tok_s']:.0f} tok/s  {q[:18]}…", flush=True)

        avg_warm = sum(warm_times) / len(warm_times) if warm_times else first["wall"]
        avg_tok = sum(warm_tok) / len(warm_tok) if warm_tok else first["tok_s"]
        avg_tokens = sum(all_tokens) / len(all_tokens)
        unfinished = sum(1 for q in questions if answers[(model, q)]["truncated"])
        summary.append((model, size_mb, load, cold, avg_warm, avg_tok, vram, avg_tokens, unfinished))
        unload(s, model)

    lines = ["# 本地模型对比：qwen2.5:0.5b vs qwen3:4b", "",
             f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
             f"- 环境：Windows 11 · RTX 5080 Laptop · Ollama {s.get(f'{BASE}/api/version').json().get('version')}",
             f"- 问题数：{len(questions)}　参数：temperature=0.7，num_predict={NUM_PREDICT}", "",
             "## 一、客观指标（脚本测出来的，不是感觉）", "",
             "| 模型 | 磁盘 | 首次装载 | 首答端到端 | 热调用平均 | 平均生成速度 | 平均输出 token | 显存占用 |",
             "|---|---|---|---|---|---|---|---|"]
    for model, size, load, cold, warm, tok, vram, avg_tokens, _unfinished in summary:
        lines.append(f"| {model} | {size:.0f} MB | {load:.1f}s | {cold:.1f}s | {warm:.1f}s | "
                     f"{tok:.0f} tok/s | {avg_tokens:.0f} | {vram or '—'} MB |")

    if len(summary) == 2:
        a, b = summary
        vram_a, vram_b = a[6] or 0, b[6] or 0
        lines += ["", "### 客观倍数（脚本算的）", "",
                  f"- 磁盘：{b[1] / a[1]:.1f} 倍（{a[1]:.0f} MB → {b[1]:.0f} MB）",
                  f"- 显存：{(vram_b / vram_a) if vram_a else 0:.1f} 倍（{vram_a:.0f} MB → {vram_b:.0f} MB）",
                  f"- 生成速度：{b[5] / a[5]:.2f} 倍（{a[5]:.0f} → {b[5]:.0f} tok/s）",
                  f"- 热调用耗时：{b[4] / a[4]:.1f} 倍（{a[4]:.1f}s → {b[4]:.1f}s）",
                  f"- 平均输出 token：{b[7] / a[7]:.1f} 倍（{a[7]:.0f} → {b[7]:.0f}）"
                  f" —— 差额主要是大模型的“自我推理”，不是答案本身",
                  f"- 思考途中被 token 上限截断的回答：{a[8]} / {len(questions)} 与 {b[8]} / {len(questions)}",
                  ""]

    lines += ["", "> 读法：`num_predict` 是单次回答的 token 上限。带「没写完」标记的，是模型的自我推理把额度用光了，", 
             "> 把 bench_models.py 顶部的 NUM_PREDICT 调到 3600 再跑一次就能看到完整答案。", "",
             "## 二、同一问题的答案对照（质量自己判）", ""]
    for i, q in enumerate(questions, 1):
        lines += [f"### {i}. {q}", ""]
        for model in models:
            data = answers[(model, q)]
            excerpt = " ".join(data["answer"].split())[:220]
            note = "　⚠️ 没写完（思考把 token 用光了）" if data["truncated"] else ""
            lines += [f"**{model}**（{data['tokens']} token，{data['tok_s']:.0f} tok/s）{note}：",
                      "", f"> {excerpt}", ""]

    lines += ["", "## 三、我的判断（自己写，别空着）", "",
              "1. 质量差多少？抄一句只有 4b 答对、0.5b 答偏的原话：", "",
              "2. 代价是什么？多占多少显存、冷启动多等几秒：", "",
              "3. 结论：什么任务 0.5b 就够，什么任务值得上 4b（写具体任务名）：", ""]

    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n== 已生成：{args.out} ==")
    print("   客观指标已填，质量对照已摘录；第三节「我的判断」要你自己写。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
