# -*- coding: utf-8 -*-
"""SENAITE addon 静态检查器（宿主机 Python 3 运行，不进容器也能跑大部分检查）。

判据来源：addons/customers/SENAITE-Addon开发规则.md 的 R1–R14、
gen-custom-addon.sh 的收录规则、CLAUDE.md §5 的语言约束。
每条检查都对应一次真实事故，不做"风格"检查。

用法：
    python lint_addon.py                      # 扫 customers + common 全部
    python lint_addon.py --addon maitux.stock # 只扫一个（跨包冲突检查仍全量加载）
    python lint_addon.py --in-container       # 额外用容器里的 py2 跑 compileall
    python lint_addon.py --json report.json   # 机器可读产物

退出码：有 ERROR 返回 1，否则 0。
"""
from __future__ import print_function

import argparse
import ast
import io
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

def _default_addons_root():
    """找 addons 根：先按自身位置，再退回按当前目录。

    这个文件有两份，内容必须保持一致（改一份要同步另一份）：
      · badshuang/PersonalMemo  的 .claude/skills/senaite-addon-lint/tools/
      · NingboMaiTux/senaite.docker 的 2.7.0-maitux1/addons/customers/

    后者是为了让「规则」和「检查器」待在一起 —— SENAITE-Addon开发规则.md
    的 R1–R14 就靠它机器化，规则在共用库而检查器不在，别人照规则写完跑不了检查。

    所以定位不能写死相对当前目录：单独 clone senaite.docker 的人，
    cwd 和目录层级都跟这边不一样。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    # ① 自身就放在 addons/customers/ 里（senaite.docker 那一份）
    if os.path.basename(here) == "customers" and \
            os.path.isdir(os.path.join(os.path.dirname(here), "customers")):
        return os.path.dirname(here)
    # ② 从自身向上找 <某处>/2.7.0-maitux1/addons
    cur = here
    for _ in range(6):
        cand = os.path.join(cur, "senaite.docker", "2.7.0-maitux1", "addons")
        if os.path.isdir(cand):
            return cand
        cand = os.path.join(cur, "2.7.0-maitux1", "addons")
        if os.path.isdir(cand):
            return cand
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    # ③ 都没有就退回老行为：相对当前目录
    return os.path.join("senaite.docker", "2.7.0-maitux1", "addons")


DEFAULT_ADDONS_ROOT = _default_addons_root()
DEFAULT_CONTAINER = "maituxlimslatest"
# customers 是 bind-mount，common 是构建期 COPY（Dockerfile:64）。
# 两层在容器里都是 /opt/addons/<layer>/<dir_name>，按 layer 取。
CONTAINER_ADDONS_ROOT = "/opt/addons"

# ZCML 里出现这些前缀的权限，说明依赖 senaite.core 的权限注册（R1）
SENAITE_PERM_PREFIXES = ("senaite.core.", "bika.lims.")
PERM_INCLUDE_PKG = "senaite.core.permissions"

CJK = re.compile(u"[一-鿿]")
CODING_LINE = re.compile(r"coding[:=]\s*([-\w.]+)")

# 只有这些 ZCML 标签是"同名即冲突"的组件注册。registerProfile / importStep /
# upgradeStep / depends 的 name 是包内命名，20 个包各写一个 default profile 不是冲突。
CONFLICTING_TAGS = frozenset([
    "adapter", "utility", "page", "pages", "viewlet", "viewletManager",
    "view", "resource", "resourceDirectory", "static", "portlet",
])

# Py3-only 语法的保守探测（宁可漏，不要误报）
PY3_PATTERNS = [
    (re.compile(r"^\s*(from|import)\s+pathlib\b", re.M), "pathlib"),
    (re.compile(r"^\s*def\s+\w+\s*\([^)]*\)\s*->", re.M), "返回值注解"),
    (re.compile(r"\bsuper\(\s*\)"), "无参 super()"),
    (re.compile(r"^\s*\w+\s*:\s*(str|int|bool|float|list|dict)\s*=", re.M),
     "变量注解"),
]

# --- R12：ReferenceWidget / QuerySelectWidget 的 base_query 泄漏 ----------
# senaite.core 的 widget._properties["base_query"] 是类级共享的可变 dict，
# referencewidget.get_query() 拿到它以后 base_query.update(query) 原地改。
# 只要渲染过一次非拷贝的原始 widget，query 里的键就永久污染整个 Zope 进程里
# 所有 ReferenceWidget。显式传 base_query={} 可让该实例用自己的 dict。
#
# 泄漏是否致命，取决于泄漏的键在目标 catalog 里是不是索引、且其他 portal_type
# 是否具备该属性。下面这些键 senaite.core 自己就在漏（63 处），它们要么不过滤
# （排序参数），要么每个内容类型都具备（is_active），所以无害 —— 只报 WARN。
# 除此之外的键（典型：addon 给自己的内容类型建的专属索引）会把别的类型过滤成
# 0 条，报 ERROR。事故实例：INNOCARE.arextension 的 usage_scope 让 Care 站
# 样品登记页所有引用控件搜不出内容。
WIDGET_QUERY_UNIVERSAL_KEYS = frozenset([
    "sort_on", "sort_order", "sort_limit", "sort_order",
    "portal_type", "is_active", "is_received", "review_state",
])


def scan_widget_base_query(src):
    """返回 [(lineno, widget_name, [泄漏的键], 有无非字面量键)]。

    只认「调用名以 Widget 结尾、传了 query= 、没传 base_query=」的构造。
    query 不是字面量 dict 时无法取键，按"未知"处理并归入 ERROR 一侧。
    """
    try:
        tree = ast.parse(src)
    except Exception:
        return []
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None) or ""
        if not name.endswith("Widget"):
            continue
        kwargs = set(k.arg for k in node.keywords if k.arg)
        if "query" not in kwargs or "base_query" in kwargs:
            continue
        keys, opaque = [], False
        for kw in node.keywords:
            if kw.arg != "query":
                continue
            if isinstance(kw.value, ast.Dict):
                for k in kw.value.keys:
                    if isinstance(k, ast.Str):
                        keys.append(k.s)
                    elif isinstance(k, ast.Constant) and isinstance(k.value, str):
                        keys.append(k.value)
                    else:
                        opaque = True
            else:
                opaque = True
        out.append((node.lineno, name, keys, opaque))
    return out


# --- R14：注入外来 UI / 注册外来内容适配器必须 layer 门控 -----------------
# ZCML 一旦进 package-includes 就**全局加载**，跟 profile 装没装无关。所以
# 「只对本 addon 的站点生效」这件事只有两条路：把自己的 browser layer 放进
# 适配签名（ZCML 门控），或在工厂里显式判 layer.providedBy(request)（运行时
# 门控）。两条都不走 = 没装该 addon 的站点也照样吃到这次注册。
#
# 事故实例（maitux.instrument_acquisition）：Worksheets 列表底部「仪器采集」
# 按钮由 IListingViewAdapter 订阅者注入，四个站点全都显示 —— 包括从未装过
# 这个 addon 的站点。同一文件里两个 browser:page 都规规矩矩写了 layer=，
# 唯独 subscriber / adapter 没有，注释还把它当成优点（"不依赖 browser layer"）。
#
# ★ 两种注册的可门控方式不一样，别混：
#   · IListingViewAdapter 的查找签名是 (view, context)，**request 不在里面**
#     → ZCML 里无处插 layer，只能在 before_render() 里判 → 必须运行时门控
#   · workflow 动作 adapter 的签名是 (context, IBrowserRequest)
#     → 把 IBrowserRequest 换成自己的 layer 即可 → 纯 ZCML 可修
#
# 收窄条件（摸底时初版打 17 处、15 处误报，加了这三条后精确命中 2 处）：
#   ① 包必须自己声明过 browser layer —— 没有 layer 的包无从门控，不报
#   ② for= 里出现 layer 算已门控（有 3 处是这么写的）
#   ③ 只认 for= 指向**外来**内容接口的；for="*" 配自有动作名不报（12 处）
FOREIGN_IFACE_PREFIXES = ("senaite.", "bika.lims.", "plone.", "Products.",
                          "zope.app.", "OFS.", "Acquisition.")
# 这些是「任意请求」，出现在 for= 里说明作者没打算用 layer 收窄
GENERIC_REQUEST_IFACES = frozenset([
    "zope.publisher.interfaces.browser.IBrowserRequest",
    "zope.publisher.interfaces.browser.IDefaultBrowserLayer",
    "zope.publisher.interfaces.http.IHTTPRequest",
    "zope.publisher.interfaces.IRequest",
    "IBrowserRequest", "IHTTPRequest", "IRequest",
])
# provides 是这些后缀的订阅者 = 往别人的视图里注入 UI
UI_INJECT_PROVIDES = ("IListingViewAdapter", "ViewAdapter",
                      "IViewletManager", "IListingSearchableTextProvider")


def _iface_is_layer(dotted):
    """接口短名以 Layer 结尾即视为 browser layer。

    本环境 12 个 layer 的基类五花八门（ISenaiteCore / IDefaultBrowserLayer /
    IDefaultPloneLayer / 甚至别的 addon 的 layer），按基类识别认不全，
    只有命名约定是齐的。
    """
    return dotted.rsplit(".", 1)[-1].endswith("Layer")


def collect_browser_layers(code_dir):
    """扫包内 .py，返回自己声明的 layer 接口短名集合。"""
    out = set()
    for dirpath, dirs, files in os.walk(code_dir):
        dirs[:] = [d for d in dirs if not d.endswith("egg-info")]
        for fn in files:
            if not fn.endswith(".py"):
                continue
            try:
                tree = ast.parse(read_text(os.path.join(dirpath, fn)))
            except Exception:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and \
                        node.name.startswith("I") and \
                        node.name.endswith("Layer"):
                    out.add(node.name)
    return out


def _factory_module_path(code_dir, dist_name, factory):
    """factory 点分名 → 模块文件路径（取不到返回 None）。"""
    if not factory or "." not in factory:
        return None
    module = factory.rsplit(".", 1)[0]          # 去掉类名
    if not module.startswith(dist_name + "."):
        return None
    rel = module[len(dist_name) + 1:].replace(".", os.sep)
    for cand in (os.path.join(code_dir, rel + ".py"),
                 os.path.join(code_dir, rel, "__init__.py")):
        if os.path.isfile(cand):
            return cand
    return None


def scan_ui_gating(code_dir, dist_name, layers):
    """返回 [(kind, rel_zcml, tag, name, provides, for_str, detail)]。

    kind: "ui_inject"（A，必现 UI 泄漏）/ "foreign_adapter"（B，可 ZCML 门控）
    """
    if not layers:
        return []
    out = []
    for dirpath, dirs, files in os.walk(code_dir):
        dirs[:] = [d for d in dirs if not d.endswith("egg-info")]
        for fn in sorted(files):
            if not fn.endswith(".zcml"):
                continue
            zpath = os.path.join(dirpath, fn)
            root, err = parse_xml(zpath)
            if err:
                continue                      # 解析失败由 E08 负责
            rel = os.path.relpath(zpath, code_dir)
            for el in iter_elements(root):
                tag = localname(el.tag)
                if tag not in ("subscriber", "adapter"):
                    continue
                # 收窄②：layer 写在 for= 里也算门控
                fors = (el.get("for") or "").split()
                if any(_iface_is_layer(f) for f in fors):
                    continue
                # 收窄③：只认指向外来内容接口的
                foreign = [f for f in fors
                           if f.startswith(FOREIGN_IFACE_PREFIXES)
                           and f not in GENERIC_REQUEST_IFACES]
                if not foreign:
                    continue
                provides = el.get("provides") or ""
                reg_name = el.get("name") or ""
                for_str = " ".join(fors)
                if tag == "subscriber" and provides.endswith(UI_INJECT_PROVIDES):
                    # 无 ZCML 门控通道 → 看工厂里有没有运行时判 layer
                    mod = _factory_module_path(code_dir, dist_name,
                                               el.get("factory") or "")
                    if mod:
                        src = read_text(mod)
                        if any(name in src for name in layers):
                            continue          # 有运行时门控，不报
                    out.append(("ui_inject", rel, tag, reg_name, provides,
                                for_str,
                                os.path.relpath(mod, code_dir) if mod else u""))
                elif any(f in GENERIC_REQUEST_IFACES for f in fors):
                    out.append(("foreign_adapter", rel, tag, reg_name, provides,
                                for_str, foreign[0]))
    return out


LEVEL_ERROR = "ERROR"
LEVEL_WARN = "WARN"
LEVEL_INFO = "INFO"


class Finding(object):
    def __init__(self, level, code, addon, msg, rule="", path=""):
        self.level = level
        self.code = code
        self.addon = addon
        self.msg = msg
        self.rule = rule
        self.path = path

    def as_dict(self):
        return {
            "level": self.level, "code": self.code, "addon": self.addon,
            "rule": self.rule, "path": self.path, "msg": self.msg,
        }


# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------

def read_text(path):
    with io.open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def exact_case_exists(root, relpath):
    """逐级用 listdir 精确匹配，绕开 Windows 大小写不敏感（gen-custom-addon.sh 同款做法）。"""
    cur = root
    for part in relpath.replace("\\", "/").split("/"):
        if not part:
            continue
        try:
            entries = os.listdir(cur)
        except OSError:
            return None
        if part not in entries:
            return None
        cur = os.path.join(cur, part)
    return cur


def read_dist_name(setup_py):
    """按 gen-custom-addon.sh 的口径从 setup.py 取 name=。"""
    txt = read_text(setup_py)
    m = re.search(r"""^\s*name\s*=\s*["']([^"']+)["']""", txt, re.M)
    if m:
        return m.group(1)
    m = re.search(r"""name\s*=\s*["']([^"']+)["']""", txt)
    return m.group(1) if m else None


def code_dir_for(addon_dir, dist_name):
    """按分发名推代码目录，返回 (真实路径 or None, 试过的相对路径列表)。"""
    rel = dist_name.replace(".", "/")
    tried = ["src/" + rel, rel]
    for cand in tried:
        hit = exact_case_exists(addon_dir, cand)
        if hit:
            return hit, tried
    return None, tried


def find_anycase(addon_dir, filename, maxdepth=5):
    """不管大小写对不对，包里到底有没有这个文件。"""
    base_depth = addon_dir.rstrip(os.sep).count(os.sep)
    for dirpath, dirnames, filenames in os.walk(addon_dir):
        if dirpath.count(os.sep) - base_depth > maxdepth:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames
                       if not d.endswith("egg-info") and d != "tests"]
        if filename in filenames:
            return os.path.join(dirpath, filename)
    return None


def scan_string_tokens(src):
    """扫真正的字符串 token（不碰注释、不碰 % 格式串这类假阳性）。

    返回 (含中文的字节串字面量行号, f-string 行号)。三引号跳过：docstring 里的
    中文是噪音。tokenize 失败就整项放弃，宁可漏报。
    """
    import tokenize
    cjk_lines, fstrings = [], []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type != tokenize.STRING:
                continue
            text = tok.string
            prefix = text[:len(text) - len(text.lstrip("uUbBrRfF"))]
            if "f" in prefix.lower():
                fstrings.append(tok.start[0])
                continue
            if "u" in prefix.lower():
                continue
            body = text[len(prefix):]
            if body[:3] in ('"""', "'''"):
                continue
            if CJK.search(body):
                cjk_lines.append(tok.start[0])
    except Exception:
        return [], []
    return cjk_lines, fstrings


def _is_ascii(text):
    try:
        text.encode("ascii")
        return True
    except Exception:
        return False


def localname(tag):
    return tag.split("}")[-1] if "}" in tag else tag


def parse_xml(path):
    """返回 (root, error_msg)。"""
    try:
        return ET.parse(path).getroot(), None
    except ET.ParseError as exc:
        return None, str(exc)
    except Exception as exc:  # 编码等
        return None, repr(exc)


def iter_elements(root):
    yield root
    for child in root.iter():
        if child is not root:
            yield child


# --- E15 辅助：区分「msgid 是中文」和「中文只是 default 兜底」-------------
#
# zope.i18n 里 i18n:translate 有两种写法，性质完全不同：
#
#   <p i18n:translate="">中文</p>          msgid **就是**那段中文 → 违反 R9b
#   <p i18n:translate="some_id">中文</p>   msgid 是 ASCII 的 some_id，
#                                          正文只是 catalog 没命中时的 default
#
# 第二种是**正确用法**（maitux.hazardcategories 就是这么写的，四套 catalog
# 里那条 msgid 齐全、en/zh 译文都有）。E15 第一版不分青红皂白扫整份模板，
# 把它判成 ERROR —— 与 E14 第一版误伤 maitux.reviewerassignment 是同一个毛病。
# 规则宁可窄一点，也不要对着能跑的代码报警。

_TAG_RE = re.compile(r"<(?P<close>/?)(?P<tag>[A-Za-z][\w:.-]*)"
                     r"(?P<attrs>(?:\"[^\"]*\"|'[^']*'|[^>\"'])*)>")
_TRANSLATE_ATTR = re.compile(r"i18n:translate\s*=\s*\"([^\"]*)\"|"
                             r"i18n:translate\s*=\s*'([^']*)'")
# HTML 空元素：不可能有子内容，出现 i18n:translate 也没有正文可挖
_VOID_TAGS = frozenset((
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr"))


def split_i18n_defaults(body):
    """把带**显式 msgid** 的 i18n:translate 元素的正文摘出来。

    返回 (剩余正文, 显式 msgid 列表, 被摘出的 default 文案列表)。
    剩余正文里，显式 msgid 元素的内容已被替换成等长空白，
    因此调用方在其中发现的非 ASCII 才是真的「硬编码不可翻译」。
    """
    out = []
    msgids = []
    defaults = []
    pos = 0
    # 栈里放正在「挖空」的元素标签名；非空即处于 default 区间内
    masking = []
    for m in _TAG_RE.finditer(body):
        text = body[pos:m.start()]
        (defaults if masking else out).append(text)
        pos = m.end()
        tag = m.group("tag")
        attrs = m.group("attrs") or ""
        is_close = bool(m.group("close"))
        self_closing = attrs.rstrip().endswith("/")
        if is_close:
            if masking and masking[-1] == tag:
                masking.pop()
            out.append(m.group(0))
            continue
        out.append(m.group(0))          # 标签本身（含属性）照旧参与检查
        if self_closing or tag.lower() in _VOID_TAGS:
            continue
        if masking:
            masking.append(tag)         # 嵌套：跟着一起挖，靠标签名配平
            continue
        am = _TRANSLATE_ATTR.search(attrs)
        if am:
            msgid = am.group(1) if am.group(1) is not None else am.group(2)
            if msgid:                   # 非空 = 显式 msgid
                msgids.append(msgid)
                masking.append(tag)
    (defaults if masking else out).append(body[pos:])
    return u"".join(out), msgids, defaults


# --------------------------------------------------------------------------
# 单包检查
# --------------------------------------------------------------------------

class Addon(object):
    def __init__(self, layer, dir_name, path):
        self.layer = layer          # customers / common
        self.dir_name = dir_name
        self.path = path
        self.dist_name = None
        self.code_dir = None
        self.configure = None
        self.overrides = None
        self.registrations = []     # 跨包冲突检查用


def check_addon(addon, findings):
    a, F = addon, findings

    def add(level, code, msg, rule="", path=""):
        F.append(Finding(level, code, a.dir_name, msg, rule, path))

    # --- R5d：能不能被 gen-custom-addon.sh 收录 -------------------------
    setup_py = os.path.join(a.path, "setup.py")
    if not os.path.isfile(setup_py):
        add(LEVEL_ERROR, "E01_NO_SETUP_PY",
            u"目录里没有 setup.py，gen-custom-addon.sh 会整包跳过（部署上等于不存在）",
            "R5d")
        return
    a.dist_name = read_dist_name(setup_py)
    if not a.dist_name:
        add(LEVEL_ERROR, "E02_NO_DIST_NAME",
            u"setup.py 里读不到 name=，生成器无法确定 egg 名，整包跳过", "R5d",
            "setup.py")
        return

    # --- R5c：分发名与代码目录大小写 -----------------------------------
    a.code_dir, tried = code_dir_for(a.path, a.dist_name)
    if a.code_dir is None:
        anyzcml = find_anycase(a.path, "configure.zcml")
        if anyzcml:
            add(LEVEL_ERROR, "E03_CASE_MISMATCH",
                u"分发名 %s 推出的代码目录（%s）大小写不匹配，实际是 %s。"
                u"显式 include 会被生成器跳过，只能靠 autoinclude；历史上这会导致"
                u"静态资源重复注册 → ConfigurationConflictError → 起不来"
                % (a.dist_name, " / ".join(tried),
                   os.path.relpath(os.path.dirname(anyzcml), a.path)),
                "R5c")
        else:
            add(LEVEL_ERROR, "E03_CASE_MISMATCH",
                u"按分发名 %s 找不到代码目录（试过 %s）"
                % (a.dist_name, " / ".join(tried)), "R5c")
        return

    a.configure = exact_case_exists(a.code_dir, "configure.zcml")
    a.overrides = exact_case_exists(a.code_dir, "overrides.zcml")
    if not a.configure:
        add(LEVEL_WARN, "W04_NO_CONFIGURE",
            u"没有 configure.zcml，生成器不会写 zcml 条目（确认这是有意的）", "R5d")

    # --- XML 合法性 + 权限 include（R1）+ 注册项收集 --------------------
    perm_uses = []          # [(file, permission)]
    has_perm_include = False
    profile_dirs = []       # [(file, directory)]

    for zpath in filter(None, [a.configure, a.overrides]):
        root, err = parse_xml(zpath)
        rel = os.path.relpath(zpath, a.path)
        if err:
            add(LEVEL_ERROR, "E08_XML_PARSE", u"ZCML 解析失败：%s" % err,
                "R4", rel)
            continue
        is_configure = (zpath == a.configure)
        for el in iter_elements(root):
            tag = localname(el.tag)
            perm = el.get("permission")
            if perm and perm.startswith(SENAITE_PERM_PREFIXES) and is_configure:
                perm_uses.append((rel, perm))
            if tag == "include" and el.get("package") == PERM_INCLUDE_PKG \
                    and is_configure:
                has_perm_include = True
            if tag == "registerProfile" and el.get("directory"):
                profile_dirs.append((rel, el.get("directory")))
            # 跨包冲突用：只收 configure.zcml 里的具名组件注册
            if is_configure and el.get("name") and tag in CONFLICTING_TAGS:
                a.registrations.append({
                    "tag": tag,
                    "name": el.get("name"),
                    "for": el.get("for", ""),
                    "manager": el.get("manager", ""),
                    "provides": el.get("provides", ""),
                    "file": rel,
                })

    if perm_uses and not has_perm_include:
        sample = perm_uses[0][1]
        add(LEVEL_ERROR, "E05_MISSING_PERM_INCLUDE",
            u"configure.zcml 用了 %s（共 %d 处）却没有 "
            u'<include package="senaite.core.permissions" />。'
            u"权限此刻尚未注册 → ComponentLookupError(IPermission, ...) → "
            u"Zope 启动失败，整站起不来"
            % (sample, len(perm_uses)), "R1", perm_uses[0][0])

    # --- R4：registerProfile 的目录必须真实存在且含 metadata.xml --------
    for rel, directory in profile_dirs:
        d = directory.replace("\\", "/").lstrip("./")
        hit = exact_case_exists(a.code_dir, d)
        if not hit:
            add(LEVEL_ERROR, "E09_PROFILE_DIR_MISSING",
                u"registerProfile 声明的目录 %s 不存在（ZCML 加载即报错）"
                % directory, "R4", rel)
        elif not exact_case_exists(hit, "metadata.xml"):
            add(LEVEL_ERROR, "E09_PROFILE_DIR_MISSING",
                u"profile 目录 %s 缺 metadata.xml" % directory, "R4", rel)

    # --- R4b：卸载能力是硬要求，豁免要付代价 ---------------------------
    uninstall = exact_case_exists(a.code_dir, "profiles/uninstall")
    if not uninstall:
        readme = (exact_case_exists(a.path, "README.md")
                  or exact_case_exists(a.path, "README.rst"))
        head = read_text(readme)[:800] if readme else u""
        declared = (u"不提供卸载" in head) or (u"不支持卸载" in head)
        upgrades = exact_case_exists(a.code_dir, "upgrades")
        if not declared:
            add(LEVEL_ERROR, "E10_NO_UNINSTALL",
                u"没有 profiles/uninstall/，README 首段也没声明合规豁免。"
                u"卸载能力是硬要求，唯一豁免是合规类 addon", "R4b")
        elif not upgrades:
            add(LEVEL_ERROR, "E10b_EXEMPT_NO_UPGRADES",
                u"声明了合规豁免却没有 upgrades/。豁免掉卸载 = 放弃唯一兜底逃生口，"
                u"必须从第一版就把 upgrade step 建起来并验证过一次", "R4b")
        else:
            add(LEVEL_INFO, "I10_UNINSTALL_EXEMPT",
                u"合规豁免已声明且 upgrades/ 存在（人工确认过 upgrade step "
                u"真的能在后台执行）", "R4b")

    # --- R14：注入外来 UI / 注册外来内容适配器必须 layer 门控 -----------
    # ★ 这里必须走**全部** .zcml，不能只看顶层 configure/overrides ——
    #   事故那处就在 browser/worksheet/configure.zcml 里。
    layers = collect_browser_layers(a.code_dir)
    for kind, rel, tag, reg_name, provides, for_str, detail in \
            scan_ui_gating(a.code_dir, a.dist_name, layers):
        relz = os.path.relpath(os.path.join(a.code_dir, rel), a.path)
        if kind == "ui_inject":
            add(LEVEL_ERROR, "E17_UI_INJECTION_UNGATED",
                u"<%s provides=\"%s\" for=\"%s\"> 往外来视图注入 UI，"
                u"既没在 for= 里放 layer，工厂 %s 里也没判 %s。"
                u"ZCML 是全局加载的 → **没装本 addon 的站点也会显示**。"
                u"该签名不含 request，ZCML 无处插 layer，"
                u"只能在 before_render() 开头判 "
                u"layer.providedBy(self.request)，不成立就 return"
                % (tag, provides.rsplit(".", 1)[-1], for_str,
                   detail or u"(未定位)", u" / ".join(sorted(layers))),
                "R14", relz)
        else:
            add(LEVEL_WARN, "W17_FOREIGN_ADAPTER_UNGATED",
                u"<%s name=\"%s\" for=\"%s\"> 把「外来内容 %s + 任意请求」"
                u"这一对全局占了，没装本 addon 的站点同样注册。"
                u"该签名里有 request —— 把它换成自己的 layer（%s）即可门控。"
                u"暂列 WARN：要够到它得手工构造 POST，不像 E17 那样必现"
                % (tag, reg_name or u"(无名)", for_str,
                   detail.rsplit(".", 1)[-1],
                   u" / ".join(sorted(layers))),
                "R14", relz)

    # --- E14：GenericSetup XML 里的非 ASCII title/description ----------
    #
    # 2026-08-31 实测事故：actions.xml 里写了中文 title + i18n:domain，
    # CMFCore 用 zope.i18nmessageid.Message（unicode 子类）去包那个字节串，
    # Py2 隐式 ASCII 解码 → UnicodeDecodeError。该 action 在 user 分类，
    # personal bar 每页都渲染 → **整站多数页面打不开**。
    #
    # 最阴的地方：lint 过、镜像建成、实例正常起、启动日志干净 ——
    # 只有真人打开页面才炸。属于 R9「静默失效」的变体：报错时机太晚。
    # ★ 只查 action 类的 XML。`types/*.xml` 有**活的反例**：
    #   maitux.reviewerassignment 的 FTI 用中文 title + i18n:domain，
    #   在生产里正常显示（侧边栏「审核工作表」）。两者都会走 Message()，
    #   差别在导入器把值存成 unicode 还是 utf-8 字节串 —— 没挖到底，
    #   所以规则只覆盖**有实测事故**的这一类，不做过度概括。
    ACTION_XML = ("actions.xml", "controlpanel.xml")
    prof_root_e14 = exact_case_exists(a.code_dir, "profiles")
    if prof_root_e14:
        for dirpath, _dirs, files in os.walk(prof_root_e14):
            for fn in files:
                if fn not in ACTION_XML:
                    continue
                p = os.path.join(dirpath, fn)
                rel = os.path.relpath(p, a.path)
                root, err = parse_xml(p)
                if err or root is None:
                    continue
                for el in iter_elements(root):
                    if localname(el.tag) != "property":
                        continue
                    if el.get("name") not in ("title", "description"):
                        continue
                    text = el.text or ""
                    if CJK.search(text) or not _is_ascii(text):
                        add(LEVEL_ERROR, "E14_NON_ASCII_GS_TITLE",
                            u"GenericSetup XML 的 <property name=\"%s\"> 含非 ASCII："
                            u"%r —— CMFCore 会用 Message() 包它，Py2 下 "
                            u"UnicodeDecodeError；若是 portal action，"
                            u"personal bar 每页渲染，**整站页面打不开**。"
                            u"要中文界面请写 ASCII msgid + locales 翻译"
                            % (el.get("name"), text.strip()[:40]), "", rel)

    # --- E15：声明了 i18n 的包，模板里不许硬编码非 ASCII 文案 ----------
    #
    # ★ 只对**已经声明 i18n** 的包生效（有 locales/ 且 configure.zcml 里
    #   registerTranslations）。没做 i18n 的包不管 —— 否则会误伤 17 个
    #   模板里写中文的 customers addon，像 E14 第一版那样制造一堆假警报。
    #   规则是"你既然声称可翻译，就别再硬编码"。
    locales_dir = exact_case_exists(a.code_dir, "locales")
    declares_i18n = bool(locales_dir) and a.configure and (
        "registerTranslations" in read_text(a.configure))
    if declares_i18n:
        for dirpath, dirs, files in os.walk(a.code_dir):
            dirs[:] = [d for d in dirs if not d.endswith("egg-info")]
            for fn in files:
                if not fn.endswith(".pt"):
                    continue
                p = os.path.join(dirpath, fn)
                rel = os.path.relpath(p, a.path)
                # 注释里的中文是给人看的说明，不进 msgid，放行
                body = re.sub(r"<!--.*?-->", "", read_text(p), flags=re.S)
                rest, msgids, defaults = split_i18n_defaults(body)

                # ① 显式 msgid 本身不许是非 ASCII —— catalog 的键必须可移植
                bad_ids = [i for i in msgids if not _is_ascii(i)]
                if bad_ids:
                    add(LEVEL_ERROR, "E15_NON_ASCII_MSGID",
                        u"i18n:translate 的显式 msgid 含非 ASCII：%s —— "
                        u"msgid 是 catalog 的键，必须 ASCII（R9b）"
                        % u"、".join(bad_ids[:3]), "", rel)

                # ② 显式 msgid 区间之外的中文才是真的「硬编码不可翻译」。
                #    这里含 i18n:translate="" 的隐式 msgid —— 那种写法
                #    msgid 就是中文本身，正是要拦的。
                bad = sorted(set(ch for ch in rest if ord(ch) > 127))
                if bad:
                    add(LEVEL_ERROR, "E15_HARDCODED_I18N_TEXT",
                        u"本包已声明 i18n（有 locales/ + registerTranslations），"
                        u"但模板里有**不在任何显式 msgid 之内**的非 ASCII 文案 %s"
                        u" —— 要么它压根没标 i18n:translate（永远不会被翻译），"
                        u"要么标的是 i18n:translate=\"\"（msgid 就是这段中文，"
                        u"违反 R9b）。中文放 locales/*.po"
                        % u"".join(bad[:6]), "", rel)

                # ③ 显式 msgid 的 default 文案是中文：不是故障，但对没有
                #    对应 catalog 的语言（如法语）会兜底显示中文，而不是英文。
                bad_def = sorted(set(ch for t in defaults for ch in t
                                     if ord(ch) > 127))
                if bad_def:
                    add(LEVEL_WARN, "W15_CJK_DEFAULT_TEXT",
                        u"显式 msgid 的 default 文案含中文 %s —— msgid 是 ASCII，"
                        u"翻译工作正常，只是 catalog 未命中的语言会兜底看到中文。"
                        u"建议 default 写英文，中文只留在 locales/zh_CN"
                        % u"".join(bad_def[:6]), "", rel)

    # --- profiles/*.xml 的 XML 合法性 ----------------------------------
    prof_root = exact_case_exists(a.code_dir, "profiles")
    if prof_root:
        for dirpath, _dirs, files in os.walk(prof_root):
            for fn in files:
                if fn.endswith(".xml"):
                    p = os.path.join(dirpath, fn)
                    _, err = parse_xml(p)
                    if err:
                        add(LEVEL_ERROR, "E08_XML_PARSE",
                            u"profile XML 解析失败：%s" % err, "R3",
                            os.path.relpath(p, a.path))

    # --- Python 2.7 语言约束 -------------------------------------------
    for dirpath, dirs, files in os.walk(a.code_dir):
        dirs[:] = [d for d in dirs if not d.endswith("egg-info")]
        for fn in files:
            if not fn.endswith(".py"):
                continue
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, a.path)
            src = read_text(p)
            # PEP 263：coding 声明只认前两行；UTF-8 BOM 在 Py2 里同样算声明
            head = u"\n".join(src.lstrip(u"﻿").splitlines()[:2])
            has_bom = src.startswith(u"﻿")
            if CJK.search(src) and not has_bom and not CODING_LINE.search(head):
                add(LEVEL_ERROR, "E06_PY2_MISSING_CODING",
                    u"含中文但前两行没有 coding 声明，Py2 import 即 SyntaxError"
                    u"（注释里的中文也算）", "", rel)
            hits, fstrings = scan_string_tokens(src)
            if fstrings:
                add(LEVEL_ERROR, "E07_FSTRING",
                    u"第 %d 行是 f-string，Python 2.7 直接 SyntaxError"
                    % fstrings[0], "", rel)
            for pat, what in PY3_PATTERNS:
                if pat.search(src):
                    add(LEVEL_WARN, "W07_PY3_SYNTAX",
                        u"疑似 Py3-only 写法：%s（本环境是 Python 2.7）" % what,
                        "", rel)
                    break

            # R11：widget 传了 query= 却没传 base_query=，会污染类级共享 dict
            for lineno, wname, keys, opaque in scan_widget_base_query(src):
                custom = [k for k in keys
                          if k not in WIDGET_QUERY_UNIVERSAL_KEYS]
                if opaque or custom:
                    what = (u"、".join(custom) if custom
                            else u"（query 非字面量，无法判定）")
                    add(LEVEL_ERROR, "E16_WIDGET_QUERY_LEAK",
                        u"第 %d 行 %s 传了 query= 但没传 base_query=，"
                        u"其中 %s 不是通用键 —— 会永久污染整个进程里所有 "
                        u"ReferenceWidget，把不具备该属性的 portal_type "
                        u"过滤成 0 条。加 base_query={} 即可"
                        % (lineno, wname, what), "R12", rel)
                else:
                    add(LEVEL_WARN, "W16_WIDGET_QUERY_LEAK",
                        u"第 %d 行 %s 传了 query= 但没传 base_query=，"
                        u"泄漏的 %s 都是通用键（senaite.core 自己也在漏），"
                        u"暂不致命；建议补 base_query={}，顺带免疫别人泼过来的键"
                        % (lineno, wname, u"、".join(keys) or u"键"), "R12", rel)
            # 中文字节串字面量：unicode 边界的高发区（docstring 与注释不算）
            if hits:
                add(LEVEL_WARN, "W07b_BYTES_CJK",
                    u"%d 处中文字节串字面量（无 u 前缀），首处在第 %d 行 —— "
                    u"与 unicode 拼接/比较时是 UnicodeDecodeError 的常见起点"
                    % (len(hits), hits[0]), "", rel)


# --------------------------------------------------------------------------
# 跨包检查（R5b）
# --------------------------------------------------------------------------

def check_cross_addon(addons, findings):
    seen = {}
    for a in addons:
        for reg in a.registrations:
            key = (reg["tag"], reg["name"], reg["for"], reg["manager"],
                   reg["provides"])
            seen.setdefault(key, []).append((a.dir_name, reg["file"]))
    for key, owners in sorted(seen.items()):
        names = sorted(set(o[0] for o in owners))
        if len(names) < 2:
            continue
        tag, name, for_, manager, provides = key
        findings.append(Finding(
            LEVEL_ERROR, "E11_DUP_REGISTRATION", " + ".join(names),
            u"%s name=%s%s%s 在 %d 个包的 configure.zcml 里重复注册 → "
            u"ConfigurationConflictError → 容器重启循环。"
            u"要共存就把冲突方移进各自的 overrides.zcml 并确认 -overrides slug"
            % (tag, name,
               (u" for=%s" % for_) if for_ else u"",
               (u" provides=%s" % provides) if provides else u"",
               len(names)),
            "R5b"))


# --------------------------------------------------------------------------
# 容器内 Py2 编译（可选）
# --------------------------------------------------------------------------

# 只 compile 不落盘：不往 bind-mount 的宿主目录写 .pyc。
# 注意（2026-08-30 在 maituxlimslatest 实测）：Py2 的 compile() 与 py_compile /
# compileall 都【不】执行 PEP 263 的编码声明检查，只有真正 import / 直接运行文件
# 才报 "Non-ASCII character ... but no encoding declared"。所以缺 coding 声明这一项
# 由宿主侧的 E06 负责，容器这一趟只兜底纯语法（f-string、py3 写法等）。
PY2_COMPILE_SNIPPET = (
    "import os,sys\n"
    "rc=0\n"
    "for dp,dn,fn in os.walk(sys.argv[1]):\n"
    "    dn[:]=[d for d in dn if not d.endswith('egg-info')]\n"
    "    for f in fn:\n"
    "        if not f.endswith('.py'): continue\n"
    "        p=os.path.join(dp,f)\n"
    "        try: compile(open(p,'rb').read(), p, 'exec')\n"
    "        except SyntaxError as e:\n"
    "            rc=1; print('%s:%s: %s' % (p, e.lineno, e.msg))\n"
    "sys.exit(rc)\n"
)


def check_in_container(addons, container, findings):
    for a in addons:
        target = "%s/%s/%s" % (CONTAINER_ADDONS_ROOT, a.layer, a.dir_name)
        # common 是构建期 COPY：宿主机上有、容器里没有 = 还没重建镜像。
        # 这种情况下容器里根本没有这份源码，必须报"跳过"而不是静默通过。
        probe = subprocess.run(
            ["docker", "exec", container, "test", "-d", target],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if probe.returncode != 0:
            findings.append(Finding(
                LEVEL_WARN, "W13_NOT_IN_CONTAINER", a.dir_name,
                u"容器里没有 %s，跳过容器内语法检查。"
                u"common 层是构建期 COPY，改了必须重建镜像才会进容器；"
                u"在此之前容器里跑的仍是镜像里的旧源码" % target))
            continue
        cmd = ["docker", "exec", container, "python", "-c",
               PY2_COMPILE_SNIPPET, target]
        try:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, timeout=180)
        except Exception as exc:
            findings.append(Finding(
                LEVEL_WARN, "W13_CONTAINER_UNAVAILABLE", a.dir_name,
                u"容器内编译跳过：%r" % (exc,)))
            return
        if proc.returncode != 0:
            out = proc.stdout.decode("utf-8", "replace").strip()
            findings.append(Finding(
                LEVEL_ERROR, "E13_PY2_COMPILE_FAIL", a.dir_name,
                u"容器内 Python 2.7 编译失败：\n%s" % out[:2000]))


# --------------------------------------------------------------------------

def collect_addons(addons_root, only=None):
    out = []
    for layer in ("customers", "common"):
        layer_dir = os.path.join(addons_root, layer)
        if not os.path.isdir(layer_dir):
            continue
        for name in sorted(os.listdir(layer_dir)):
            p = os.path.join(layer_dir, name)
            if not os.path.isdir(p):
                continue
            if not os.path.isfile(os.path.join(p, "setup.py")):
                continue  # 生成器也会跳过，不是 addon
            if only and name != only:
                # 仍然加载，跨包冲突检查需要全量视图
                a = Addon(layer, name, p)
                a._muted = True
                out.append(a)
                continue
            a = Addon(layer, name, p)
            a._muted = False
            out.append(a)
    return out


# --------------------------------------------------------------------------
# 基线：把门禁语义从「lint 全绿」改成「不新增 ERROR」
#
# 这条政策 Docs/SENAITE-Addon流水线.md 早就写死了：
#     「新包的门槛是"不新增 ERROR"，不是"lint 全绿"。」
# 但工具一直是"有 ERROR 就 exit 1"，两者不一致 —— 后果是**别人一跑就红，
# 红的还是别人包的问题**，于是所有人开始忽略 lint 输出，真 ERROR 也拦不住了。
# 那正是 SKILL.md「宁可窄，不可宽」一节反复警告的失效模式。
#
# 指纹用 (addon, code, path) 三元组，**故意不含行号和消息文本**：
# 行号一改代码就漂，消息里还带计数（W07b 的"33 处"），都会让基线天天失效。
# 同一个 (addon, code, path) 可能命中多次，所以基线存 count，
# 实测数 > 基线数 也算新增。
#
# ★ 基线不是"永久豁免"，是"欠账清单"：
#   · 每条带 recorded 日期与 note，可评审
#   · 基线里已经不再出现的条目会被报成「已消失」，提示重写基线把它剔掉
#     —— 否则基线会烂成一张没人看的免死金牌
BASELINE_FILENAME = "lint_baseline.json"


def default_baseline_path(addons_root):
    """基线跟着 addons/customers/ 走 —— 那样 clone senaite.docker 的人白得。"""
    return os.path.join(addons_root, "customers", BASELINE_FILENAME)


def finding_key(f):
    """基线指纹。path 统一成正斜杠，免得 Windows / Linux 上互相不认。"""
    return (f.addon, f.code, (f.path or u"").replace("\\", "/"))


def _counted(findings):
    out = {}
    for f in findings:
        k = finding_key(f)
        out[k] = out.get(k, 0) + 1
    return out


def load_baseline(path):
    """返回 ({key: count}, meta, err)。文件不存在不是错误。"""
    if not os.path.isfile(path):
        return {}, None, None
    try:
        with io.open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:
        return {}, None, u"基线文件读不动（%s）：%r" % (path, exc)
    counts = {}
    for e in data.get("entries", []):
        try:
            k = (e["addon"], e["code"],
                 (e.get("path") or u"").replace("\\", "/"))
        except KeyError:
            continue
        counts[k] = counts.get(k, 0) + int(e.get("count", 1))
    return counts, data, None


def write_baseline(path, findings, only_levels=(LEVEL_ERROR,)):
    """把当前结果写成基线。默认只记 ERROR —— WARN 不参与门禁，记它没意义。"""
    keep = [f for f in findings if f.level in only_levels]
    entries = []
    for (addon, code, p), n in sorted(_counted(keep).items()):
        lvl = next((f.level for f in keep if finding_key(f) == (addon, code, p)),
                   LEVEL_ERROR)
        entries.append({
            "addon": addon, "code": code, "path": p, "count": n,
            "level": lvl,
            "note": u"",       # ← 人工填：为什么还欠着、谁负责、什么时候还
        })
    payload = {
        "_说明": u"lint 门禁基线：这里列的是**已知欠账**，门禁只拦不在本表里的 "
                 u"ERROR（政策见 Docs/SENAITE-Addon流水线.md「不新增 ERROR」）。"
                 u"基线不是永久豁免 —— 修掉一条就重写本表把它剔掉；"
                 u"lint 会把「基线里已消失」的条目报出来提醒你重写。",
        "_重写命令": u"python lint_addon.py --write-baseline "
                     u"<addons>/customers/" + BASELINE_FILENAME,
        "recorded": _today(),
        "entries": entries,
    }
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, indent=2))
    return len(entries)


def _today():
    import datetime
    return datetime.date.today().isoformat()


def split_by_baseline(findings, baseline):
    """按基线切三份：new（要拦）、suppressed（已知欠账）、stale（基线里已消失）。"""
    seen = _counted(findings)
    new, suppressed = [], []
    used = {}
    for f in findings:
        k = finding_key(f)
        allowed = baseline.get(k, 0)
        used[k] = used.get(k, 0) + 1
        if used[k] <= allowed:
            suppressed.append(f)
        else:
            new.append(f)
    stale = [(k, n) for k, n in sorted(baseline.items())
             if seen.get(k, 0) < n]
    return new, suppressed, stale


# --------------------------------------------------------------------------
# 两份副本的漂移守卫
#
# lint_addon.py 有两份（见文件头注释），必须内容一致。多人协作下这必然漂：
# 有人只改了 senaite.docker 那份，技能里那份还是旧的（或反之），
# 于是"同一条规则两个人跑出不同结果"，比没有规则更糟。
# 只提示、不拦 —— 拦了会在别人只 clone 一份的场景下误伤。
def check_self_copies(addons_root):
    """返回提示文本或 None。"""
    me = os.path.abspath(__file__)
    other = os.path.abspath(os.path.join(addons_root, "customers",
                                         os.path.basename(__file__)))
    if me == other or not os.path.isfile(other):
        return None
    try:
        a = read_text(me).replace(u"\r\n", u"\n")
        b = read_text(other).replace(u"\r\n", u"\n")
    except Exception:
        return None
    if a == b:
        return None
    return (u"⚠ 两份 lint_addon.py 内容不一致（忽略行尾差异后仍不同）：\n"
            u"    正在跑：%s\n"
            u"    另一份：%s\n"
            u"  规则文档靠 addons/customers 那份机器化，两份必须同步；"
            u"否则同一条规则两个人会跑出不同结果。" % (me, other))


# --------------------------------------------------------------------------
# 按包汇总表：批量看 21 个包时的主视图
#
# 逐条明细适合"我刚改完这一个包"；批量评审要的是另一种东西 ——
# 哪些包干净、哪些包欠账、欠的是哪一类。**干净的包也必须列出来**，
# 否则看不出"扫到了但没问题"和"压根没扫到"的区别（后者是 R5d 的经典坑：
# 目录缺 setup.py 被生成器整包跳过，部署上等于不存在）。
def print_rollup(scanned, findings, baseline):
    per = {}
    for a in scanned:
        per[a.dir_name] = {"layer": a.layer, LEVEL_ERROR: 0,
                           LEVEL_WARN: 0, LEVEL_INFO: 0, "new_err": 0}
    new, _sup, _stale = split_by_baseline(findings, baseline)
    new_keys = _counted([f for f in new if f.level == LEVEL_ERROR])
    for f in findings:
        row = per.get(f.addon)
        if row is None:
            continue
        row[f.level] += 1
    for (addon, _c, _p), n in new_keys.items():
        if addon in per:
            per[addon]["new_err"] += n

    def sort_key(item):
        name, r = item
        return (-r["new_err"], -r[LEVEL_ERROR], -r[LEVEL_WARN], name)

    lines = [u"按包汇总（%d 个包；★ = 本次新增 ERROR，门禁只看这一列）" % len(per),
             u"  %-32s %-10s %5s %5s %5s  %s"
             % (u"包", u"层", u"ERR", u"WARN", u"INFO", u"判定")]
    for name, r in sorted(per.items(), key=sort_key):
        if r["new_err"]:
            verdict = (u"★ 新增 %d 条 ERROR" % r["new_err"] if baseline
                       else u"★ %d 条 ERROR（无基线）" % r["new_err"])
        elif r[LEVEL_ERROR]:
            verdict = u"欠账（基线已记）"
        elif r[LEVEL_WARN]:
            verdict = u"仅 WARN"
        elif r[LEVEL_INFO]:
            verdict = u"干净（有 INFO）"
        else:
            verdict = u"干净"
        lines.append(u"  %-32s %-10s %5d %5d %5d  %s"
                     % (name, r["layer"], r[LEVEL_ERROR], r[LEVEL_WARN],
                        r[LEVEL_INFO], verdict))
    return u"\n".join(lines) + u"\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="SENAITE addon 静态检查")
    ap.add_argument("--addons-root", default=DEFAULT_ADDONS_ROOT)
    ap.add_argument("--addon", help="只报告这一个包（跨包检查仍全量加载）")
    ap.add_argument("--in-container", action="store_true",
                    help="额外用容器里的 Python 2.7 跑 compileall")
    ap.add_argument("--container", default=DEFAULT_CONTAINER)
    ap.add_argument("--json", help="把结果写成 JSON")
    ap.add_argument("--baseline",
                    help=u"基线文件（默认自动找 <addons>/customers/%s）"
                         % BASELINE_FILENAME)
    ap.add_argument("--no-baseline", action="store_true",
                    help=u"忽略基线，按「lint 全绿」判定（严格模式）")
    ap.add_argument("--write-baseline", nargs="?", const="", metavar="FILE",
                    help=u"把当前 ERROR 写成基线然后退出（不带值＝写默认路径）")
    ap.add_argument("--summary", action="store_true",
                    help=u"只打按包汇总表，不打逐条明细（批量看 21 个包时用）")
    args = ap.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    root = os.path.abspath(args.addons_root)
    if not os.path.isdir(root):
        print(u"找不到 addons 根目录：%s" % root)
        return 2

    drift = check_self_copies(root)
    if drift:
        print(drift + u"\n")

    addons = collect_addons(root, args.addon)
    if args.addon and not any(not a._muted for a in addons):
        print(u"没找到 addon：%s" % args.addon)
        return 2

    findings = []
    for a in addons:
        sub = []
        check_addon(a, sub)
        if not a._muted:
            findings.extend(sub)
    cross = []
    check_cross_addon(addons, cross)
    for f in cross:
        if not args.addon or args.addon in f.addon:
            findings.append(f)
    if args.in_container:
        targets = [a for a in addons if not a._muted]
        check_in_container(targets, args.container, findings)

    errors = [f for f in findings if f.level == LEVEL_ERROR]
    warns = [f for f in findings if f.level == LEVEL_WARN]
    infos = [f for f in findings if f.level == LEVEL_INFO]

    scanned = [a for a in addons if not a._muted]

    # --- 写基线后退出 ------------------------------------------------------
    if args.write_baseline is not None:
        target = args.write_baseline or default_baseline_path(root)
        if args.addon:
            print(u"拒绝执行：--write-baseline 必须全量扫描后再写，"
                  u"否则会把没扫到的包当成「已修好」从基线里抹掉。"
                  u"去掉 --addon 重跑。")
            return 2
        n = write_baseline(target, findings)
        print(u"已把 %d 条 ERROR 写成基线：%s\n"
              u"→ 请逐条填上 note（为什么还欠着 / 谁负责），再提交。"
              % (n, target))
        return 0

    # --- 基线 --------------------------------------------------------------
    baseline, bmeta, berr = {}, None, None
    bpath = args.baseline or default_baseline_path(root)
    if not args.no_baseline:
        baseline, bmeta, berr = load_baseline(bpath)
        if berr:
            print(u"⚠ %s\n  本次按严格模式（有 ERROR 即拦）判定。\n" % berr)

    new, suppressed, stale = split_by_baseline(findings, baseline)
    new_errors = [f for f in new if f.level == LEVEL_ERROR]

    print(u"扫描 %d 个 addon（%s）" % (len(scanned), root))
    if baseline:
        print(u"基线：%s（%d 条已知欠账，recorded=%s）"
              % (bpath, sum(baseline.values()),
                 (bmeta or {}).get("recorded", u"?")))
    elif not args.no_baseline:
        print(u"基线：无（%s 不存在）—— 按「有 ERROR 即拦」判定。"
              u"要把现存欠账固化成基线：--write-baseline" % bpath)
    print(u"")

    # --- 逐条明细（--summary 时跳过）---------------------------------------
    if not args.summary:
        shown = new if baseline else findings
        for level, bucket in ((LEVEL_ERROR, [f for f in shown
                                             if f.level == LEVEL_ERROR]),
                              (LEVEL_WARN, [f for f in shown
                                            if f.level == LEVEL_WARN]),
                              (LEVEL_INFO, [f for f in shown
                                            if f.level == LEVEL_INFO])):
            for f in bucket:
                rule = u"[%s]" % f.rule if f.rule else u""
                path = u" %s" % f.path if f.path else u""
                print(u"%-5s %-26s %s%s%s\n      %s"
                      % (level, f.code, f.addon, path, rule, f.msg))

    # --- 按包汇总表：批量看的主视图 ---------------------------------------
    if len(scanned) > 1:
        print(print_rollup(scanned, findings, baseline))

    # --- 基线账目 ----------------------------------------------------------
    if suppressed:
        by_addon = {}
        for f in suppressed:
            by_addon.setdefault(f.addon, []).append(f.code)
        print(u"基线抑制了 %d 条既有 ERROR（不拦，但仍是欠账）：" % len(suppressed))
        for addon in sorted(by_addon):
            print(u"  · %-30s %s"
                  % (addon, u"、".join(sorted(set(by_addon[addon])))))
        print(u"")
    if stale:
        print(u"★ 基线里有 %d 条已经不再出现 —— 说明修好了，"
              u"请重写基线把它们剔掉（否则基线会烂成免死金牌）：" % len(stale))
        for (addon, code, p), n in stale:
            print(u"  · %s %s %s" % (addon, code, p))
        print(u"  重写：python %s --write-baseline\n"
              % os.path.basename(__file__))

    # --- 判定 --------------------------------------------------------------
    print(u"合计：%d ERROR / %d WARN / %d INFO"
          % (len(errors), len(warns), len(infos)))
    if baseline:
        print(u"门禁（不新增 ERROR）：新增 %d 条 ERROR" % len(new_errors))
    if not new_errors:
        if suppressed:
            print(u"✔ 通过 —— 没有新增 ERROR（%d 条既有欠账见上）。"
                  u"可以进入 senaite-addon-deploy" % len(suppressed))
        else:
            print(u"✔ 通过 —— ERROR 为 0，可以进入 senaite-addon-deploy")
    elif baseline:
        print(u"✘ 拦下 —— 上面 %d 条 ERROR 不在基线里，是本次新增的"
              % len(new_errors))
    else:
        # 没有基线时这些 ERROR 未必是"本次"引入的，别把话说死 ——
        # 措辞一失真，人就开始不信这个工具了。
        print(u"✘ 拦下 —— %d 条 ERROR（无基线，无法区分既有欠账与本次新增）。"
              u"若确认都是既有问题，用 --write-baseline 固化后再跑"
              % len(new_errors))

    if args.json:
        payload = {
            "addons_root": root,
            "scanned": [a.dir_name for a in scanned],
            "errors": len(errors), "warnings": len(warns),
            "baseline_path": bpath if baseline else None,
            "new_errors": len(new_errors),
            "suppressed": len(suppressed),
            "stale_baseline": [
                {"addon": k[0], "code": k[1], "path": k[2], "count": n}
                for k, n in stale],
            "gate": "pass" if not new_errors else "fail",
            "findings": [f.as_dict() for f in findings],
            "new_findings": [f.as_dict() for f in new],
        }
        with io.open(args.json, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False, indent=2))
        print(u"已写出 %s" % args.json)

    return 1 if new_errors else 0


if __name__ == "__main__":
    sys.exit(main())
