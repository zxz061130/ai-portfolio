# W3 生词表 CSV -> 自动生成练习题（含“填空挖空”题型）
# 运行：python vocab_tool.py
#   产物：代码包根目录 练习.txt（造句）、练习_填空.txt（填空挖空）
# 依赖：无第三方库
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import weekpath  # noqa: E402  统一解析 data/ 路径，换目录也不会找不到文件

DATA = weekpath.data_path("生词表.csv")


def load_words(path=DATA):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def filter_by_level(words, level="4"):
    return [w for w in words if str(w["HSK等级"]) == str(level)]


def count_by_pos(words):
    d = {}
    for w in words:
        d[w["词性"]] = d.get(w["词性"], 0) + 1
    return d


def gen_exercises(words, out=None):
    # 产物统一落到代码包根目录：否则“从哪个目录运行”决定了文件落在哪，
    # 与 README 的“任意目录运行”承诺冲突，且散落的产物 .gitignore 拦不住。
    out = out or weekpath.root_path("练习.txt")
    with open(out, "w", encoding="utf-8") as f:
        for w in words:
            f.write("用“%s”造一个句子。（%s）\n" % (w["词汇"], w["词性"]))
    return out


def gen_cloze(words, out=None):
    """填空挖空：能直接从释义里挖掉原词的，出“填空”；
    释义里没有原词的，退化成“看释义写词”，保证每题都有唯一答案。"""
    out = out or weekpath.root_path("练习_填空.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write("一、把括号里的词填到横线上（每空一词）\n\n")
        for i, w in enumerate(words, 1):
            word, meaning, pos = w["词汇"], w["释义"], w["词性"]
            if word in meaning:
                f.write("%d. %s（　　）\n" % (i, meaning.replace(word, "＿＿＿＿", 1)))
            else:
                f.write("%d. 看释义写词：%s（%s，共 %d 字）\n"
                        % (i, meaning, pos, len(word)))
        f.write("\n二、参考答案\n\n")
        for i, w in enumerate(words, 1):
            note = w.get("备注") or ""
            f.write("%d. %s（%s）%s\n" % (i, w["词汇"], w["词性"],
                                        "　[%s]" % note if note else ""))
    return out


if __name__ == "__main__":
    words = load_words()
    lv4 = filter_by_level(words, "4")
    print("总词汇 %d 个，其中 HSK4 词汇 %d 个，词性分布：%s"
          % (len(words), len(lv4), count_by_pos(lv4)))
    print("已生成：%s" % gen_exercises(lv4))
    print("已生成：%s（填空挖空 %d 题）" % (gen_cloze(lv4), len(lv4)))
