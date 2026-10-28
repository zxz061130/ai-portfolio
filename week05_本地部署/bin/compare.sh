#!/usr/bin/env bash
# 第5周 · 对比实验：同一组学科问题，本地跑一遍（云端可选），直接生成 markdown 表
#
# 用法：
#   bash bin/compare.sh                                  # 用同目录 questions.txt，只跑本地
#   bash bin/compare.sh questions.txt 5                  # 指定问题文件、最多跑 5 题
#   CLOUD_BOT=../week04_API/week4_api_bot.py bash bin/compare.sh   # 顺带跑云端（要 .env 里的密钥）
#
# 产出：当前目录下 comparison_local.md —— 填完"质量""该用哪个"两列，就能贴进 ollama_notes.md
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$DIR/.." && pwd)"
BASE="http://${OLLAMA_HOST:-127.0.0.1:11434}"
MODEL="${MODEL:-qwen2.5:0.5b}"
TEMP="${TEMP_LLM:-0.7}"
TIMEOUT="${TIMEOUT_LLM:-300}"
QFILE="${1:-$ROOT/questions.txt}"
LIMIT="${2:-0}"
OUT="${OUT:-comparison_local.md}"
CLOUD_BOT="${CLOUD_BOT:-}"

[ -f "$QFILE" ] || { echo "[FAIL] 找不到问题文件：$QFILE"; exit 1; }
command -v curl >/dev/null 2>&1 || { echo '[FAIL] 没有 curl'; exit 1; }

escape() {
  local s=$1
  s=${s//\\/\\\\}; s=${s//\"/\\\"}
  s=${s//$'\r'/}; s=${s//$'\n'/\\n}; s=${s//$'\t'/\\t}
  printf '%s' "$s"
}

# Windows：Git Bash 的 locale 不是 UTF-8 时，中文参数可能是 GBK 字节，
# 而 Ollama 只收 UTF-8 JSON → 自适应转一次（questions.txt 是 UTF-8，会原样通过）。
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

# 本地一问，stdout 输出 TSV：摘要 <TAB> token <TAB> tok/s <TAB> 装载 <TAB> 端到端
ask_local() {
  local q payload tmp req row
  q="$(to_utf8 "$1")"
  payload="$(printf '{"model":"%s","messages":[{"role":"user","content":"%s"}],"stream":false,"options":{"temperature":%s}}' \
    "$MODEL" "$(escape "$q")" "$TEMP")"
  tmp="$(mktemp)" || return 1
  req="$(mktemp)" || { rm -f "$tmp"; return 1; }
  printf '%s' "$payload" > "$req"        # 必须走文件：Windows curl 的 -d 会按 GBK 传中文
  if ! curl -sS --noproxy '*' --max-time "$TIMEOUT" -H 'Content-Type: application/json' \
        -X POST "$BASE/api/chat" --data-binary "@$req" -o "$tmp" 2>/dev/null; then
    rm -f "$tmp" "$req"; return 1
  fi
  row="$(PYTHONUTF8=1 python "$DIR/jsonpick.py" "$tmp" --mode row --width 48 2>/dev/null)"
  local rc=$?
  rm -f "$tmp" "$req"
  [ "$rc" -eq 0 ] && [ -n "$row" ] && printf '%s' "$row"
  return "$rc"
}

# 云端一问（调第4周的机器人），只取答案前 48 字
ask_cloud() {
  local q=$1
  python "$CLOUD_BOT" "$q" 2>/dev/null \
    | awk '/^-{10,}$/{exit} {print}' \
    | tr -d '\r' | tr '\n' ' ' \
    | cut -c1-140
}

{
  printf '# 本地 vs 云端：对比记录（本地侧自动采集）\n\n'
  printf '生成时间：%s　模型：%s　服务：%s　temperature：%s\n\n' \
    "$(date '+%Y-%m-%d %H:%M:%S')" "$MODEL" "$BASE" "$TEMP"
  printf '| # | 学科问题 | 本地答案摘要 | 本地 tok/s | 本地 装载/端到端(s) | 云端答案摘要 | 本地质量 | 云端质量 | 该用哪个 |\n'
  printf '|---|---|---|---|---|---|---|---|---|\n'
} > "$OUT"

echo "== 本地模型：$MODEL（$BASE）=="
echo "== 问题：$QFILE =="
[ -n "$CLOUD_BOT" ] && echo "== 云端：$CLOUD_BOT =="
echo

n=0
while IFS= read -r line; do
  q="$(printf '%s' "$line" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
  case "$q" in ''|'#'*) continue ;; esac
  n=$((n + 1))
  if [ "$LIMIT" -gt 0 ] && [ "$n" -gt "$LIMIT" ]; then break; fi

  printf '[%d] %s\n' "$n" "$q"
  if row="$(ask_local "$q")"; then
    IFS=$'\t' read -r summary count toks load total model <<< "$row"
    printf '   本地：%s tok / %s tok/s / 装载 %ss / 端到端 %ss\n' "$count" "$toks" "$load" "$total"
  else
    summary='（失败：服务未启动或模型未拉取）'; count='-'; toks='-'; load='-'; total='-'
    printf '   本地：失败（先跑 bash bin/check_env.sh）\n'
  fi

  cloud='（未跑）'
  if [ -n "$CLOUD_BOT" ]; then
    cloud="$(ask_cloud "$q")"
    [ -n "${cloud// /}" ] || cloud='（云端失败：查密钥/网络）'
    printf '   云端：%s\n' "$cloud"
  fi

  # markdown 表格里不能出现裸竖线
  summary="${summary//|/／}"; cloud="${cloud//|/／}"; qmd="${q//|/／}"
  printf '| %d | %s | %s | %s | %s / %s | %s | ☐ | ☐ | ☐ |\n' \
    "$n" "$qmd" "$summary" "$toks" "$load" "$total" "$cloud" >> "$OUT"
  echo
done < "$QFILE"

echo "== 已生成：$OUT =="
cat <<EOF

下一步（这张表就是 ollama_notes.md 第 4 节的主体）：
  1) 打开 $OUT，把「本地质量 / 云端质量」按 ✓（可用）△（要改）✕（跑偏）打上；
  2) 「该用哪个」写本地或云端，并补一句为什么；
  3) 整个表粘进 ollama_notes.md，删掉这行说明。
EOF
