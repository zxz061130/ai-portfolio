#!/usr/bin/env bash
# 第5周 · 一句话问答（走 /api/chat，Git Bash 下比 ollama run 稳，且能直接看速度）
# 用法：bash bin/ask.sh "给《愚公移山》出一道 HSK4 阅读题"
#       bash bin/ask.sh                              # 回车后按提示输入
#       MODEL=qwen3:4b bash bin/ask.sh "解释把字句的构成条件"
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE="http://${OLLAMA_HOST:-127.0.0.1:11434}"
MODEL="${MODEL:-qwen2.5:0.5b}"
TEMP="${TEMP_LLM:-0.7}"
TIMEOUT="${TIMEOUT_LLM:-300}"

Q="${*:-}"
if [ -z "${Q//[[:space:]]/}" ]; then
  printf '问题> '
  IFS= read -r Q
fi
if [ -z "${Q//[[:space:]]/}" ]; then
  echo '用法: bash bin/ask.sh "你的问题"'
  exit 2
fi

# 纯 bash 转义成 JSON 字符串（不依赖 jq / python；中文按 UTF-8 原样传）
escape() {
  local s=$1
  s=${s//\\/\\\\}
  s=${s//\"/\\\"}
  s=${s//$'\r'/}
  s=${s//$'\n'/\\n}
  s=${s//$'\t'/\\t}
  printf '%s' "$s"
}

# Windows 坑：Git Bash 若 locale 不是 UTF-8，中文参数会以 GBK 字节进来，
# 而 Ollama 的 JSON 只认 UTF-8（否则 400 invalid character）。这里做一次自适应转换。
to_utf8() {
  local s=$1
  if printf '%s' "$s" | iconv -f UTF-8 -t UTF-8 >/dev/null 2>&1; then
    printf '%s' "$s"
  elif command -v iconv >/dev/null 2>&1 \
       && printf '%s' "$s" | iconv -f GBK -t UTF-8 >/dev/null 2>&1; then
    printf '%s' "$s" | iconv -f GBK -t UTF-8
  else
    printf '%s' "$s"
  fi
}

Q="$(to_utf8 "$Q")"

payload="$(printf '{"model":"%s","messages":[{"role":"user","content":"%s"}],"stream":false,"options":{"temperature":%s}}' \
  "$MODEL" "$(escape "$Q")" "$TEMP")"

tmp="$(mktemp)" || exit 1
req="$(mktemp)" || exit 1
trap 'rm -f "$tmp" "$req"' EXIT

# Windows 坑：JSON 一定要写进文件再用 --data-binary @文件 发送。
# 直接 -d "……中文……" 时，Windows 原生 curl.exe 会把命令行参数按 GBK 解释，
# 服务端只认 UTF-8 → 400 invalid character。（这条是在教师机上实测踩到的。）
printf '%s' "$payload" > "$req"

if ! curl -sS --noproxy '*' --max-time "$TIMEOUT" \
      -H 'Content-Type: application/json' \
      -X POST "$BASE/api/chat" --data-binary "@$req" -o "$tmp" 2>/dev/null; then
  cat <<EOF
[FAIL] 请求失败：连不上 $BASE
       1) 任务栏有羊驼图标吗？没有 → 另开终端跑 ollama serve
       2) 跑一下体检：bash bin/check_env.sh
       3) 换过端口？export OLLAMA_HOST=127.0.0.1:11434
EOF
  exit 1
fi

PYTHONUTF8=1 python "$DIR/jsonpick.py" "$tmp" --mode content
rc=$?
if [ "$rc" -eq 2 ]; then
  echo '[提示] 上面的 [ERROR] 多半是模型没拉：bash bin/pull_model.sh '"$MODEL"
  exit 1
fi

PYTHONUTF8=1 python "$DIR/jsonpick.py" "$tmp" --mode metrics
