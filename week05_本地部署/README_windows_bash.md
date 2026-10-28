# 第5周 · Windows 上用 bash 做本地部署

**一句话结论**：Ollama 在 Windows 是**原生 exe**，bash 只是你的命令行外壳。
你不需要 WSL，也不需要重装系统——用**已经装好的 Git Bash**（`D:\ai-portfolio\Git\bin\bash.exe`）就能把讲义第6页那四条命令原样跑起来。真正要小心的是 **Windows 的编码与路径**，不是 bash 本身。

---

## 0. 先看清你这台机器的现状（我已实测）

| 项目 | 你机器上的情况 | 意味着什么 |
|---|---|---|
| Git Bash | ✅ `D:\ai-portfolio\Git\bin\bash.exe`（bash 5.3.15，MINGW64） | 有 bash，可以直接用 |
| Ollama | ❌ 没装（PATH 里没有 `ollama`，11434 端口没监听） | 先装，装完**重开终端** |
| WSL | ❌ 未安装（`wsl -l` 报未安装 Linux 子系统） | 不必装，走 Git Bash 更省事 |
| curl | ✅ `C:\Windows\System32\curl.exe` | 能用，但中文有坑（见 §5） |
| python | ✅ `D:\Python311\python.exe`，requests 2.32.5 已装 | 第12页直连能直接跑 |
| jq | ❌ 没有 | 用 `python -m json.tool` 代替 |
| 作品集仓库 | `D:\ai-portfolio`，分支 `master`，远端 GitHub（SSH） | 交付物放这里（见 §9 的一个隐患） |

---

## 1. 打开 bash 的四种方式

1. **开始菜单**搜 `Git Bash` 打开窗口（最好用这个）；
2. 双击 `D:\ai-portfolio\Git\git-bash.exe`；
3. **Windows Terminal** → 下拉箭头 → 设置 → 添加配置文件 → 命令填 `D:\ai-portfolio\Git\bin\bash.exe -i -l`；
4. **VS Code** → 终端面板 → 选择默认配置文件 → Git Bash。

打开后先确认：

```bash
echo "$BASH_VERSION"        # 期望 5.x
uname -s                    # 期望 MINGW64_NT-10.0-xxxx
```

> Git Bash 的 `~`（家目录）是 `C:\Users\ZXZ`，不是仓库目录。仓库要自己 `cd` 进去。

---

## 2. 路径怎么写（Windows ↔ bash 对照）

| Windows 写法 | Git Bash 写法 |
|---|---|
| `D:\ai-portfolio` | `/d/ai-portfolio` |
| `C:\Users\ZXZ\Documents` | `/c/Users/ZXZ/Documents` |
| `D:\ai-portfolio\week05_本地部署` | `/d/ai-portfolio/week05_本地部署` |

```bash
cd /d/ai-portfolio            # 反斜杠在这里会变转义符，一律用正斜杠
pwd                           # /d/ai-portfolio
ls                            # 列目录
explorer.exe .                # 用资源管理器打开当前目录
start .                       # 同上（另一个写法）
```

**别做的事**：`cd D:\ai-portfolio`（bash 会把 `\a` 当转义，路径就废了）；`cd /mnt/d/...`（那是 WSL 的写法，Git Bash 不认）。

---

## 3. 装 Ollama（唯一必须点鼠标的一步）

```bash
# 装完在 bash 里验证（一定要新开窗口，PATH 才会刷新）
ollama --version
```

1. 双击 `OllamaSetup.exe`（老师分发的离线包就是它），一路"下一步"，**不要改到中文路径下**；
2. 装完看**任务栏托盘**：出现羊驼图标 = 后台服务已启动（默认就监听 `127.0.0.1:11434`）；
3. **关掉所有 Git Bash 窗口再重开**——不重开就会出现"装了但 bash 找不到命令"；
4. 验证：`ollama --version`。

**没有离线包、但有网**的备选：

```powershell
winget install --id Ollama.Ollama -e
```

**装完还是 command not found？** 临时救急（只对当前窗口有效）：

```bash
export PATH="$LOCALAPPDATA/Programs/Ollama:$PATH"
ollama --version
```

---

## 4. 四条命令，在 bash 里原样能跑

```bash
ollama pull qwen2.5:0.5b        # 拉模型（约 397MB）；断网用离线包导入
ollama list                     # 已装模型 + 体积
ollama ps                       # 当前谁在跑、占多少内存
ollama run qwen2.5:0.5b         # 命令行直接对话，输入 /bye 退出
```

`ollama run` 在 Git Bash 里可能遇到两个现象，都有解：

| 现象 | 原因 | 解决 |
|---|---|---|
| 打字没回显、按键怪 | mintty 不是真终端 | `winpty ollama run qwen2.5:0.5b`（或用我的 `bash bin/run.sh`） |
| 中文显示成乱码/方块 | 终端 locale 不是 UTF-8 | `export LANG=zh_CN.UTF-8`；或改用 Windows Terminal / VS Code 终端 |

服务起不来时的手工验证（curl 一定用 `127.0.0.1`，别用 `localhost`）：

```bash
curl -sS --noproxy '*' http://127.0.0.1:11434/api/tags | python -m json.tool
```

---

## 5. curl 在 Windows 上的四个雷（都实测过）

1. **PowerShell 里 `curl` 不是 curl** —— 它是 `Invoke-WebRequest` 的别名，参数全不一样。要用就写 `curl.exe`。在 Git Bash 里没这个问题。
2. **`localhost` 可能解析到 IPv6 `::1`**，而 Ollama 只听 IPv4 → 一律写 `127.0.0.1`。
3. **中文 JSON 绝不能 `-d "……"`**：Windows 原生 `curl.exe` 会把命令行参数按 **GBK** 解释，服务端只认 UTF-8，直接 400 `invalid character`。正确做法是先写文件再发：

   ```bash
   printf '%s' '{"model":"qwen2.5:0.5b","messages":[{"role":"user","content":"给《愚公移山》出一道题"}],"stream":false}' > req.json
   curl -sS --noproxy '*' -H 'Content-Type: application/json' \
        --data-binary @req.json http://127.0.0.1:11434/api/chat -o resp.json
   python -m json.tool resp.json | head -20
   ```

   （本包的 `bin/ask.sh` 已经这么做了，所以它能正常跑；如果你手抄别处的 `curl -d`，中文一定翻车。）
4. **代理**：机房/校园网设了 `http_proxy` 时，curl 会把本机请求也送去代理 → 连接被拒。加 `--noproxy '*'`（本包脚本已加），或 `export NO_PROXY=localhost,127.0.0.1`。

---

## 6. 环境变量：`export` / `setx` / `.bashrc` 各管什么

| 目的 | 命令 | 生效范围 |
|---|---|---|
| 当前 bash 窗口临时用 | `export OLLAMA_HOST=127.0.0.1:11434` | 本窗口 + 本窗口启动的子进程 |
| 永久（bash 每次启动生效） | 把这行写进 `~/.bashrc`（即 `C:\Users\ZXZ\.bashrc`） | 以后所有 Git Bash 窗口 |
| 改**系统服务**的行为 | PowerShell：`setx OLLAMA_HOST "127.0.0.1:11434"`，再从托盘**退出并重启** Ollama | 全局（但托盘里那个进程不重启就不生效） |
| 模型换个盘（省 C 盘） | `setx OLLAMA_MODELS "D:\ollama-models"`，重启 Ollama | 全局 |

**最常见的误会**：以为 `export` 能改变托盘里那个 Ollama 服务——不能。托盘进程是开机自启的独立进程，它只认系统环境变量。

---

## 7. CRLF 地雷：`bash: $'\r': command not found`

Windows 编辑器存成 CRLF 后，bash 会在行尾多读一个 `\r`，于是报这种看不懂的错。

```bash
sed -i 's/\r$//' bin/ask.sh            # 单个文件
git config --global core.autocrlf false  # 让 Git 别再自动转（推荐）
```
VS Code 右下角把 `CRLF` 点成 `LF` 也行。**本包所有脚本已确认是 LF**，你可以直接跑。

---

## 8. 用本包的脚本（三条命令走完课堂任务）

```bash
cd /c/Users/ZXZ/Documents/deepseek-harness/default-workspace/week05_本地部署

bash bin/check_env.sh           # 1) 体检：bash/ollama/服务/模型/代理/python，逐项 OK/FAIL
bash bin/pull_model.sh          # 2) 拉 qwen2.5:0.5b（带离线包与内存不足的处理提示）
bash bin/ask.sh "给《愚公移山》出一道 HSK4 阅读题"   # 3) 问一句，打印答案 + tok/s + 装载耗时
bash bin/compare.sh             # 4) 5 个学科问题跑一遍，自动生成对比表（交付物主体）
python local_chat.py "解释把字句的构成条件"          # 5) 讲义第12页的 Python 直连
```

各脚本干什么：

| 文件 | 作用 | 对应讲义 |
|---|---|---|
| `bin/check_env.sh` | 六项体检，直接告诉你卡在哪 | 第13页排错 |
| `bin/pull_model.sh` | 拉模型 + 已装检测 + 离线包/换盘指引 | 第6页第2步 |
| `bin/run.sh` | 交互对话（自动 `winpty`、UTF-8） | 第6页第3步 |
| `bin/ask.sh` | 一问一答，输出 tok/s、装载/端到端耗时 | 第10页速度维度 |
| `bin/compare.sh` | 批量跑问题，生成 markdown 对比表 | 第10页记录表 |
| `bin/jsonpick.py` | 解析响应（代替没装的 jq） | — |
| `local_chat.py` | requests 直连，`trust_env=False` | 第12页 |
| `ollama_notes.md` | 交付物模板，按空填 | 第3、15页 |

> 说明：因为你这台机器还没装 Ollama，我在**本地起了一个假的 Ollama 服务**把脚本全流程跑通验证了（返回固定答案 + 固定 token 数）。
> 所以脚本逻辑、中文编码、表格生成都是验证过的；但**真实的 tok/s 要你装完 Ollama 后自己跑出来**，那才是能写进笔记的数字。

---

## 9. 顺手修一个隐患：你的 Git 被提交进仓库了

`D:\ai-portfolio` 里 **9620 个被 Git 跟踪的文件**全是 `Git/` 目录（就是你现在用的这个 Git 本体），而且仓库**没有 `.gitignore`**。后果：每次 `git add -A` 都会把整个 Git 安装一起提交（慢、仓库巨大），老师点开你的作品集第一眼看到的是 `Git/bin/...`。

修法（**注意：只用 `--cached`，千万别删目录**，那是你的 Git）：

```bash
cd /d/ai-portfolio
printf '.env\n.env.*\n!.env.example\n__pycache__/\nGit/\n' > .gitignore
git rm -r --cached Git
git add .gitignore
git commit -m "chore: 把误提交的 Git/ 移出版本库，补 .gitignore"
git push
```

- `git rm -r --cached Git` 只是让 Git **不再跟踪**，磁盘上的 `Git\` 原样保留，命令照常能用。
- 历史里那 9620 个文件仍然存在，仓库不会立刻变小；要彻底瘦身得用 `git filter-repo`（可选，期末统一做也行）。
- 本条与本周作业无关，但会一直拖慢你每次 push，建议先修。

---

## 10. Python 直连（讲义第12页）与 Git Bash 的编码

```bash
python local_chat.py "给《愚公移山》出一道 HSK4 阅读题"
python local_chat.py --model qwen3:4b --host 127.0.0.1:11434 "解释把字句的构成条件"
```

三个必讲点：

1. **`session.trust_env = False`** —— 校园网配了代理时，requests 会把 `127.0.0.1` 也送进代理，于是"curl 通、Python 不通"。这行就是关掉代理自动探测。
2. **`timeout=120`** —— 首次调用要把模型装进内存（0.5b 约 5 秒，4b 更久），给 30 秒会误判成"服务挂了"。
3. **中文乱码** —— Windows 上 Python 默认按 GBK 输出到管道，mintty 按 UTF-8 解码 → 乱码。两个办法：
   ```bash
   export PYTHONUTF8=1        # 推荐，本窗口内所有 python 都按 UTF-8 输出
   python local_chat.py "……"
   ```
   本包的 `local_chat.py` / `jsonpick.py` 已经在代码里自动纠正这个问题，但你自己写的脚本要知道原因。

---

## 11. 排错对照表

| 现象 | 多半是 | 处理 |
|---|---|---|
| `ollama: command not found` | 装完没重开终端 | 重开 Git Bash；或 `export PATH="$LOCALAPPDATA/Programs/Ollama:$PATH"` |
| `connection refused` / curl 空响应 | 服务没起 / 端口不同 | 托盘羊驼图标？`ollama serve`；`export OLLAMA_HOST=...` |
| `model "xxx" not found` | 模型没拉，或名字打错 | `ollama list` 看确切名字；`ollama pull xxx` |
| 400 `invalid character` | 中文用 `-d` 传成了 GBK | 用 `--data-binary @文件`（§5.3） |
| 401（云端） | 密钥错/失效/带空格 | 重新生成密钥，`.env` 里别加引号 |
| 跑起来极慢、系统卡死 | 模型太大，内存不够 | `ollama ps` 看占用；4b → 0.5b；8GB 别碰 8b |
| 首次调用超时 | 装载时间长 | timeout 给 120–180 秒 |
| 中文全是 `锟斤拷`/乱码 | 编码 | `export LANG=zh_CN.UTF-8`、`export PYTHONUTF8=1` |
| `bash: $'\r': command not found` | CRLF 行尾 | `sed -i 's/\r$//' 文件` |
| `curl: (6) Could not resolve host` | 写了 `localhost` 但解析异常，或代理 | 换 `127.0.0.1`；加 `--noproxy '*'` |

---

## 12. bash ↔ PowerShell 速查（换着用时别懵）

| 动作 | bash | PowerShell |
|---|---|---|
| 切盘/目录 | `cd /d/ai-portfolio` | `cd D:\ai-portfolio` |
| 列目录 | `ls -la` | `dir` / `ls` |
| 看文件 | `cat f.txt` | `Get-Content f.txt` |
| 设环境变量（临时） | `export X=1` | `$env:X=1` |
| 设环境变量（永久） | 写 `~/.bashrc` | `setx X 1` |
| 管道过滤 | `\| grep 关键词` | `\| Select-String 关键词` |
| 下载 | `curl -O URL` | `curl.exe -O URL`（`curl` 是别名！） |
| 看进程 | `ps aux \| grep ollama` | `Get-Process ollama` |
| 后台跑 | `ollama serve &` | `Start-Process ollama serve` |
| 退出码 | `echo $?` | `$LASTEXITCODE` |

---

## 13. 离场验收（讲义第16页）+ 提交

- [ ] `bash bin/run.sh` 能对话不报错；`ollama list` 看得到模型
- [ ] `ollama_notes.md` 写了安装步骤 + 选型理由（按自己内存）
- [ ] 对比表 ≥5 个学科问题，速度/质量/隐私三维都有真实观察
- [ ] 能说清"量化"是什么，并指出"用 MCP 把模型塞进小内存"错在哪
- [ ] 能举例哪些教学数据不该上云
- [ ] 作业：读官方文档 / 换量级对比 / 离线部署复盘

```bash
cd /d/ai-portfolio
git status                       # 确认只有 week05 相关文件 + 没有 .env
git add week05_本地部署 .gitignore
git commit -m "week5: Ollama 本地部署，ollama_notes.md + 对比表"
git push
```
