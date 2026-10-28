# -*- coding: utf-8 -*-
"""selfcheck_offline.py —— 不用密钥、不联网，验证 week4_api_bot.py 的行为是否正确。

课堂用途：跑一遍就知道“缺密钥 / 缺库 / 401 / 超时 / 截断 / 日志与费用”这六件事，
你的脚本是不是都处理成了人话；也顺手证明你没有把密钥写进代码。

运行：  python selfcheck_offline.py
"""
from __future__ import annotations

import importlib.util
import builtins
import os
import re
import shutil
import sys
import types
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

HERE = Path(__file__).resolve().parent
BOT_PATH = HERE / "week4_api_bot.py"

if not BOT_PATH.exists():
    sys.exit(f"找不到 {BOT_PATH}，请把本文件和 week4_api_bot.py 放在同一目录。")

spec = importlib.util.spec_from_file_location("week4_api_bot", BOT_PATH)
bot = importlib.util.module_from_spec(spec)
sys.modules["week4_api_bot"] = bot
spec.loader.exec_module(bot)                       # type: ignore[union-attr]

TMP = HERE / "_selfcheck_tmp"          # 放在本目录里，避免系统临时目录的权限问题
if TMP.exists():
    shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True, exist_ok=True)
PASS, FAIL = [], []

# 自检必须不受仓库里真实 .env 影响：否则“缺密钥”这类用例会被真实密钥顶掉。
# .env 的解析逻辑另外单独测（见最后一节 _parse_env_file）。
bot.load_env = lambda: None


def check(name: str, condition: bool, detail: str = "") -> None:
    (PASS if condition else FAIL).append(name)
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f"  -> {detail}" if detail and not condition else ""))


def run(argv: list[str], stdin_text: str = "") -> tuple[int, str, str]:
    out, err = StringIO(), StringIO()
    old_stdin = sys.stdin
    sys.stdin = StringIO(stdin_text)
    bot._client = None
    try:
        with redirect_stdout(out), redirect_stderr(err):
            code = bot.main(argv)
    finally:
        sys.stdin = old_stdin
    return code, out.getvalue(), err.getvalue()


def fresh_env(**env: str) -> None:
    for key in ("DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL", "DEEPSEEK_TIMEOUT",
                "PRICE_INPUT_PER_M", "PRICE_OUTPUT_PER_M", "WEEK4_LOG_DIR"):
        os.environ.pop(key, None)
    os.environ.update(env)
    bot._client = None
    for leftover in TMP.rglob("chat_log.txt"):
        leftover.unlink()


# --------------------------------------------------------------------------
# 假 openai：只模拟 create() 的返回结构与可抛的异常类型
# --------------------------------------------------------------------------
class FakeChoice:
    def __init__(self, content: str, finish_reason: str = "stop") -> None:
        self.message = types.SimpleNamespace(content=content)
        self.finish_reason = finish_reason


class FakeUsage:
    prompt_tokens = 11
    completion_tokens = 49
    total_tokens = 60


class FakeResponse:
    def __init__(self, content: str, finish_reason: str = "stop") -> None:
        self.choices = [FakeChoice(content, finish_reason)]
        self.usage = FakeUsage()


def install_fake_openai(behavior) -> None:
    """behavior(client_kwargs) -> 响应对象，或直接抛异常。"""
    class Completions:
        def create(self, **kwargs):
            return behavior(kwargs)

    class Chat:
        completions = Completions()

    class Client:
        def __init__(self, **kwargs):
            self.init_kwargs = kwargs
            self.chat = Chat()

    module = types.ModuleType("openai")
    module.OpenAI = Client                      # type: ignore[attr-defined]
    sys.modules["openai"] = module
    bot._client = None


def uninstall_fake_openai() -> None:
    sys.modules.pop("openai", None)
    bot._client = None


print(f"临时日志目录：{TMP}\n")

# 1. 缺密钥 → 退出码 2、人话提示、不发请求、不写日志 -------------------------
fresh_env(WEEK4_LOG_DIR=str(TMP))
code, out, err = run(['把字句的教学难点有哪些'])
check("缺密钥时退出码为 2", code == 2, f"实际 {code}")
check("缺密钥时提示设置 DEEPSEEK_API_KEY", "未设置 DEEPSEEK_API_KEY" in err, err[:120])
check("缺密钥时不写日志", not list(TMP.rglob("chat_log.txt")))
check("缺密钥时明确说明没产生费用", "没有产生费用" in err)

# 2. 有密钥但没装 openai 库 → 提示 pip install，而不是堆栈 -------------------
#    注意：这台机器可能真的装了 openai，所以用导入钩子强行模拟“没装”，
#    否则这一条会真的去联网（拿假密钥换回 401），而自检承诺不联网。
fresh_env(DEEPSEEK_API_KEY="sk-fake", WEEK4_LOG_DIR=str(TMP))
uninstall_fake_openai()
_real_import = builtins.__import__


def _block_openai(name, *args, **kwargs):
    if name == "openai" or name.startswith("openai."):
        raise ModuleNotFoundError("No module named 'openai'")
    return _real_import(name, *args, **kwargs)


builtins.__import__ = _block_openai
try:
    code, out, err = run(['测试'])
finally:
    builtins.__import__ = _real_import
check("缺 openai 库时退出码为 1", code == 1, f"实际 {code}")
check("缺 openai 库时提示 pip install", "pip install openai" in err, err[:160])

# 3. 正常调用（假响应）：打印答案、写日志、算费用 -----------------------------
fresh_env(DEEPSEEK_API_KEY="sk-fake", WEEK4_LOG_DIR=str(TMP),
          PRICE_INPUT_PER_M="2", PRICE_OUTPUT_PER_M="8")
install_fake_openai(lambda kwargs: FakeResponse("把字句是用“把”将宾语提前的句式。"))
code, out, err = run(['把字句的教学难点有哪些', '--temperature', '0.0', '--max-tokens', '800'])
log = (TMP / "chat_log.txt")
check("正常调用退出码为 0", code == 0, f"实际 {code}；stderr={err[:200]}")
check("答案被打印到终端", "把字句是用" in out, out[:200])
check("终端显示 token 用量", "prompt_tokens=11" in out and "completion_tokens=49" in out, out[-300:])
# 11/1e6*2 + 49/1e6*8 = 0.000414
check("按 .env 单价算出费用 ¥0.000414", "0.000414" in out, out[-300:])
check("日志文件已生成在指定目录", log.exists())
if log.exists():
    text = log.read_text(encoding="utf-8")
    check("日志含问题", "Q: 把字句的教学难点有哪些" in text)
    check("日志含答案", "A: 把字句是用" in text)
    check("日志含 usage 与参数", "temperature=0.0" in text and "total=60" in text)
    check("日志里不含密钥", "sk-fake" not in text)
check("日志写在代码包根目录（未指定时为仓库根）",
      str(bot.log_path()).endswith("chat_log.txt"))
check("默认日志名是 chat_log.txt", bot.log_path().name == "chat_log.txt")
os.environ.pop("WEEK4_LOG_DIR", None)
check("未指定日志目录时落在代码包根目录",
      bot.log_path() == bot.ROOT / "chat_log.txt" and bot.ROOT.name.lower() != "week04_api",
      f"ROOT={bot.ROOT}")
os.environ["WEEK4_LOG_DIR"] = str(TMP)

# 4. 401 → 让人知道是密钥问题 ------------------------------------------------
fresh_env(DEEPSEEK_API_KEY="sk-fake", WEEK4_LOG_DIR=str(TMP))


def raise_auth(_kwargs):
    error = type("AuthenticationError", (Exception,), {})
    raise error("Error code: 401 - Authentication Fails, Your api key is invalid")


install_fake_openai(raise_auth)
code, out, err = run(['测试 401'])
check("401 时退出码为 1", code == 1, f"实际 {code}")
check("401 时提示密钥无效", "密钥无效" in err, err[:200])

# 5. 超时 → 提示网络/超时，而不是原始堆栈 ------------------------------------
fresh_env(DEEPSEEK_API_KEY="sk-fake", WEEK4_LOG_DIR=str(TMP))


def raise_timeout(_kwargs):
    error = type("APITimeoutError", (Exception,), {})
    raise error("Request timed out.")


install_fake_openai(raise_timeout)
code, out, err = run(['测试超时'])
check("超时退出码为 1", code == 1, f"实际 {code}")
check("超时提示检查网络/调大 timeout", "请求超时" in err and "timeout" in err, err[:200])

# 6. finish_reason=length → 明确告诉学生“这是被截断，不是模型坏了” -----------
fresh_env(DEEPSEEK_API_KEY="sk-fake", WEEK4_LOG_DIR=str(TMP))
install_fake_openai(lambda kwargs: FakeResponse("把字句是汉语中一种用介词“把”将动词的",
                                               finish_reason="length"))
code, out, err = run(['用一句话说明什么是把字句', '--max-tokens', '15'])
check("截断调用仍退出码 0", code == 0, f"实际 {code}")
check("截断时提示 finish_reason=length", "finish_reason=length" in out, out[-300:])
check("截断时建议调大 max_tokens", "max_tokens" in out and "调大" in out, out[-300:])

# 7. 空问题 / 无参数且无输入 → 友好报错，不崩 --------------------------------
fresh_env(DEEPSEEK_API_KEY="sk-fake", WEEK4_LOG_DIR=str(TMP))
code, out, err = run([], stdin_text="")
check("无参数且无输入时退出码为 2 且不崩", code == 2, f"实际 {code}")
check("空问题给出用法提示", "用法" in err or "没有输入问题" in err, err[:200])

# 8. 静态检查：源码里不能出现 sk- 开头的密钥字面量 ---------------------------
source = BOT_PATH.read_text(encoding="utf-8")
leaked = re.findall(r"sk-[A-Za-z0-9_\-]{16,}", source)
check("脚本源码中没有真实密钥字样", not leaked, str(leaked[:3]))

# 8.5 密钥写错（占位符/中文）→ 联网之前就拦住，不能伪装成 UnicodeEncodeError
fresh_env(WEEK4_LOG_DIR=str(TMP))
for bad_key, expect, label in [
    ("sk-在这里粘贴你的密钥", "非 ASCII", "中文占位符"),
    ("sk-REPLACE_ME", "占位符", "英文占位符"),
]:
    os.environ["DEEPSEEK_API_KEY"] = bad_key
    bot._client = None
    err = ""
    try:
        bot.get_client()
    except bot.BotError as exc:
        err = str(exc)
    check(f"{label}密钥被拦下", bool(err), "居然通过了校验")
    check(f"{label}密钥的提示包含“{expect}”", expect in err, err[:160])
    check(f"{label}密钥不产生费用", "没有产生费用" in err, err[:160])

try:
    check("正常密钥能通过校验", bot.check_key("sk-abc123XYZ") == "sk-abc123XYZ")
except bot.BotError as exc:
    check("正常密钥能通过校验", False, str(exc))

# 9. .env 兜底解析（没装 python-dotenv 时也能读） ----------------------------
env_sample = TMP / ".env.sample"
env_sample.write_text(
    "# 注释行\n\nDEEPSEEK_API_KEY=\"sk-from-file\"\nDEEPSEEK_MODEL=qwen-plus\n",
    encoding="utf-8",
)
os.environ.pop("SELFCHECK_FROM_FILE", None)
os.environ.pop("DEEPSEEK_API_KEY", None)
os.environ["DEEPSEEK_MODEL"] = "already-set"          # 已存在的变量不能被文件覆盖
bot._parse_env_file(env_sample)
check("兜底解析读到文件里的键", os.getenv("DEEPSEEK_API_KEY") == "sk-from-file",
      str(os.getenv("DEEPSEEK_API_KEY")))
check("兜底解析去掉引号", '"' not in (os.getenv("DEEPSEEK_API_KEY") or '"'))
check("兜底解析不覆盖已有环境变量", os.getenv("DEEPSEEK_MODEL") == "already-set")

print("\n" + "=" * 60)
print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
if FAIL:
    print("失败项：" + "；".join(FAIL))
    sys.exit(1)
print("离线自检全部通过：缺少密钥/缺库/401/超时/截断/费用/日志，行为都符合讲义要求。")
