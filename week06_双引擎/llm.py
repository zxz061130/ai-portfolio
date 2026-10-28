# -*- coding: utf-8 -*-
"""llm.py —— W6 双引擎统一入口：本地 Ollama ＋ 云端 DeepSeek，一个 prefer 参数切换

    from llm import LLM
    print(LLM().ask("给《愚公移山》出一道 HSK4 阅读题", prefer="local"))     # 单轮
    llm = LLM(); llm.chat("我在教 HSK4 阅读"); llm.chat("那出题该注意什么")   # 多轮

命令行：
    python llm.py "给《愚公移山》出一道 HSK4 阅读题" --prefer local
    python llm.py --chat --prefer local        # 连续追问，/bye 退出，/clear 清空记忆

【作业 1 的选择与理由】（讲义第九节，三选一）
    选「多轮对话（messages 列表记忆）」。理由：
    1) W8 的对话式助手必然要记忆，现在把 messages 的组装点收进 LLM，
       避免到时在助手层再散落一套、两处各改一遍；
    2) 多轮最能暴露「上下文成本」：第 10 轮的 prompt 含前 9 轮，云端按输入
       token 计费，本地小模型也会因为上下文变长而明显退化——这正好能撑起
       讲义优秀档要的「什么任务走本地、什么任务走云端」的判断依据；
    3) 不选重试（B）：它与已有的双向回退在概念上重叠，单独交显得薄；
       不选费用打印（C）：W4 已经算过一次账，增量信息不如多轮大。

设计纪律（讲义第四、七节）：
    · 不吞异常：except 里必须打印原因，禁止 pass、禁止返回空字符串
    · 回退必须双向：prefer="local" 本地挂→切云端；prefer="api" 云端挂→切本地
    · 返回类型统一为 str：上层才能无差别使用两个引擎
"""
from __future__ import annotations

import argparse
import os
import sys
import time

# 跨周导入固定三行（讲义第 7 节）：让 W7/W8 的 from llm import LLM 找得到，
# 同时把 .env 加载好，免得到处重复 load_env()。
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
try:
    import weekpath
    weekpath.load_env()
except Exception:                      # 没有 weekpath（单独拷贝出去跑）也不影响
    pass

DEFAULT_LOCAL_MODEL = "qwen2.5:0.5b"
DEFAULT_LOCAL_HOST = "127.0.0.1:11434"   # 用 127.0.0.1 而不是 localhost：
                                         # Windows 上 localhost 可能解析到 IPv6 ::1，而 Ollama 只听 IPv4
DEFAULT_LOCAL_TIMEOUT = 60.0             # 首次装载可能 30 秒，必须留够
DEFAULT_API_MODEL = "deepseek-chat"
DEFAULT_API_BASE = "https://api.deepseek.com/v1"
DEFAULT_API_TIMEOUT = 120.0
DEFAULT_KEEP_TURNS = 8                   # 只记住最近 8 轮（1 轮 = 1 问 + 1 答）


class LLMError(RuntimeError):
    """两个引擎都失败时抛这个，把两边的原始原因都带上（便于排错，不静默）。"""


class LocalEngine:
    """本地引擎：W5 那段 http 直连，原样搬进类里。返回 str。

    多轮改造：真正干活的是 ask_messages(messages)，ask(prompt) 只是包一条 user 消息，
    这样 W4/W5 那种「一句话调用」照旧可用，而 LLM.chat() 能把整段历史传进来。
    """

    name = "local"

    def __init__(self, model=None, host=None, timeout=None):
        self.model = model or os.getenv("LOCAL_MODEL", DEFAULT_LOCAL_MODEL)
        self.host = host or os.getenv("LOCAL_HOST", DEFAULT_LOCAL_HOST)
        self.timeout = float(timeout or os.getenv("LOCAL_TIMEOUT", DEFAULT_LOCAL_TIMEOUT))

    def _think(self):
        """qwen3 系列默认会先“思考”，思考完正文可能已经没 token 了 —— 返回空答案。

        课堂用法是短问答，默认关掉思考；想要推理链时设 LOCAL_THINK=1。
        qwen2.5 这类不支持 think 的模型不传这个字段（传了会 400）。
        """
        raw = os.getenv("LOCAL_THINK")
        if raw is not None:
            return raw.strip().lower() not in ("0", "false", "no", "off", "")
        return False if self.model.lower().startswith("qwen3") else None

    def ask(self, prompt, temperature=0.7, max_tokens=800):
        return self.ask_messages([{"role": "user", "content": prompt}], temperature, max_tokens)

    def ask_messages(self, messages, temperature=0.7, max_tokens=800):
        import requests

        payload = {
            "model": self.model,
            "messages": messages,
            "options": {"temperature": temperature, "num_predict": max_tokens},
            "stream": False,
        }
        # qwen3 会先“自言自语”一段再作答：实测一句话问题要 1300+ token，
        # 默认 800 会在思考途中被截断 —— 结果是“只有思考、没有答案”，最难排查。
        if self.model.lower().startswith("qwen3") and max_tokens < 1800:
            payload["options"]["num_predict"] = 1800
        think = self._think()
        if think is not None:
            payload["think"] = think

        # trust_env=False：机房/校园网配了代理时，requests 会把 127.0.0.1 也送去代理。
        session = requests.Session()
        session.trust_env = False
        resp = session.post(f"http://{self.host}/api/chat", json=payload, timeout=self.timeout)
        resp.raise_for_status()            # 模型名打错返回 404，当场暴露，不返回空答案
        data = resp.json()
        if "error" in data:
            raise LLMError(f"本地服务返回错误：{data['error']}")
        content = (data.get("message") or {}).get("content", "").strip()
        # qwen3 把思考写在同一段正文里，以 </think> 结尾；只留它后面的最终答案
        if "</think>" in content:
            content = content.rsplit("</think>", 1)[1].strip()
        if not content:
            thinking = (data.get("message") or {}).get("thinking", "")
            hint = "（本次关掉了思考，" if self._think() is False else "（"
            raise LLMError(
                f"本地模型返回了空内容{hint}finish_reason={data.get('done_reason', '?')}）。"
                f"{'思考过程占了全部 token，可把 max_tokens 调大或设 LOCAL_THINK=1 观察；' if thinking else ''}"
                f"也可能是 num_predict 太小，试试 --max-tokens 800。")
        return content

    def __repr__(self):
        return f"<LocalEngine model={self.model} host={self.host}>"


class APIEngine:
    """云端引擎：客户端按需创建 —— 没配密钥也能纯本地跑（讲义片段 2 的坑）。"""

    name = "api"

    def __init__(self, model=None, base_url=None, timeout=None):
        self.model = model or os.getenv("DEEPSEEK_MODEL", DEFAULT_API_MODEL)
        self.base_url = (base_url or os.getenv("DEEPSEEK_BASE_URL", DEFAULT_API_BASE)).rstrip("/")
        self.timeout = float(timeout or os.getenv("DEEPSEEK_TIMEOUT", DEFAULT_API_TIMEOUT))
        self.client = None                 # 先不建客户端！

    def _ensure_client(self):
        if self.client is not None:
            return self.client
        key = (os.getenv("DEEPSEEK_API_KEY") or "").strip().strip('"').strip("'")
        if not key:
            raise LLMError("未配置 DEEPSEEK_API_KEY（本地引擎仍可用）")
        if any(ord(ch) > 127 for ch in key):
            raise LLMError(
                "DEEPSEEK_API_KEY 含非 ASCII 字符（多半还是 .env.example 的中文占位符），"
                "HTTP 头只能是 ASCII，请换成平台给的真密钥")
        import openai
        self.client = openai.OpenAI(base_url=self.base_url, api_key=key, timeout=self.timeout)
        return self.client

    def ask(self, prompt, temperature=0.7, max_tokens=800):
        return self.ask_messages([{"role": "user", "content": prompt}], temperature, max_tokens)

    def ask_messages(self, messages, temperature=0.7, max_tokens=800):
        client = self._ensure_client()     # 第一次真调用才建客户端
        resp = client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return (resp.choices[0].message.content or "").strip()

    def __repr__(self):
        return f"<APIEngine model={self.model} base_url={self.base_url}>"


class LLM:
    """统一入口：持有两个引擎，负责选路与双向回退；多轮时再加一层历史管理。"""

    def __init__(self, local_model=None, keep_turns=DEFAULT_KEEP_TURNS):
        self.local = LocalEngine(local_model)
        self.api = APIEngine()
        self.history = []                  # [{"role": "user"/"assistant", "content": str}]
        self.keep_turns = max(1, int(keep_turns))
        self.last = {}                     # 最近一次调用的元信息，给测试记录用

    # ------------------------------------------------------------------ 单轮
    def ask(self, prompt, prefer="local", **kw):
        """单轮：不带历史，也不写历史。W4/W5 的用法照旧。"""
        return self._ask_messages([{"role": "user", "content": prompt}], prefer, **kw)

    # ------------------------------------------------------------------ 多轮
    def chat(self, prompt, prefer="local", **kw):
        """多轮：把历史一起发过去，问完把回答也存回历史。

        为什么历史要裁：第 10 轮若不裁，prompt 里带着前面 9 轮的全部文字，
        云端按输入 token 计费 → 越聊越贵；本地小模型也会因为上下文太长而答偏。
        """
        self.history.append({"role": "user", "content": prompt})
        payload = self.history[-2 * self.keep_turns:]      # 最近 N 轮（一问一答为 1 轮）
        try:
            answer = self._ask_messages(payload, prefer, **kw)
        except Exception:
            self.history.pop()             # 失败就把这条 user 消息撤回，别留半截历史
            raise
        self.history.append({"role": "assistant", "content": answer})
        self.last["turns"] = len(self.history) // 2
        return answer

    def clear(self):
        """开新话题：清空记忆。不清的话，上一节课的内容会一直占着 context。"""
        self.history.clear()
        self.last = {}

    # ------------------------------------------------------------------ 内部
    def _ask_messages(self, messages, prefer="local", **kw):
        if prefer not in ("local", "api"):
            raise ValueError('prefer 只能是 "local" 或 "api"')
        first, second = (self.local, self.api) if prefer == "local" else (self.api, self.local)

        started = time.perf_counter()
        try:
            answer = first.ask_messages(messages, **kw)
        except Exception as exc:           # noqa: BLE001  —— 不吞：先打印，再换另一边
            print(f"[首选引擎失败，自动切换] {first.name} → {second.name}：{exc}")
            try:
                answer = second.ask_messages(messages, **kw)
            except Exception as exc2:      # noqa: BLE001
                raise LLMError(
                    f"两个引擎都失败：{first.name} -> {exc}；{second.name} -> {exc2}"
                ) from exc2
            self.last = {"engine": second.name, "fallback": True, "prefer": prefer,
                         "seconds": time.perf_counter() - started, "error": str(exc)}
            return answer

        self.last = {"engine": first.name, "fallback": False, "prefer": prefer,
                     "seconds": time.perf_counter() - started, "error": ""}
        return answer

    def __repr__(self):
        return (f"<LLM local={self.local.model} api={self.api.model} "
                f"turns={len(self.history) // 2}/{self.keep_turns}>")


def ask(prompt, prefer="local", **kw):
    """一句话版本（单轮）：from llm import ask; ask("…", prefer="api")"""
    return LLM().ask(prompt, prefer=prefer, **kw)


def meta_line(last: dict) -> str:
    """机器可读的一行摘要 —— 边界测试脚本靠它判断「实际走了哪个引擎」。"""
    if not last:
        return "[引擎] - | - | 回退: -"
    line = (f"[引擎] {last.get('engine', '-')} | {last.get('seconds', 0):.2f}s | "
            f"回退: {'是' if last.get('fallback') else '否'} | prefer={last.get('prefer', '-')}")
    if last.get("turns") is not None:
        line += f" | 第 {last['turns']} 轮"
    return line


def chat_loop(llm: LLM, prefer: str, temperature: float, max_tokens: int) -> int:
    """命令行多轮模式：/bye 退出，/clear 清空记忆，其余都当成提问。"""
    print(f"多轮对话（prefer={prefer}，记住最近 {llm.keep_turns} 轮）。"
          f"输入 /bye 退出，/clear 清空记忆。")
    print("-" * 62)
    while True:
        try:
            prompt = input("你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已退出。")
            return 0
        if prompt in ("/bye", "/exit", "exit", "quit"):
            print("已退出。")
            return 0
        if prompt == "/clear":
            llm.clear()
            print("（记忆已清空）")
            continue
        if not prompt:
            continue
        try:
            answer = llm.chat(prompt, prefer=prefer,
                              temperature=temperature, max_tokens=max_tokens)
        except LLMError as exc:
            print(f"错误：{exc}", file=sys.stderr)
            continue
        print(answer)
        print(meta_line(llm.last))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="llm.py", description="W6 双引擎：一句问题，两个引擎，prefer 切路；--chat 进多轮")
    parser.add_argument("prompt", nargs="*", help="要问的问题（--chat 模式下忽略）")
    parser.add_argument("--prefer", choices=("local", "api"), default="local",
                        help="先用哪个引擎（另一个作为回退）")
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--max-tokens", type=int, default=800, dest="max_tokens")
    parser.add_argument("--model", default=None, help="覆盖本地模型名，如 qwen3:4b")
    parser.add_argument("--chat", action="store_true", help="多轮对话模式（/bye 退出）")
    parser.add_argument("--keep-turns", type=int, default=DEFAULT_KEEP_TURNS, dest="keep_turns",
                        help=f"多轮时记住最近几轮（默认 {DEFAULT_KEEP_TURNS}）")
    args = parser.parse_args(argv)

    llm = LLM(local_model=args.model, keep_turns=args.keep_turns)

    if args.chat:
        return chat_loop(llm, args.prefer, args.temperature, args.max_tokens)

    prompt = " ".join(args.prompt).strip()
    if not prompt:
        try:
            prompt = input("问题> ").strip()
        except EOFError:
            print('错误：没有输入问题。用法：python llm.py "你的问题" --prefer local', file=sys.stderr)
            return 2

    try:
        answer = llm.ask(prompt, prefer=args.prefer,
                         temperature=args.temperature, max_tokens=args.max_tokens)
    except LLMError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1

    print(answer)
    print("-" * 62)
    print(meta_line(llm.last))
    return 0


if __name__ == "__main__":
    sys.exit(main())
