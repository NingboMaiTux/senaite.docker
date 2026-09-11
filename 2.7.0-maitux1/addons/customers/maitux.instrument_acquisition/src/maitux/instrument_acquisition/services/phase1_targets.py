# -*- coding: utf-8 -*-
"""采集目标位定义 —— 由 interim 上的两个标记按行推导

本模块是"某个分析行的哪些字段参与仪器采集"的唯一判定处：

- 采集界面读它生成"待分配目标列表"
- 回写服务只允许回写它认定的目标位
- `manage_results` 只读渲染同样依赖它

★ **目标位不再写死。** 客户在 Calculation 的 interim 上配两个标记
（`acquisition_role` / `acquisition_group`，由 maitux.calcenhance 注册为
subfield），本模块按**分析的 interim 快照**推导出目标位。留在代码里的只有
角色词表（name / weight）与每个角色的槽位元数据。
语义见 `Docs/Cal增加/maitux.calcenhance-仪器采集标记-需求与方案.md` §4.1。

★ **快照不追溯**：标记导入之前建的分析没有这两个键，采集页就没有目标位 ——
这是 CLAUDE.md §6.3.2 的预期行为。要让老分析参与采集，得重建分析。

目标位采用 `target_key` 字符串抽象（`{analysis_uid}:{keyword}[:{seq}]`），
不直接引用 Analysis UID 对象；将来升级为独立的 InstrumentReading content
type 与 UID 引用（`assigned_analysis_uids`）时只需解析此字符串。
"""

# 入站接口固定鉴权 Token（第一阶段写死，后续升级为配置界面）
PHASE1_INGEST_TOKEN = "maitux-phase1-instrument-acquisition-token"

# 远端采集端模式（默认开启）：
#   True  —— 云 LIMS 与实验室本地采集端（agent）分离部署。LIMS 点「开始采集」
#            只标记会话为监听状态并登记占用者，**不**由 LIMS 进程内 relay 直连
#            仪器（云连不到实验室内网）；本地采集端轮询
#            `@@instrument_acquisition_api_agent_config` 拿到 start/ip/port 后
#            自行连接仪器，读数按 instrument_code 推回 LIMS。
#   False —— 进程内 relay 模式（LIMS 与仪器同网，或仪器地址可直连时）：
#            LIMS 自己连接仪器收数，读数进 relay 内存队列由采集页轮询写入。
PHASE1_AGENT_MODE = True

# 开始采集时仪器 TCP 连通性探测超时（秒）
PHASE1_TCP_PROBE_TIMEOUT = 3

# Worksheet annotations 存储键
PHASE1_ANNOTATION_KEY = "maitux.instrument_acquisition.v1.session"
PHASE1_SESSION_INDEX_KEY = "maitux.instrument_acquisition.v1.session_index"

# ---------------------------------------------------------------------------
# 采集角色词表
#
# ★ 这里**不再**写死「哪些 keyword 参与采集」—— 那是客户可配的，配在
# Calculation 的 interim 上（`acquisition_role` / `acquisition_group` 两个
# subfield，由 maitux.calcenhance 注册；语义见需求方案 §4.1）。
#
# 留在代码里的只有**角色的取值集合**与每个角色的槽位元数据：角色只有
# name / weight 两种，是代码级词汇，不是客户可配项。
# ---------------------------------------------------------------------------

ROLE_NAME = "name"
ROLE_WEIGHT = "weight"

# role → 槽位元数据。display_order 决定组内字段次序（名称在前、重量在后）。
ACQUISITION_ROLE_META = {
    ROLE_NAME: {
        "display_order": 1,
        "value_type": "string",
        "allow_multi_assign": False,
        # 名称允许手工填写（仪器不给名称）
        "manual_input": True,
    },
    ROLE_WEIGHT: {
        "display_order": 2,
        "value_type": "float",
        "allow_multi_assign": True,
        "manual_input": False,
    },
}

# interim dict 上两个标记的键名
ACQUISITION_ROLE_KEY = "acquisition_role"
ACQUISITION_GROUP_KEY = "acquisition_group"

# ★ Dexterity 的编辑表单把「空的 TextLine 子字段」存成这个**字符串字面量**，
# 而它是**真值** —— `if role:` / `if group:` 会把"不参与采集"当成参与，
# 直接拿它做数值比较则抛异常。读这两个标记的地方一律先过 `_clean_mark()`。
# 出处：Backlog S1「新发现」（2026-09-10 实测，全站曾有 44 格）。
NO_VALUE_MARKER = "<NO_VALUE>"

# 运行环境是 Python 2（容器），但本模块的纯函数会被宿主机的 python3
# 直接按文件路径加载做单测（tests/test_phase1_targets.py），故两边都要兼容。
# 写法与 api/views.py:28 的 `_TEXT` shim 一致。
try:  # Python 2
    _TEXT = unicode
    _TEXT_TYPES = (str, unicode)
except NameError:  # Python 3
    _TEXT = str
    _TEXT_TYPES = (str,)

# target_key 分隔符："{analysis_uid}:{interim_keyword}" 或
# "{analysis_uid}:{interim_keyword}:{seq}"（数组字段的手动添加行）
TARGET_KEY_SEPARATOR = ":"

# 数组类型 result_type（interim field）：值存 JSON 数组，目标位支持手动添加行
ARRAY_RESULT_TYPES = (
    "list",
    "multiselect",
    "multiselect_duplicates",
    "multichoice",
)


def is_array_result_type(result_type):
    """interim 的 result_type 是否数组类型"""
    return ((result_type or u"").strip().lower()
            in ARRAY_RESULT_TYPES)


def _clean_mark(value):
    """把 interim 上的标记值归一成 unicode；`<NO_VALUE>`/空白 → u""

    ★ 不要省这一步，见 NO_VALUE_MARKER 的注释。
    另外兼容 XLSX 导入器可能给的 int / float（`acquisition_group`）。
    """
    if value is None:
        return u""
    if isinstance(value, bool):
        # 布尔不是有效的角色或分组号（标记误配到勾选列时会出现）
        return u""
    if not isinstance(value, _TEXT_TYPES):
        try:
            text = u"%s" % value
        except Exception:
            return u""
    elif isinstance(value, _TEXT):
        text = value
    else:
        # py2 的 bytes（中文标题从 Archetypes 回来可能是 str）
        try:
            text = value.decode("utf-8")
        except UnicodeDecodeError:
            return u""
    text = text.strip()
    if text == NO_VALUE_MARKER:
        return u""
    return text


def read_acquisition_group(interim):
    """读 interim 的采集分组号；**0 = 不参与采集**

    兼容 int / float / str 三种来源（XLSX 导入器与 Dexterity 编辑表单
    给的类型不同），非法值一律当 0。
    """
    text = _clean_mark(interim.get(ACQUISITION_GROUP_KEY))
    if not text:
        return 0
    try:
        group = int(float(text))
    except (TypeError, ValueError):
        return 0
    return group if group > 0 else 0


def read_acquisition_role(interim):
    """读 interim 的采集角色；未配置或不在词表内返回 u"" """
    role = _clean_mark(interim.get(ACQUISITION_ROLE_KEY)).lower()
    if role not in ACQUISITION_ROLE_META:
        return u""
    return role


def build_definitions_for_interims(interims, on_invalid=None):
    """由 interim 列表推导采集目标位定义（纯函数，可脱离 Zope 单测）

    跳过规则：
    - 两个标记都没配 → 纯计算字段，**静默**跳过（这是绝大多数字段）
    - 只配了一半 / 角色不在词表内 → 配错了，跳过但**回调留痕**
      （R9「失败大多是静默的」：这种错必须能查出来）

    :param interims: `analysis.getInterimFields()` 的返回值
    :param on_invalid: 可选回调 `on_invalid(keyword, reason)`，让调用方记日志
                       —— 本模块不持有 logger，保持可单测
    :returns: 定义列表，按 (角色次序, 快照出现序) 稳定排序
    """
    definitions = []
    for index, interim in enumerate(interims or []):
        keyword = _clean_mark(interim.get("keyword"))
        if not keyword:
            continue
        role = _clean_mark(interim.get(ACQUISITION_ROLE_KEY)).lower()
        group = read_acquisition_group(interim)
        if not role and not group:
            # 纯计算字段：不参与采集
            continue
        reason = u""
        if role not in ACQUISITION_ROLE_META:
            reason = u"未知的采集角色「%s」（可选：%s）" % (
                role, u" / ".join(sorted(ACQUISITION_ROLE_META)))
        elif group <= 0:
            reason = u"采集角色已配（%s）但分组号无效，不会出现在采集页" % role
        if reason:
            if on_invalid is not None:
                on_invalid(keyword, reason)
            continue
        meta = ACQUISITION_ROLE_META[role]
        definitions.append({
            # 抽象目标位标识（= interim keyword，页面按分析行组合出 target_key）
            "target_key": keyword,
            # 保留字段：现由标记按行决定，不再按 AS 限定
            "analysis_service_keyword": "",
            "interim_keyword": keyword,
            # ★ 标题取 interim 自己的 title —— 比"角色→固定中文名"准确，
            # 能区分「对照品1称样量(mg)」与「对照品2称样量(mg)」
            "display_title": _clean_mark(interim.get("title")) or keyword,
            "allow_multi_assign": meta["allow_multi_assign"],
            "sort_order": meta["display_order"],
            "value_type": meta["value_type"],
            "manual_input": meta["manual_input"],
            "acquisition_role": role,
            "acquisition_group": group,
            "result_type": _clean_mark(interim.get("result_type")),
            # 同角色多字段（对照品1/2）按快照出现序稳定排
            "interim_index": index,
        })
    definitions.sort(key=lambda d: (d["sort_order"], d["interim_index"]))
    return definitions


def build_target_definitions(analysis, on_invalid=None):
    """按**分析行**推导采集目标位定义

    ★ 读的是分析的 interim **快照**，不是 Calculation。快照不追溯
    （CLAUDE.md §6.3.2）：标记导入之前建的分析没有这两个键，返回空列表 ——
    这是**预期行为**，不是 bug。
    """
    try:
        interims = analysis.getInterimFields() or []
    except Exception:
        return []
    return build_definitions_for_interims(interims, on_invalid=on_invalid)


def get_target_definition(analysis, keyword, on_invalid=None):
    """按 (分析行, keyword) 取目标位定义；未被标记返回 None

    ★ 这个函数取代了原来的全局白名单 `keyword in PHASE1_KEYWORDS`：
    `assign_reading` / `set_manual_value` / `writeback.save` 三处校验都走它，
    于是"把读数分配到某个没标记的字段上"会被拒 —— 原来是放行的。
    """
    if not keyword:
        return None
    for definition in build_target_definitions(analysis, on_invalid=on_invalid):
        if definition["interim_keyword"] == keyword:
            return definition
    return None


def get_marked_keywords(analysis):
    """返回该分析行上被标成采集目标的 interim keyword 列表"""
    return [item["interim_keyword"]
            for item in build_target_definitions(analysis)]


def get_readonly_keywords(analysis):
    """返回该分析行需要只读保护的 keyword（= 被标成采集目标的那些）

    ★ 签名从"无参"改成"按分析行" —— worksheet 级的并集见
    `session_store.collect_readonly_keywords()`。
    """
    return get_marked_keywords(analysis)


def make_target_key(analysis_uid, keyword, seq=None):
    """由分析 UID 与 interim keyword 组合出具体目标位的 target_key

    数组字段（result_type 为 list/multiselect 等）支持手动添加行：
    - 基础行（seq=None/0）："{analysis_uid}:{keyword}"
    - 添加行（seq>=1）："{analysis_uid}:{keyword}:{seq}"

    第一阶段用 target_key 字符串抽象"某个分析行的某个字段"；
    第二阶段迁移到 `assigned_analysis_uids` 时，只需解析此字符串即可。
    """
    key = u"{}{}{}".format(analysis_uid, TARGET_KEY_SEPARATOR, keyword)
    if seq:
        key = u"{}{}{}".format(key, TARGET_KEY_SEPARATOR, seq)
    return key


def parse_target_key_full(target_key):
    """解析 target_key，返回 (analysis_uid, interim_keyword, seq)

    - "{analysis_uid}:{keyword}"          → (uid, kw, 0)
    - "{analysis_uid}:{keyword}:{seq}"    → (uid, kw, seq)
    无法解析时返回 (None, None, None)。
    """
    target_key = target_key or u""
    parts = target_key.split(TARGET_KEY_SEPARATOR)
    if len(parts) < 2:
        return None, None, None
    analysis_uid = (parts[0] or u"").strip()
    keyword = (parts[1] or u"").strip()
    if not analysis_uid or not keyword:
        return None, None, None
    seq = 0
    if len(parts) > 2:
        try:
            seq = int(parts[2])
        except (TypeError, ValueError):
            return None, None, None
    return analysis_uid, keyword, seq


def parse_target_key(target_key):
    """解析 target_key，返回 (analysis_uid, interim_keyword)

    兼容数组字段的带序号 target_key（"{uid}:{kw}:{seq}"），
    只返回前两段。无法解析时返回 (None, None)。
    """
    analysis_uid, keyword, _seq = parse_target_key_full(target_key)
    return analysis_uid, keyword
