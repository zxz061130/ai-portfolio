# 第4周 · 第一次 API 调用：把 AI 装进你的程序

**今天要交的三样（讲义第3页）**

| # | 交付物 | 判定标准 |
|---|--------|----------|
| 1 | `week4_api_bot.py` 能跑 | 命令行问一句，终端出答案，不报错 |
| 2 | `chat_log.txt` 里 3 次学科问答 | 3 个问题都是你本学科真实的教学问题 |
| 3 | 密钥安全自查表 | 5 项全打钩；`git status` 里没有 `.env` |

评的是 **跑得通 + 密钥零泄露 + 能讲清参数**，不是代码多花哨。

---

## 0. 包里有什么

```
week04_API/
├─ week4_api_bot.py      ← 交付物 1：机器人本体（可以直接用，但要能逐行讲清）
├─ .env.example          ← 配置模板：复制成 .env 再填密钥
├─ .gitignore            ← 已把 .env 排除，别删这一条
├─ selfcheck_offline.py  ← 离线自检：不用密钥、不联网，验证脚本行为（31 项）
├─ README.md             ← 本文件：五步操作手册
├─ 参数体验表.md          ← 交付物 3 的一部分：第3步填完
└─ 密钥安全自查表.md      ← 交付物 3：逐项打钩
```

跑起来只有一条命令：

```powershell
python week4_api_bot.py "把字句的教学难点有哪些"
```

---

## 1. 准备：装库 + 填密钥（5′）

```powershell
python -m pip install openai python-dotenv     # 用 python -m pip，避免装到别的解释器
Copy-Item .env.example .env                    # macOS/Linux: cp .env.example .env
notepad .env                                   # 把 DEEPSEEK_API_KEY= 后面换成你的密钥
```

`.env` 长这样（**这个文件永远不提交**）：

```ini
DEEPSEEK_API_KEY=sk-你的密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-chat
PRICE_INPUT_PER_M=2          # 元/百万 token，去平台价目页查，按当期价格填
PRICE_OUTPUT_PER_M=8
```

**复制完先别急着花钱**，跑一次离线自检（不联网、不用密钥、不写真实日志）：

```powershell
python selfcheck_offline.py
```

期望结尾：`通过 31 项，失败 0 项`。这一步能确认"缺密钥、缺库、401、超时、截断、费用、日志"这些分支都是人话提示，而不是一堆红字堆栈。

> 换平台（通义/其他 OpenAI 兼容平台）只改 `.env` 两行：`DEEPSEEK_BASE_URL` 和 `DEEPSEEK_MODEL`，代码一个字不动。这就是讲义第6页说的"换平台只改两行"。

---

## 2. 第 1 步：跑通第一句（5′）

```powershell
python week4_api_bot.py "把字句的教学难点有哪些"
```

看到答案 + 下面这几行，就是成功（示意输出）：

```
把字句的教学难点主要有三：一是“把”后宾语的定指性，二是动词的及物性与处置义，三是补语搭配的限制。
------------------------------------------------------------------------
费用相关：prompt_tokens=14  completion_tokens=96  total=110  耗时=1.32s  finish_reason=stop  本次≈¥0.000796
已追加日志：D:\你的仓库\chat_log.txt
（.env 加载方式：dotenv；base_url=https://api.deepseek.com/v1 model=deepseek-chat）
```

**注意两点：**

1. 命令里的引号必须是英文 `"`。用中文引号 `“”`，问题会被 shell 拆开，程序只收到半句。
2. 日志落在**代码包根目录**（脚本在 `week04_API/` 时，写到你仓库根目录的 `chat_log.txt`），不管你在哪个目录运行都一样。

---

## 3. 第 2 步：换上你自己的 3 个学科问题（10′）

示范轨（汉语国际教育）的三条，直接复制：

```powershell
python week4_api_bot.py "把字句的教学难点有哪些"
python week4_api_bot.py "HSK4 需要掌握多少词汇量？教学上怎么分配"
python week4_api_bot.py "给中级水平留学生作文写一段三段式评语：优点、问题、下一步练习"
```

要求：**换成你自己学科**的 3 个真实教学问题（不是"你好""1+1 等于几"这种）。跑完打开 `chat_log.txt`，确认有 3 段完整记录——这是交付物 2 的证据。

三条问题跑完，把 `chat_log.txt` 一起提交；日志里只有问题、答案和 token，不含密钥。

---

## 4. 第 3 步：参数体验，填表（10′）

同一个问题，换参数各跑一次，记录"你设的值 + 你看到的现象"：

```powershell
python week4_api_bot.py "用一句话说明什么是把字句" --temperature 0.0
python week4_api_bot.py "用一句话说明什么是把字句" --temperature 1.5
python week4_api_bot.py "用一句话说明什么是把字句" --max-tokens 15
python week4_api_bot.py "用一句话说明什么是把字句" --max-tokens 800
```

看两个信号：

- `temperature`：0.0 两次几乎一字不差；1.5 措辞更活、可能跑题。**教学材料建议 0.2–0.7**。
- `max_tokens`：设 15 会看到 `finish_reason=length` 和"答案被硬截断"的提示——**这是长度上限，不是模型出错**。

把现象填进 [`参数体验表.md`](参数体验表.md)，四行都要有。

---

## 5. 第 4 步：算这一问花了多少钱（5′）

每次调用终端都会打印 `prompt_tokens / completion_tokens`，日志里也留了一份。

```
费用 = 输入 token ÷ 1,000,000 × 输入单价 + 输出 token ÷ 1,000,000 × 输出单价
```

单价去平台"价格/计费"页查，填进 `.env` 的 `PRICE_INPUT_PER_M` / `PRICE_OUTPUT_PER_M`（元/百万 token），脚本会直接打印 `本次≈¥0.000796`。**讲义故意不写死价格**，因为价格会调整。

讲义作业 3 要 10 次调用平均值，用循环一次跑完（PowerShell）：

```powershell
1..10 | ForEach-Object { python week4_api_bot.py "给中级作文写一句评语" } | Out-Null
```

跑完看 `chat_log.txt` 里 10 段 `cost≈`，加起来除以 10，就是你的一问平均成本。写进实录时回答一句：**用 API 做教学材料，这个成本能不能忽略？**

---

## 6. 第 5 步：故意制造两种失败（7′）

失败也要失败得可读——这是本周最实用的能力。

| 你怎么弄坏它 | 你应该看到 | 说明 |
|---|---|---|
| 把 `.env` 里密钥清空后重跑 | `错误：未设置 DEEPSEEK_API_KEY。…（本次没有发出任何请求，也没有产生费用）` | 退出码 2，先检查再调用 |
| 密钥改成 `sk-wrong` 重跑 | `错误：密钥无效（401 Authentication Fails）…` | 密钥错/失效/带空格 |
| 把 `DEEPSEEK_BASE_URL` 改成不存在的域名 / 拔网线 | `错误：连不上服务器（APIConnectionError）…` | 网络或域名问题 |
| 答案很长时加 `--timeout 1` | `错误：请求超时，请检查网络或调大 timeout。…` | 校园网抖动、答案太长 |

**判读顺序（讲义第13页）**：先看最后一行错误类型 → 是 401/402 就怀疑密钥和余额 → 是超时/连接就怀疑网络 → **最后**才怀疑代码。

> 视频/截图作业时注意：把 `.env` 内容打码，只露前 4 位。

---

## 7. 提交（5′）

```powershell
git status                          # 确认列表里没有 .env；有就先 git rm --cached .env
git add week04_API
git commit -m "week4: 第一次 API 调用，命令行学科问答机器人 + 3 条日志"
git push
```

- GitHub 连不上就换 Gitee，`git` 命令一字不改（讲义第14页）：`git remote set-url origin https://gitee.com/<用户名>/<仓库>.git`，然后 `git push -u origin main`。
- **私有仓库也要把教师账号加成观察者/开发者**，否则验收看不到。
- 换了 Gitee 记得在课程群登记仓库地址。

---

## 8. 常见坑对照

| 症状 | 原因 | 处理 |
|---|---|---|
| `ModuleNotFoundError: No module named 'openai'` | 库没装，或装到了别的 Python | `python -m pip install openai python-dotenv`，装完重开终端 |
| 报 `UnicodeEncodeError: 'ascii' codec can't encode...` | **密钥里还有中文**——`.env` 还是 `.env.example` 的占位符没换 | 把 `.env` 里 `DEEPSEEK_API_KEY=` 后面整段换成真密钥（`sk-` + 字母数字）；保存后直接重跑，**不必**重开终端 |
| 配好了 `.env` 仍报"未设置 DEEPSEEK_API_KEY" | 值为空、文件名叫 `.env.txt`、或不在仓库根目录 | 确认文件名与值；脚本每次运行都会重读 `.env`，改完直接重跑即可 |
| 报 401，但密钥看着没错 | 粘贴带了空格/引号/换行 | 重新粘贴，`=` 后不要留空格，别加引号 |
| 问题只被答了一半 | 中文引号把问题拆开了 | 改用英文 `"`，或者不加引号直接写 |
| 答案突然断在半句 | `max_tokens` 太小，`finish_reason=length` | 调大到 800；这不是模型坏了 |
| 一直超时 | 校园网/代理/答案太长 | `--timeout 120 --max-tokens 300`，换热点再试 |
| 日志找不到 | 日志在**代码包根目录**，不在当前目录 | 看终端最后一行"已追加日志：…"的完整路径 |
| `git status` 里出现 `.env` | `.gitignore` 没生效或已被跟踪 | 确认 `.gitignore` 有 `.env`；已跟踪的先 `git rm --cached .env`，**再换密钥** |

---

## 9. 作业 2「多轮追问」怎么改（先自己写，再对照）

讲义要求"让程序记住上一轮内容"。思路只有一句：**把历史消息一起带上**。

```python
history = []                                   # 会话历史
def chat(q):
    history.append({"role": "user", "content": q})
    r = client.chat.completions.create(model=MODEL, messages=history, ...)
    answer = r.choices[0].message.content
    history.append({"role": "assistant", "content": answer})   # 关键：把回答也存回去
    return answer
```

三个要想清楚的问题（验收会问）：

1. 为什么回答也要追加进 `messages`？只存问题行不行？
2. 聊到第 20 轮，`prompt_tokens` 为什么越来越大？这跟钱什么关系？
3. 历史太长怎么办？（提示：只保留最近 N 轮）

---

## 10. 离场前对照（讲义第16页）

- [ ] `python week4_api_bot.py "问题"` 能打印答案，不报错
- [ ] `chat_log.txt` 里有 3 次学科问题问答
- [ ] 参数体验表已填：`temperature` 两个值 + `max_tokens` 两个值
- [ ] 能说出一次调用的四个要素，并指出换平台改哪两行
- [ ] 密钥安全自查表 5 项全打钩，`git status` 中无 `.env`
- [ ] 已记下作业：读官方文档 / 加多轮追问 / 记录 10 次费用

**红线**：密钥泄露 ＝ 本周成绩直接不及格。共享密钥只用于课堂，课后作废；别把自己的密钥发给同学，也别用别人的额度跑自己的作业。
