# -*- coding: utf-8 -*-
"""week4_api_bot.py —— 第4周交付物：命令行学科问答机器人

用法（在本文件所在目录、或仓库根目录都行）：
    python week4_api_bot.py "把字句的教学难点有哪些"
    python week4_api_bot.py "HSK4 需要多少词汇量" --temperature 0.0
    python week4_api_bot.py "给中级作文写三段式评语" --max-tokens 15    # 看截断
    python week4_api_bot.py                                            # 不带问题 → 交互输入

一次调用只需要四个要素：base_url（去哪）、api_key（我是谁）、model（用哪个）、messages（问什么）。
密钥只从环境变量 / .env 读，代码里永远不出现 sk- 开头的字符串。
"""
from __future__ import annotations

import argparse
import datetime
import math
import os
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# 〇、路径与默认配置（换平台基本只动这里）
# ---------------------------------------------------------------------------
HERE = Path(__file__).resolve().parent
# 讲义约定：脚本放在 week04_API/，日志落在仓库根目录（代码包根目录），
# 这样不管从哪个目录运行、.gitignore 都拦得住。
ROOT = HERE.parent if HERE.name.lower() == "week04_api" else HERE

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"      # ② 换平台改这两行
DEFAULT_MODEL = "deepseek-chat"                       #    通义：dashscope compatible-mode + qwen-plus
DEFAULT_TEMPERATURE = 0.7
DEFAULT_MAX_TOKENS = 800
DEFAULT_TIMEOUT = 60.0
KEY_NAME = "DEEPSEEK_API_KEY"
LOG_NAME = "chat_log.txt"

_client = None          # ③ 按需创建：缺密钥时不至于 import 阶段就崩
last_usage: dict = {}   # 最近一次调用的账单信息，供第4步算费用


class BotError(RuntimeError):
    """所有“人话”错误都用它抛出，主程序统一打印、不抛堆栈。"""


# ---------------------------------------------------------------------------
# 一、配置读取
# ---------------------------------------------------------------------------
def _parse_env_file(path: Path) -> None:
    """不依赖 python-dotenv 的兜底解析：KEY=VALUE，忽略注释与空行。"""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:      # 不覆盖已存在的环境变量
            os.environ[key] = value


def load_env() -> str | None:
    """① 必须显式加载 .env —— Windows 下 os.getenv() 读不到文件里的键值。"""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        import weekpath  # 课程仓库自带的路径/环境助手（第12周讲原理），有就用
        weekpath.load_env()
        return "weekpath"
    except Exception:
        pass
    try:
        from dotenv import load_dotenv
        for candidate in (ROOT / ".env", HERE / ".env"):
            if candidate.exists():
                load_dotenv(candidate, override=False)
        return "dotenv"
    except Exception:
        pass
    for candidate in (ROOT / ".env", HERE / ".env"):
        if candidate.exists():
            _parse_env_file(candidate)
            return f"builtin:{candidate}"
    return None


def base_url() -> str:
    return (os.getenv("DEEPSEEK_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/")


def model() -> str:
    return (os.getenv("DEEPSEEK_MODEL") or DEFAULT_MODEL).strip()


def default_timeout() -> float:
    try:
        return float(os.getenv("DEEPSEEK_TIMEOUT", "") or DEFAULT_TIMEOUT)
    except ValueError:
        return DEFAULT_TIMEOUT


# ---------------------------------------------------------------------------
# 二、客户端与调用
# ---------------------------------------------------------------------------
def missing_key_message() -> str:
    env_path = ROOT / ".env"
    return (
        f"错误：未设置 {KEY_NAME}。\n"
        f"处理：在 {env_path} 里写一行  {KEY_NAME}=sk-你的密钥\n"
        f"      没有 .env 就先把 .env.example 复制成 .env；改完重试即可（脚本每次都会重读 .env）。\n"
        f"（本次没有发出任何请求，也没有产生费用）"
    )


PLACEHOLDER_HINTS = ("在这里", "粘贴", "你的密钥", "replace", "your-key", "xxxx", "改成")


def check_key(key: str) -> str:
    """发请求之前就把“密钥没填对”拦住 —— 这类错误以前会伪装成 UnicodeEncodeError。

    HTTP 头只能是 ASCII，密钥里混进中文，SDK 会在联网之前就抛
    `'ascii' codec can't encode characters`，看着像代码 bug，其实是 .env 没改。
    """
    if not key:
        raise BotError(missing_key_message())
    bad = sorted({ch for ch in key if ord(ch) > 127})
    if bad:
        raise BotError(
            f"错误：{KEY_NAME} 里含非 ASCII 字符（{'、'.join(bad[:3])} …），这不是有效密钥。\n"
            f"      最常见原因：.env 还是 .env.example 的占位符，没换成真密钥。\n"
            f"      处理：打开 .env，把 {KEY_NAME}= 后面【整段】删掉，粘贴平台后台复制的密钥\n"
            f"            （形如 sk- 加一串英文字母数字，纯英文、不带引号、不带空格）；\n"
            f"            保存后直接重跑本条命令，不必重开终端。\n"
            f"（本次没有发出任何请求，也没有产生费用）"
        )
    lowered = key.lower()
    if any(hint in lowered for hint in PLACEHOLDER_HINTS):
        raise BotError(
            f"错误：{KEY_NAME} 看起来还是占位符（{key[:12]}…）。\n"
            f"      处理：把 .env 里这一行换成平台后台复制的真实密钥（sk- + 32 位字母数字），保存后重跑。\n"
            f"（本次没有发出任何请求，也没有产生费用）"
        )
    return key


def get_client():
    """③ 按需创建客户端：把“缺密钥/缺库/密钥写错”变成一句人话，而不是一堆堆栈。"""
    global _client
    if _client is not None:
        return _client
    key = (os.getenv(KEY_NAME) or "").strip().strip('"').strip("'")
    key = check_key(key)
    try:
        import openai
    except ModuleNotFoundError as exc:
        raise BotError(
            "错误：未安装 openai 库。处理：在终端执行 pip install openai python-dotenv"
        ) from exc
    _client = openai.OpenAI(base_url=base_url(), api_key=key, timeout=default_timeout())
    return _client


def explain_error(exc: Exception) -> str:
    """把异常翻译成“先判断，再决定问谁”的那句话（讲义第13页）。"""
    name = type(exc).__name__
    text = str(exc) or name
    blob = f"{name} {text}".lower()
    if isinstance(exc, UnicodeEncodeError) or "ascii' codec" in blob:
        return ("错误：请求头里有非 ASCII 字符（多半是密钥或模型名写成了中文）。\n"
                "      处理：检查 .env 的 DEEPSEEK_API_KEY 是否还是占位符，"
                "密钥必须是平台给的英文数字串。")
    if "authentication" in blob or "401" in text or "invalid api key" in blob \
            or "incorrect api key" in blob:
        return ("错误：密钥无效（401 Authentication Fails）。多为密钥抄错、已失效、"
                "或粘贴时带了空格/引号。处理：去平台后台重新生成，重新写入 .env。")
    if "402" in text or "insufficient" in blob or "balance" in blob or "quota" in blob:
        return ("错误：账户余额/额度不足。处理：到平台充值，或改用课堂共享密钥"
                "（共享密钥课后作废）。")
    if "timeout" in blob or "timed out" in blob:
        return ("错误：请求超时，请检查网络或调大 timeout。校园网抖动、或答案太长都会这样；"
                "先把 --max-tokens 调小重试，或加 --timeout 120。")
    if "rate" in blob and "limit" in blob:
        return "错误：请求太频繁（429）。等十几秒再试，别在死循环里狂调。"
    if "connect" in blob or "network" in blob or "getaddrinfo" in blob or "ssl" in blob:
        return ("错误：连不上服务器（APIConnectionError）。检查 base_url 是否写对"
                "（应带 /v1）、网络/代理是否正常；换手机热点再试一次。")
    return f"错误：调用失败（{name}）。原文：{text}"


def ask(question: str, temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        timeout: float | None = None) -> str:
    """问一句、拿答案正文。只调一次 —— 每次调用都计费。"""
    global last_usage
    question = (question or "").strip()
    if not question:
        raise BotError('错误：问题是空的。用法：python week4_api_bot.py "你的问题"')
    if timeout is None:
        timeout = default_timeout()

    client = get_client()
    started = time.perf_counter()
    try:
        response = client.chat.completions.create(
            model=model(),
            messages=[{"role": "user", "content": question}],   # 问什么
            temperature=temperature,                            # 发散度
            max_tokens=max_tokens,                              # 长度上限
            timeout=timeout,
        )
    except BotError:
        raise
    except Exception as exc:                                    # noqa: BLE001
        raise BotError(explain_error(exc)) from exc
    elapsed = time.perf_counter() - started

    choice = response.choices[0]
    answer = (choice.message.content or "").strip()
    usage = getattr(response, "usage", None)
    last_usage = {
        "model": model(),
        "temperature": temperature,
        "max_tokens": max_tokens,
        "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
        "finish_reason": getattr(choice, "finish_reason", "") or "",
        "elapsed": elapsed,
    }
    if not answer:
        raise BotError("错误：模型返回了空内容。多半是 max_tokens 太小或内容被安全策略拦截，"
                       "把 --max-tokens 调到 300 以上再试。")
    return answer


# ---------------------------------------------------------------------------
# 三、账单与日志
# ---------------------------------------------------------------------------
def estimate_cost(usage: dict) -> float | None:
    """单价不写死在代码里，由你按平台价目页填到 .env（元 / 百万 token）。"""
    try:
        price_in = float((os.getenv("PRICE_INPUT_PER_M") or "").strip())
        price_out = float((os.getenv("PRICE_OUTPUT_PER_M") or "").strip())
    except ValueError:
        return None
    if math.isnan(price_in) or math.isnan(price_out):
        return None
    return (usage["prompt_tokens"] / 1_000_000 * price_in
            + usage["completion_tokens"] / 1_000_000 * price_out)


def log_path() -> Path:
    override = (os.getenv("WEEK4_LOG_DIR") or "").strip()
    return Path(override).expanduser() / LOG_NAME if override else ROOT / LOG_NAME


def append_log(question: str, answer: str, usage: dict) -> Path:
    """⑤ 日志统一落代码包根目录；绝不写密钥。"""
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cost = estimate_cost(usage)
    cost_text = f" | cost≈¥{cost:.6f}" if cost is not None else ""
    block = "\n".join([
        "=" * 78,
        f"时间 {stamp} | 模型 {usage['model']} | temperature={usage['temperature']} "
        f"| max_tokens={usage['max_tokens']}",
        f"Q: {question}",
        f"A: {answer}",
        f"usage: prompt={usage['prompt_tokens']} completion={usage['completion_tokens']} "
        f"total={usage['total_tokens']} | finish_reason={usage['finish_reason'] or '-'} "
        f"| elapsed={usage['elapsed']:.2f}s{cost_text}",
        "",
    ])
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(block)
    return path


def usage_line(usage: dict) -> str:
    cost = estimate_cost(usage)
    parts = [
        f"prompt_tokens={usage['prompt_tokens']}",
        f"completion_tokens={usage['completion_tokens']}",
        f"total={usage['total_tokens']}",
        f"耗时={usage['elapsed']:.2f}s",
    ]
    if usage.get("finish_reason"):
        parts.append(f"finish_reason={usage['finish_reason']}")
    line = "费用相关：" + "  ".join(parts)
    if cost is not None:
        line += f"  本次≈¥{cost:.6f}"
    else:
        line += ("\n（想直接看钱：在 .env 里填 PRICE_INPUT_PER_M / PRICE_OUTPUT_PER_M，"
                 "单位 元/百万token，单价去平台价目页查）")
    return line


# ---------------------------------------------------------------------------
# 四、命令行入口
# ---------------------------------------------------------------------------
def _fix_console() -> None:
    """命令行走纯 ASCII 编码时也别崩（不影响 GBK 终端正常显示）。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            if (stream.encoding or "").lower() not in ("utf-8", "utf8", "gbk", "cp936"):
                stream.reconfigure(errors="replace")     # type: ignore[attr-defined]
        except Exception:
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="week4_api_bot.py",
        description="第4周命令行学科问答机器人：问一句 → 调 API → 打印 → 追加 chat_log.txt",
        epilog='例：python week4_api_bot.py "把字句的教学难点有哪些" --temperature 0.0',
    )
    parser.add_argument("question", nargs="*", help="要问的问题（不加引号也行，会拼起来）")
    parser.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE,
                        help=f"发散度，0.0 最稳、1.5 最活（默认 {DEFAULT_TEMPERATURE}）")
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS, dest="max_tokens",
                        help=f"答案长度上限（默认 {DEFAULT_MAX_TOKENS}；调成 15 可看截断）")
    parser.add_argument("--timeout", type=float, default=None,
                        help=f"超时秒数（默认 {DEFAULT_TIMEOUT:g}）")
    parser.add_argument("--no-log", action="store_true", help="只打印，不写 chat_log.txt")
    parser.add_argument("--log-dir", default=None, help="日志目录（默认写到代码包根目录）")
    return parser


def main(argv: list[str] | None = None) -> int:
    _fix_console()
    mode = load_env()                     # ① 先加载 .env
    args = build_parser().parse_args(argv)
    if args.log_dir:
        os.environ["WEEK4_LOG_DIR"] = args.log_dir

    # ④ 先检查再调用：密钥没配/写错，在问问题、发请求之前就拦住
    #    （密钥里混进中文时，SDK 会抛 UnicodeEncodeError，看不出真正原因）
    try:
        check_key((os.getenv(KEY_NAME) or "").strip().strip('"').strip("'"))
    except BotError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    question = " ".join(args.question).strip()
    if not question:
        try:
            question = input("问题> ").strip()
        except EOFError:                     # 管道里没有输入，别抛堆栈
            print('错误：没有输入问题。用法：python week4_api_bot.py "你的问题"', file=sys.stderr)
            return 2
        except KeyboardInterrupt:
            print("\n已取消。", file=sys.stderr)
            return 130
    if not question:
        print('错误：没有输入问题。用法：python week4_api_bot.py "你的问题"', file=sys.stderr)
        return 2

    try:
        answer = ask(question, args.temperature, args.max_tokens, args.timeout)
    except BotError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n已中断（可能已计费）。", file=sys.stderr)
        return 130

    print(answer)
    print("-" * 72)
    print(usage_line(last_usage))
    if last_usage.get("finish_reason") == "length":
        print("提示：finish_reason=length —— 答案被 max_tokens 硬截断了，"
              "这不是模型出错，把 --max-tokens 调大即可。")
    if args.no_log:
        print("（--no-log：本次未写日志）")
    else:
        path = append_log(question, answer, last_usage)
        print(f"已追加日志：{path}")
    if mode:
        print(f"（.env 加载方式：{mode}；base_url={base_url()} model={model()}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
