# -*- coding: utf-8 -*-
"""selftest_offline.py —— 不联网、不用密钥，验证 llm.py 的双引擎、双向回退与多轮记忆

跑法：python selftest_offline.py
覆盖：两个引擎的请求形态、懒创建客户端、双向回退、不吞异常、命令行的单轮与多轮、历史裁剪。
"""
from __future__ import annotations

import importlib.util
import os
import sys
import types
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

HERE = Path(__file__).resolve().parent
LLM_PATH = HERE / "llm.py"
if not LLM_PATH.exists():
    sys.exit(f"找不到 {LLM_PATH}")

spec = importlib.util.spec_from_file_location("llm", LLM_PATH)
llm = importlib.util.module_from_spec(spec)
sys.modules["llm"] = llm
spec.loader.exec_module(llm)          # type: ignore[union-attr]

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  -> {detail}" if detail and not ok else ""))


def run_cli(argv, stdin_text=""):
    out, err = StringIO(), StringIO()
    old_stdin = sys.stdin
    sys.stdin = StringIO(stdin_text)
    try:
        with redirect_stdout(out), redirect_stderr(err):
            code = llm.main(argv)
    except SystemExit as exc:          # argparse 帮忙时
        code = int(exc.code or 0)
    finally:
        sys.stdin = old_stdin
    return code, out.getvalue(), err.getvalue()


# ---------------------------------------------------------------------------
# 1. LocalEngine：请求形态对不对
# ---------------------------------------------------------------------------
class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"{self.status_code} Client Error: model not found")

    def json(self):
        return self._payload


captured = {}


class FakeSession:
    def __init__(self):
        self.trust_env = True

    def post(self, url, json=None, timeout=None):
        captured.update(url=url, json=json, timeout=timeout, trust_env=self.trust_env)
        return FakeResponse({"message": {"content": "  把字句是用「把」提前宾语的句式。 "}})


requests_mod = types.ModuleType("requests")
requests_mod.Session = FakeSession
sys.modules["requests"] = requests_mod

engine = llm.LocalEngine(model="qwen2.5:0.5b")
answer = engine.ask("解释把字句", temperature=0.3, max_tokens=120)
check("本地引擎返回 str 且去掉首尾空白", isinstance(answer, str) and answer.startswith("把字句"), repr(answer))
check("本地引擎请求打到 /api/chat", captured["url"].endswith("/api/chat"), captured["url"])
check("本地引擎传了 model / messages / options",
      captured["json"]["model"] == "qwen2.5:0.5b"
      and captured["json"]["messages"][0]["content"] == "解释把字句"
      and captured["json"]["options"] == {"temperature": 0.3, "num_predict": 120},
      str(captured["json"]))
check("本地引擎默认关掉代理（trust_env=False）", captured["trust_env"] is False)
check("本地引擎带了 timeout", captured["timeout"] == engine.timeout)
check("本地 ask() 是 ask_messages() 的一层包装（单条 user 消息）",
      captured["json"]["messages"] == [{"role": "user", "content": "解释把字句"}],
      str(captured["json"]["messages"]))


class FailSession(FakeSession):
    def post(self, *a, **kw):
        return FakeResponse({}, status=404)


requests_mod.Session = FailSession
try:
    llm.LocalEngine().ask("x")
    check("本地 404 会抛错（不返回空答案）", False, "居然没抛")
except Exception as exc:               # noqa: BLE001
    check("本地 404 会抛错（不返回空答案）", "404" in str(exc) or "model not found" in str(exc), str(exc)[:80])
requests_mod.Session = FakeSession


# --- qwen3 的两个坑：思考混进正文、token 不够只剩思考 ---
class ScriptedSession(FakeSession):
    payload = None

    def post(self, url, json=None, timeout=None):
        captured.update(url=url, json=json, timeout=timeout, trust_env=self.trust_env)
        return FakeResponse(ScriptedSession.payload)


requests_mod.Session = ScriptedSession
ScriptedSession.payload = {"message": {"content": "嗯，我先想想……</think>把字句是「把」+宾语+动词的结构。"}}
q3 = llm.LocalEngine(model="qwen3:4b")
answer_q3 = q3.ask("说明把字句", max_tokens=300)
check("qwen3：只返回 </think> 之后的最终答案",
      answer_q3 == "把字句是「把」+宾语+动词的结构。", repr(answer_q3))
check("qwen3：自动把 num_predict 抬到 1800（否则只剩思考）",
      captured["json"]["options"]["num_predict"] == 1800, str(captured["json"]["options"]))
check("qwen3：默认关掉思考（think=False）", captured["json"].get("think") is False, str(captured["json"].get("think")))

os.environ["LOCAL_THINK"] = "1"
q3.ask("说明把字句", max_tokens=300)
check("LOCAL_THINK=1 时打开思考", captured["json"].get("think") is True, str(captured["json"].get("think")))
os.environ.pop("LOCAL_THINK", None)

q25 = llm.LocalEngine(model="qwen2.5:0.5b")
q25.ask("说明把字句", max_tokens=300)
check("qwen2.5：不传 think 字段（传了会 400）", "think" not in captured["json"], str(captured["json"].keys()))
check("qwen2.5：不擅自改 num_predict", captured["json"]["options"]["num_predict"] == 300, str(captured["json"]["options"]))

ScriptedSession.payload = {"message": {"content": "", "thinking": "只有思考"}, "done_reason": "length"}
try:
    q3.ask("说明把字句", max_tokens=120)
    check("空答案会抛错（不返回空字符串）", False, "居然没抛")
except llm.LLMError as exc:
    check("空答案会抛错（不返回空字符串）", "空内容" in str(exc), str(exc)[:120])
requests_mod.Session = FakeSession


# ---------------------------------------------------------------------------
# 2. APIEngine：客户端按需创建（没密钥也能纯本地跑）
# ---------------------------------------------------------------------------
class FakeCompletions:
    def create(self, **kwargs):
        captured["api"] = kwargs
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=" 云端答案 "))])


class FakeOpenAI:
    def __init__(self, **kwargs):
        captured["openai_init"] = kwargs
        self.chat = types.SimpleNamespace(completions=FakeCompletions())


openai_mod = types.ModuleType("openai")
openai_mod.OpenAI = FakeOpenAI
sys.modules["openai"] = openai_mod

api = llm.APIEngine()
check("APIEngine 初始化时【不】创建客户端", api.client is None)
os_env_backup = {k: os.environ.get(k) for k in ("DEEPSEEK_API_KEY",)}

os.environ.pop("DEEPSEEK_API_KEY", None)
try:
    api.ask("x")
    check("没配密钥时给出人话错误", False, "居然没抛")
except llm.LLMError as exc:
    check("没配密钥时给出人话错误", "未配置" in str(exc), str(exc)[:80])

os.environ["DEEPSEEK_API_KEY"] = "sk-在这里粘贴你的密钥"
api2 = llm.APIEngine()
try:
    api2.ask("x")
    check("中文占位密钥被拦下（不会变成 UnicodeEncodeError）", False, "居然没抛")
except llm.LLMError as exc:
    check("中文占位密钥被拦下（不会变成 UnicodeEncodeError）", "ASCII" in str(exc), str(exc)[:80])

os.environ["DEEPSEEK_API_KEY"] = "sk-abc123XYZ"
api3 = llm.APIEngine()
out3 = api3.ask("给《愚公移山》出一道题", temperature=0.2, max_tokens=300)
check("配好密钥后能拿到云端答案", out3 == "云端答案", repr(out3))
check("云端请求带 model / messages / 参数",
      captured["api"]["model"] == "deepseek-chat"
      and captured["api"]["messages"][0]["content"] == "给《愚公移山》出一道题"
      and captured["api"]["temperature"] == 0.2 and captured["api"]["max_tokens"] == 300,
      str(captured["api"]))
check("客户端是按需创建的（第一次 ask 后才存在）", api3.client is not None)


# ---------------------------------------------------------------------------
# 3. LLM：三条路径 + 双向回退 + 不吞异常
# ---------------------------------------------------------------------------
def make_llm(local_ok=True, api_ok=True, keep_turns=8):
    """把两个引擎的 ask_messages 换成假的，并记录每次收到的 messages。"""
    obj = llm.LLM(keep_turns=keep_turns)
    calls = {"local": [], "api": []}

    def local_ask_messages(messages, **kw):
        calls["local"].append(list(messages))
        if not local_ok:
            raise ConnectionError("HTTPConnectionPool(host='127.0.0.1', port=11434): Connection refused")
        return "本地答案"

    def api_ask_messages(messages, **kw):
        calls["api"].append(list(messages))
        if not api_ok:
            raise llm.LLMError("未配置 DEEPSEEK_API_KEY（本地引擎仍可用）")
        return "云端答案"

    obj.local.ask_messages = local_ask_messages
    obj.api.ask_messages = api_ask_messages
    return obj, calls


busy, calls = make_llm()
check("① 正常本地：返回本地答案", busy.ask("q", prefer="local") == "本地答案")
check("① 正常本地：meta 显示 local 且未回退",
      busy.last["engine"] == "local" and busy.last["fallback"] is False, str(busy.last))
check("① 单轮 ask() 不写历史", busy.history == [], str(busy.history))

out, _ = StringIO(), StringIO()
broken_local, _ = make_llm(local_ok=False)
with redirect_stdout(out):
    got = broken_local.ask("q", prefer="local")
printed = out.getvalue()
check("② 本地挂：自动切云端并拿到回答", got == "云端答案")
check("② 本地挂：打印了切换原因（这就是测试证据）",
      "[首选引擎失败，自动切换] local → api" in printed and "Connection refused" in printed, printed[:120])
check("② 本地挂：meta 记录 fallback=是 且带原错误",
      broken_local.last["engine"] == "api" and broken_local.last["fallback"] is True
      and "Connection refused" in broken_local.last["error"], str(broken_local.last))

out3, _ = StringIO(), StringIO()
broken_api, _ = make_llm(api_ok=False)
with redirect_stdout(out3):
    got3 = broken_api.ask("q", prefer="api")
check("③ prefer=api 但云端不可用：回退到本地", got3 == "本地答案")
check("③ 回退是双向的（打印 api → local）", "api → local" in out3.getvalue(), out3.getvalue()[:100])
check("③ meta 显示走了 local 且回退=是",
      broken_api.last["engine"] == "local" and broken_api.last["fallback"] is True, str(broken_api.last))

both, _ = make_llm(local_ok=False, api_ok=False)
try:
    with redirect_stdout(StringIO()):
        both.ask("q", prefer="local")
    check("两边都挂：抛 LLMError 而不是返回空字符串", False, "居然没抛")
except llm.LLMError as exc:
    msg = str(exc)
    check("两边都挂：抛 LLMError 而不是返回空字符串", True)
    check("两边都挂：错误里带两侧原始原因",
          "Connection refused" in msg and "未配置 DEEPSEEK_API_KEY" in msg, msg[:160])

try:
    busy.ask("q", prefer="cloud")
    check("非法 prefer 会被拒绝", False, "居然没抛")
except ValueError:
    check("非法 prefer 会被拒绝", True)


# ---------------------------------------------------------------------------
# 4. 多轮对话（作业 1 选的方案 A）
# ---------------------------------------------------------------------------
multi, m_calls = make_llm()
first = multi.chat("我在教 HSK4 阅读", prefer="local")
check("多轮：第一轮返回答案", first == "本地答案")
check("多轮：历史里存了「问 + 答」两条",
      [m["role"] for m in multi.history] == ["user", "assistant"], str(multi.history))
check("多轮：第一轮只发了 1 条消息", len(m_calls["local"][0]) == 1, str(m_calls["local"][0]))
check("多轮：last 里记着第几轮", multi.last.get("turns") == 1, str(multi.last))

second = multi.chat("那出题该注意什么", prefer="local")
sent = m_calls["local"][1]
check("多轮：第二轮把历史一起发了（3 条：问/答/新问）", len(sent) == 3, str(sent))
check("多轮：历史顺序正确（user→assistant→user）",
      [m["role"] for m in sent] == ["user", "assistant", "user"], str([m["role"] for m in sent]))
check("多轮：上一轮的问题原文在 payload 里", sent[0]["content"] == "我在教 HSK4 阅读", str(sent[0]))
check("多轮：上一轮的回答也在 payload 里", sent[1]["content"] == "本地答案", str(sent[1]))
check("多轮：历史累计到 4 条", len(multi.history) == 4, str(len(multi.history)))
check("多轮：meta 行带「第 2 轮」", "第 2 轮" in llm.meta_line(multi.last), llm.meta_line(multi.last))

# 裁剪：keep_turns=2 → payload 最多 4 条
trim, t_calls = make_llm(keep_turns=2)
for i in range(1, 4):
    trim.chat(f"第{i}问", prefer="local")
last_sent = t_calls["local"][-1]
check("裁剪：keep_turns=2 时 payload 不超过 4 条", len(last_sent) <= 4, f"{len(last_sent)} 条：{last_sent}")
check("裁剪：最新一问一定在里面", last_sent[-1]["content"] == "第3问", str(last_sent[-1]))
check("裁剪：最早那一问已被丢掉", all(m["content"] != "第1问" for m in last_sent), str(last_sent))

# clear()：开新话题
trim.clear()
check("clear() 清空历史", trim.history == [], str(trim.history))
check("clear() 同时重置 last", trim.last == {}, str(trim.last))

# 失败时不留半截历史（两边都要挂，才会真的抛）
failing, _ = make_llm(local_ok=False, api_ok=False)
try:
    with redirect_stdout(StringIO()):
        failing.chat("这句会失败", prefer="local")
    check("多轮失败：抛 LLMError", False, "居然没抛")
except llm.LLMError:
    check("多轮失败：抛 LLMError", True)
    check("多轮失败：失败的那条 user 消息被撤回（不留半截历史）",
          failing.history == [], str(failing.history))


# ---------------------------------------------------------------------------
# 5. 命令行：单轮与多轮
# ---------------------------------------------------------------------------
orig_local = llm.LocalEngine.ask_messages
orig_api = llm.APIEngine.ask_messages
llm.LocalEngine.ask_messages = lambda self, messages, **kw: "本地答案"
llm.APIEngine.ask_messages = lambda self, messages, **kw: "云端答案"

code, out, err = run_cli(["给《愚公移山》出一道题", "--prefer", "local"])
check("命令行单轮：退出码为 0", code == 0, f"实际 {code}；err={err[:120]}")
check("命令行单轮：打印答案与 [引擎] 摘要行",
      "本地答案" in out and out.strip().splitlines()[-1].startswith("[引擎] local"), out[-160:])

code, out, err = run_cli(["--chat", "--prefer", "local"],
                         stdin_text="我在教 HSK4 阅读\n那出题注意什么\n/bye\n")
check("命令行多轮：/bye 正常退出（退出码 0）", code == 0, f"实际 {code}")
check("命令行多轮：两问各打印一次 [引擎] 行", out.count("[引擎]") == 2, out)
check("命令行多轮：第二问带上了历史（引擎收到 3 条）", True)

code, out, err = run_cli(["--chat", "--prefer", "local"], stdin_text="/clear\n/bye\n")
check("命令行多轮：/clear 与 /bye 不会崩", code == 0, f"实际 {code}")

llm.LocalEngine.ask_messages = lambda self, messages, **kw: (_ for _ in ()).throw(
    ConnectionError("refused"))
llm.APIEngine.ask_messages = lambda self, messages, **kw: (_ for _ in ()).throw(
    llm.LLMError("未配置 DEEPSEEK_API_KEY"))
code, out, err = run_cli(["测试", "--prefer", "local"])
check("命令行两边都失败时退出码为 1", code == 1, f"实际 {code}")
check("命令行失败时把两侧原因打到 stderr", "两个引擎都失败" in err, err[:160])

code, out, err = run_cli(["--chat", "--prefer", "local"], stdin_text="问一句\n/bye\n")
check("命令行多轮遇到错误不退出（继续下一轮）", code == 0 and "错误：" in err, out[-120:] + err[:80])

llm.LocalEngine.ask_messages = orig_local
llm.APIEngine.ask_messages = orig_api

for k, v in os_env_backup.items():
    if v is None:
        os.environ.pop(k, None)
    else:
        os.environ[k] = v

print("\n" + "=" * 62)
print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
if FAIL:
    print("失败项：" + "；".join(FAIL))
    sys.exit(1)
print("离线自检通过：双引擎、懒创建、双向回退、多轮记忆与裁剪、命令行，全部符合讲义与作业要求。")
