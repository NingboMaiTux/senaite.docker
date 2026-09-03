# -*- coding: utf-8 -*-
"""将 maitux.setupmenu 的 .po 编译为 .mo（gettext 二进制格式）

用法（Python 2/3 均可）：:

    python tools/compile_mo.py

会扫描 locales/<lang>/LC_MESSAGES/*.po 并生成同名 .mo。
不依赖 gettext 工具链，仅用标准库 struct。
"""
import os
import struct

HERE = os.path.dirname(os.path.abspath(__file__))
LOCALES = os.path.abspath(os.path.join(HERE, "..", "src", "maitux",
                                       "setupmenu", "locales"))


def parse_po(path):
    """解析 .po，返回 [(msgid, msgstr), ...]（已解码为 unicode）"""
    with open(path, "rb") as f:
        data = f.read()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin-1")

    entries = []
    cur_id = None
    cur_str = ""
    mode = None  # 'id' | 'str'
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("msgid_plural"):
            continue
        if line.startswith("msgid"):
            if cur_id is not None:
                entries.append((cur_id, cur_str))
            cur_id = _parse_string(line[len("msgid"):])
            cur_str = ""
            mode = "id"
        elif line.startswith("msgstr"):
            cur_str = _parse_string(line[len("msgstr"):])
            mode = "str"
        elif line.startswith('"'):
            val = _parse_string(line)
            if mode == "id":
                cur_id += val
            elif mode == "str":
                cur_str += val
    if cur_id is not None:
        entries.append((cur_id, cur_str))
    return entries


def _parse_string(s):
    """解析 ' "text"' -> text（处理常见转义）"""
    s = s.strip()
    if not s.startswith('"'):
        return ""
    body = s[1:-1]
    out = []
    i = 0
    mapping = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"'}
    while i < len(body):
        c = body[i]
        if c == "\\" and i + 1 < len(body):
            nxt = body[i + 1]
            if nxt in mapping:
                out.append(mapping[nxt])
                i += 2
                continue
            if nxt in ("x", "0"):
                j = i + 2
                if nxt == "x":
                    while j < len(body) and body[j] in "0123456789abcdefABCDEF" \
                            and j < i + 4:
                        j += 1
                    out.append(chr(int(body[i + 2:j], 16)))
                else:
                    while j < len(body) and body[j] in "01234567" and j < i + 4:
                        j += 1
                    out.append(chr(int(body[i + 2:j], 8)))
                i = j
                continue
            out.append(nxt)
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def compile_mo(entries, outpath):
    """把条目写成 gettext .mo 文件"""
    items = [(mid.encode("utf-8"), mstr.encode("utf-8"))
             for mid, mstr in entries]
    # gettext 约定：按 msgid 字节序排序（空 msgid 表头排最前）
    items.sort(key=lambda pair: pair[0])
    n = len(items)

    key_table_off = 28
    val_table_off = key_table_off + 8 * n

    key_entries = []
    val_entries = []
    key_data = []
    val_data = []
    pos = val_table_off + 8 * n
    for key, _ in items:
        key_entries.append((len(key), pos))
        key_data.append(key)
        pos += len(key)
    for _, val in items:
        val_entries.append((len(val), pos))
        val_data.append(val)
        pos += len(val)

    with open(outpath, "wb") as f:
        f.write(struct.pack("<I", 0x950412de))  # magic
        f.write(struct.pack("<I", 0))           # version
        f.write(struct.pack("<I", n))           # count
        f.write(struct.pack("<I", key_table_off))
        f.write(struct.pack("<I", val_table_off))
        f.write(struct.pack("<I", 0))           # hash size
        f.write(struct.pack("<I", 0))           # hash offset
        for length, offset in key_entries:
            f.write(struct.pack("<II", length, offset))
        for length, offset in val_entries:
            f.write(struct.pack("<II", length, offset))
        for data in key_data:
            f.write(data)
        for data in val_data:
            f.write(data)
        # GNU gettext 约定：字符串以 NUL 结尾。
        # Python 2.7 的 gettext 用严格 `tend < buflen` 校验，
        # 末尾补一个 NUL 保证最后一个条目不会恰好落在文件末尾。
        f.write(b"\x00")


def main():
    compiled = 0
    for lang in os.listdir(LOCALES):
        messages = os.path.join(LOCALES, lang, "LC_MESSAGES")
        if not os.path.isdir(messages):
            continue
        for name in os.listdir(messages):
            if not name.endswith(".po"):
                continue
            po = os.path.join(messages, name)
            mo = po[:-3] + ".mo"
            entries = parse_po(po)
            compile_mo(entries, mo)
            compiled += 1
            print("compiled %s -> %s (%d entries)" % (po, mo, len(entries)))
    print("done: %d .mo files" % compiled)


if __name__ == "__main__":
    main()
