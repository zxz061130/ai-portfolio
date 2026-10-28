# W6 · 双引擎封装：Windows 上用 bash 做完这节课

对应讲义《第六次课讲义：双引擎封装》。三个交付物：`llm.py`、回退不崩、`week06_test_log.md`。

**你机器的现状（我刚实测）**：Ollama **0.40.12 已装好**，`qwen2.5:0.5b`（397MB）已拉；`openai`、`requests` 都已装；**`.env` 里的云端密钥可用**（第 1 轮回退时真的拿到了云端答案）——三条路径都能真测了。

**实测数字（RTX 5080 Laptop + Ultra 9 275HX）**：冷启动装载 llama-server 用了 **41 秒**，首次请求可能撞上 60 秒超时；**预热后 0.65s / 0.53s / 0.05s**。所以课前先预热一次，见 §9。

---

## 0. 三分钟跑完课堂任务

```bash
cd /d/ai-portfolio/week06_双引擎

python selftest_offline.py     # 不联网、不用密钥：验证双引擎、双向回退、多轮记忆（51 项）
bash test_paths.sh             # 三条路径实跑，自动生成 week06_test_log.md
```

跑完打开 `week06_test_log.md`，把「是否符合预期」「质量点评」两处补完，然后：

```bash
cd /d/ai-portfolio
git add week06_双引擎 && git commit -m "W6: 双引擎封装" && git push
```

## 1. 讲义五步 ↔ 实际命令

| 讲义步骤 | 你要做的 | 现成的 |
|---|---|---|
| 第1步 建目录、装依赖 | `pip install openai requests` | 你已装好，不用再做 |
| 第2步 写两个引擎 | LocalEngine 搬 W5 的 http 直连；APIEngine 按需建客户端 | `llm.py` 已写好（见 §3 对照） |
| 第3步 写 LLM 入口 | prefer 切换 + 双向 try/except + 打印切换原因 | 同上 |
| 第4步 跑三条路径 | 正常本地 → 关掉 Ollama → `prefer="api"` | `bash test_paths.sh` |
| 第5步 提交 | `git commit` + `push` | 见 §6 |

## 2. 三条路径在 bash 里怎么“制造”出来

```bash
# ① 正常本地
python llm.py "给《愚公移山》出一道 HSK4 阅读题" --prefer local

# ② 本地挂 → 应自动切云端
bash test_paths.sh --stop-ollama        # 真把 Ollama 关掉（讲义原话做法）
bash test_paths.sh                      # 或者：把 LOCAL_HOST 指向空端口，等效但不打断服务

# ③ prefer="api"（云端优先，挂了回本地）
python llm.py "同一个问题" --prefer api
```

**关于 `--stop-ollama`**：脚本用的是 `taskkill //F //IM "ollama app.exe"`（Git Bash 里要写**双斜杠**，单斜杠会被 MSYS 当路径转义）。跑完它会打印重启命令；重启后 `curl -sS --noproxy '*' http://127.0.0.1:11434/api/version` 应返回版本号。

**为什么默认用“空端口”而不是真关**：真关会打断你正在用的服务，而把 `LOCAL_HOST` 指向 `127.0.0.1:11499` 得到的错误完全一样（都是 `ConnectionError`），日志里写清楚用的哪种做法即可。想要讲义原版证据就加 `--stop-ollama`。

## 3. `llm.py` 与讲义的对照（改了什么、为什么）

| 讲义片段 | 我的实现 | 差异与理由 |
|---|---|---|
| 片段1 LocalEngine | `LocalEngine.ask` → `POST /api/chat`，`options.num_predict=max_tokens`，`timeout` 默认 60 | 多两处：`127.0.0.1` 代替 `localhost`（Windows 上 `localhost` 可能解析到 IPv6 `::1`，Ollama 只听 IPv4）；`session.trust_env=False`（W5 实测：系统代理会把本机请求也劫走） |
| 片段2 APIEngine | `_ensure_client()` 懒创建，密钥为空/含中文都给中文提示 | 沿用 W4 的教训：密钥若还是 `.env.example` 的中文占位符，SDK 会抛 `UnicodeEncodeError`，看不出真正原因 |
| 片段3 LLM | `ask(prompt, prefer)` 双向回退，`print("[首选引擎失败，自动切换] …")`；两边都挂抛 `LLMError` 并带两侧原因 | 不返回空字符串；`LLM.last` 记下本次真实走的引擎/耗时/回退原因，测试脚本靠它填表 |

读代码先看这三处：`LocalEngine.ask`、`APIEngine._ensure_client`、`LLM.ask` 的 `try/except`。

## 4. 测试记录怎么填（讲义第六节那张表）

`bash test_paths.sh` 自动生成 `week06_test_log.md`，含六列：

| # | 测试条件 | 实际走的引擎 | 耗时／回退 | 答案摘录 | 是否符合预期／怎么改的 |
|---|---|---|---|---|---|

- 前五列机器填，「是否符合预期」**你填**；
- 第二段「回退日志原文」是评分关键（讲义原话：别只写“成功了”），脚本会把 `[首选引擎失败，自动切换] …` 原样贴进去；
- 第三段三个问题是**质量点评**，必须自己写，优秀档就靠它。

没配云端密钥时，第②组会标「未测：缺云端密钥」——这是诚实标注，不是失败。填好 `.env` 重跑即可。

## 5. Windows + bash 的坑（这节课会遇到的）

| 现象 | 原因 | 处理 |
|---|---|---|
| 本地一直转圈 | 没设 timeout / 服务没起 | 代码已设 60s；`curl 127.0.0.1:11434/api/version` 验证 |
| `connection refused` 但托盘有羊驼 | 端口不对或 IPv6 | 用 `127.0.0.1`，别用 `localhost`；`ollama ps` 看服务 |
| curl 通、Python 不通 | 系统代理劫持本机请求 | `trust_env=False`（已加）；或 `export NO_PROXY=localhost,127.0.0.1` |
| 终端中文乱码 | Python 在 Windows 默认 GBK 输出 | `export PYTHONUTF8=1`（脚本已设） |
| `bash: $'\r': command not found` | 文件被存成 CRLF | 仓库 `.gitattributes` 已固定 LF |
| `taskkill` 报找不到参数 | Git Bash 把 `/F` 当路径 | 写 `//F //IM` |
| 首次 `ollama run` 时防火墙弹窗 | Windows 防火墙询问 | 允许“专用网络”即可，不影响本机调用 |

## 6. 提交

```bash
cd /d/ai-portfolio
git status                      # 确认没有 .env
git add week06_双引擎
git commit -m "W6: 双引擎封装（LocalEngine + APIEngine + 双向回退）"
git push
```

## 7. 验收对照

- **达标**：`llm.py` 有 LocalEngine / APIEngine / LLM，两个引擎都能调，异常有提示；本地失败能自动切云端且不崩溃 → `python selftest_offline.py` 全 PASS 即满足
- **良好**：prefer 可切换、回退双向、测试记录 ≥3 组含回退日志原文 → `bash test_paths.sh` 产出
- **优秀**：能说清“隐私任务走本地、复杂任务走云端”的判断依据 → 写在 `week06_test_log.md` 第三段

## 8. 课后作业（讲义第九节）

1. `llm.py` 增强一项：多轮对话 / 失败重试（最多 2 次再回退）/ 调用耗时与费用估算打印——三选一，注释里写理由 → **你选了多轮，已实现，见 §9**；
2. 边界测试扩到 ≥5 组（补：云端不可用时 `prefer="api"`、`max_tokens` 调小观察截断），写 200 字反思；
3. 预习 RAG：准备一段学科文本，想清楚“模型再强也不知道 HSK4 的具体数字怎么办”。

---

## 9. 作业 1 已实现：多轮对话（`--chat`）

### 怎么用

```bash
cd /d/ai-portfolio/week06_双引擎
python llm.py --chat --prefer local
你> 记住：我的班级有 32 个学生
你> 我们班多少人？只回答数字
你> /clear       # 开新话题，清空记忆
你> /bye         # 退出
```

（也可以只用代码：`llm = LLM(); llm.chat("…"); llm.chat("…"); llm.clear()`）

### 机制（看 `llm.py` 里 `LLM.chat`）

| 细节 | 实现 |
|---|---|
| 记忆 | `history` 里存 `{"role": "user"/"assistant", "content": …}`，每轮把整段历史发给引擎 |
| 裁剪 | `keep_turns=8`（可 `--keep-turns` 改），只发最近 8 轮 → `history[-2*N:]`；不裁的话第 10 轮 prompt 会带着前 9 轮，云端按输入 token 计费，越聊越贵 |
| 失败 | 两边都挂时抛 `LLMError`，并把刚加的那条 user 消息撤回，不留半截历史 |
| 单轮不受影响 | `ask()` 不带历史、也不写历史，W4/W5 的用法照旧 |

### 实测（你这台机器，2026-10-28）

| 场景 | 结果 |
|---|---|
| 冷启动首次请求 | 撞上 60s 超时 → **自动回退云端并成功**（`[引擎] api ｜ 64.15s ｜ 回退: 是 ｜ 第 1 轮`） |
| 预热后单轮 | `[引擎] local ｜ 0.65s` |
| 预热后多轮第 1、2 轮 | `0.53s` / `0.05s`，第 2 轮正确答出 **32** → 历史真的传进去了 |
| 本地 0.5b 的质量 | 第 1 轮回答“抱歉，我没有理解你的问题”——**这就是讲义说的“小模型会答偏”**，对比表里正好用得上 |

### 课前预热（避免第一次撞超时）

```bash
ollama run qwen2.5:0.5b "你好"        # 一条就够，把模型装进显存
```

本机冷启动装载 llama-server 实测 **41 秒**，所以：

- 课前预热一次，课堂演示就不会卡；
- 或者干脆把超时放宽：在 `.env` 里加 `LOCAL_TIMEOUT=180`；
- 副作用提醒：预热后模型会常驻，`ollama ps` 能看到占用（0.5b 约 460 MiB 显存）。

---

## 10. 作业 2：0.5b 与 4b 的账，已经替你算好（数据要你自己判）

`qwen3:4b`（2.5 GB）已经拉好，`python bench_models.py` 会重跑一遍并生成
`模型对比_0.5b_vs_4b.md`。本机实测结果：

| 模型 | 磁盘 | 首次装载 | 首答端到端 | 热调用平均 | 生成速度 | 平均输出 token | 显存 |
|---|---|---|---|---|---|---|---|
| qwen2.5:0.5b | 379 MB | 3.4s | 3.9s | **1.6s** | **192 tok/s** | 210 | **461 MB** |
| qwen3:4b | 2382 MB | 4.4s | 46.4s | 29.5s | 59 tok/s | 1938 | 3033 MB |

**客观倍数**：磁盘 6.3×、显存 6.6×、生成速度 0.31×、热调用耗时 **18.6×**、输出 token 9.2×。

质量上的差别（`模型对比_0.5b_vs_4b.md` 第二节有原文）：

- **0.5b 会一本正经地胡说**：问「把字句」，它答成“由一个或多个动词和一个或多个名词构成，但没有主语和谓语”；
  问「量化」，它答成“通过统计学和数据挖掘对数据进行分析”，跟模型压缩毫无关系；出题时还会反问你要题目。
- **4b 明显懂行**：三段式评语给出了“时态混用导致事件顺序模糊”这种具体问题；「量化」用“把分数约分”“给模型瘦身”
  两个比喻讲到中学老师能懂（`模型对比_0.5b_vs_4b.md` 第 4、5 题原文）。

**但 4b 有个坑**：它会先自言自语上千 token 再给答案，2400 的额度下 5 题里有 **2 题没写完**。
`llm.py` 已经处理了两件事：自动把 qwen3 的 `num_predict` 抬到 1800、把 `</think>` 之前的思考内容剥掉；
想看到完整答案，把 `bench_models.py` 顶部的 `NUM_PREDICT` 改成 3600 再跑一次。

**你现在要写的是判断，不是数字**（`模型对比_0.5b_vs_4b.md` 第三节）：

1. 质量差多少？抄一句只有 4b 答对、0.5b 答偏的原话；
2. 代价是什么？多占多少显存、多等多少秒；
3. 结论：什么任务 0.5b 就够（提示：格式固定、可人工校验、批量生成），什么任务值得上 4b。

参考口径（讲义第五节那张表）：批改作文/成绩评语 → 本地（隐私）；批量练习 → 本地（省钱）；
复杂教案/多步推理 → 云端（质量）；断网课堂演示 → 本地（可用性）。4b 正处在“比 0.5b 懂行、但仍不如云端”的位置。
