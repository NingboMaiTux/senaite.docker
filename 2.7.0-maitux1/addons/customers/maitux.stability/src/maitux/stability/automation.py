# -*- coding: utf-8 -*-
"""稳定性「样品模板 + 自动登样」的配置读取（对象级 / registry 级）。

配置分三处，优先级从高到低：

1. **方案**（``StabilityPlan``）：``auto_create_samples`` / ``contact``
   —— 逐个方案可覆盖（新建方案时从方案模板带入初值，见 ``browser/add.py``）；
2. **方案模板**（``StabilityPlanTemplate``）：``sample_template`` /
   ``auto_create_samples`` / ``contact`` —— 按品种/项目给默认值；
3. **站点配置**（``plone.app.registry``，界面见 ``@@stability-automation-controlpanel``）：
   ``auto_create_enabled`` / ``auto_create_time`` / ``auto_create_lead_days`` /
   ``zero_point_lookback_days`` —— 全站运营口径。

**为什么"生成时刻 / 窗口天数"放站点级**：全站只有一套运营节奏
（一个调度任务、一套实验室排班）；按品种各配一套会出现"空值算覆盖还是算继承"
的歧义（Int 的 0 既可能表示"就是 0 天"、也可能表示"没填"）。
模板只决定"这个品种要不要自动登样、用哪个样品模板、联系谁"。
将来若确需按品种配窗口，再加模板字段并明确空值语义。

纯逻辑（时刻解析、边界判定）在 `sampleautomation.py`；本模块只做
"取对象 / 读 registry / 解析优先级"，不写业务判定。
"""

from bika.lims import api
from plone.supermodel import model
from senaite.core import logger
from zope import schema

from maitux.stability import stabilityMessageFactory as _
from maitux.stability import plan_status
from maitux.stability import sampleautomation as sa
from maitux.stability import timepoints as tp
from maitux.stability.sampleautomation import DEFAULT_GENERATION_TIME
from maitux.stability.sampleautomation import DEFAULT_LEAD_DAYS
from maitux.stability.sampleautomation import DEFAULT_ZERO_POINT_LOOKBACK_DAYS
from maitux.stability.sampleautomation import PROBLEM_CLIENT_TEMPLATE_MISMATCH
from maitux.stability.sampleautomation import PROBLEM_CONTACT_OTHER_CLIENT
from maitux.stability.sampleautomation import PROBLEM_NO_CLIENT
from maitux.stability.sampleautomation import PROBLEM_NO_CONTACT
from maitux.stability.sampleautomation import PROBLEM_NO_SAMPLE_TEMPLATE
from maitux.stability.sampleautomation import PROBLEM_NO_SAMPLE_TYPE
from maitux.stability.sampleautomation import PROBLEM_NO_SERVICES
from maitux.stability.sampleautomation import parse_generation_time
from maitux.stability.sampleautomation import resolve_bool
from maitux.stability.sampleautomation import resolve_int


# registry.xml 里的 prefix（记录键 = "<prefix>.<字段名>"）
REGISTRY_PREFIX = "maitux.stability"


class IStabilityAutomationSettings(model.Schema):
    """稳定性自动登样 —— 站点级设置（plone.app.registry）。"""

    model.fieldset(
        "automation",
        label=_(u"Sample Automation"),
        fields=[
            "auto_create_enabled",
            "auto_create_time",
            "auto_create_lead_days",
            "zero_point_lookback_days",
        ],
    )

    auto_create_enabled = schema.Bool(
        title=_(u"Enable automatic sample creation"),
        description=_(
            u"Master switch for the whole site. When it is off, no sample is "
            u"created automatically; creating samples by hand still works."
        ),
        default=False,
        required=False,
    )

    auto_create_time = schema.TextLine(
        title=_(u"Time of day for automatic creation"),
        description=_(
            u"24-hour HH:MM (default 08:00). A timepoint whose target date is "
            u"today is handled once the current time has passed this value. "
            u"The scheduled task may run more often; the time is read from "
            u"this setting, not from the scheduler."
        ),
        default=DEFAULT_GENERATION_TIME,
        missing_value=u"",
        required=False,
    )

    auto_create_lead_days = schema.Int(
        title=_(u"Create samples N days before the target date"),
        description=_(u"0 = create on the target date itself (default)."),
        default=DEFAULT_LEAD_DAYS,
        required=False,
    )

    zero_point_lookback_days = schema.Int(
        title=_(u"Zero point: look-back window (days)"),
        description=_(
            u"How far back from T0 a sample may be dated to be linked as the "
            u"zero point sample (default 30)."
        ),
        default=DEFAULT_ZERO_POINT_LOOKBACK_DAYS,
        required=False,
    )


def _settings_fields():
    """站点配置 schema 的字段名（有序）。"""
    try:
        from zope.schema import getFieldsInOrder
        return [name for name, _field in
                getFieldsInOrder(IStabilityAutomationSettings)]
    except Exception:
        return ["auto_create_enabled", "auto_create_time",
                "auto_create_lead_days", "zero_point_lookback_days"]


def ensure_records():
    """给"安装之后才新增的字段"补 registry 记录，返回补了哪些字段。

    ``plone.app.registry`` 的设置页会调 ``forInterface()``（**不带** ``check=False``），
    只要有一个字段缺记录，**整页就 KeyError → 500** —— 而"新增字段后忘了重跑
    profile"是很常见的情况（开发规则 R3）。``registerInterface()`` 会补齐缺失的
    记录，并按 plone.registry 自身实现**保留已有记录的值**，所以在已配置的站点上
    重跑是安全的。

    与 ``maitux.oauth2.config.ensure_records()`` 同一套路。
    """
    try:
        from plone.registry.interfaces import IRegistry
        from zope.component import queryUtility
        registry = queryUtility(IRegistry)
        if registry is None:
            return []
        missing = [
            name for name in _settings_fields()
            if ("%s.%s" % (REGISTRY_PREFIX, name)) not in registry.records
        ]
        if missing:
            logger.info(
                "maitux.stability: creating %s missing automation "
                "registry record(s): %s", len(missing), sorted(missing))
            registry.registerInterface(
                IStabilityAutomationSettings, prefix=REGISTRY_PREFIX)
        return missing
    except Exception:
        logger.exception(
            "maitux.stability: failed to ensure automation registry records")
        return []


def _record(name, default=None):
    """读一条 registry 记录；没有记录/registry 不可用时返回 default。

    **不抛异常**：设置页还没装（例如 profile 未重跑）时，
    自动登样应当按"安全默认值"工作，而不是让整个方案页面炸掉。
    """
    key = "%s.%s" % (REGISTRY_PREFIX, name)
    try:
        from plone.registry.interfaces import IRegistry
        from zope.component import queryUtility
        registry = queryUtility(IRegistry)
        if registry is None:
            return default
        if key not in registry:
            return default
        value = registry[key]
        return default if value is None else value
    except Exception:
        return default


def get_settings():
    """站点级配置（缺失时给安全默认值）。"""
    return {
        "auto_create_enabled": resolve_bool(
            False, _record("auto_create_enabled", None)),
        "auto_create_time": _record(
            "auto_create_time", DEFAULT_GENERATION_TIME) or DEFAULT_GENERATION_TIME,
        "auto_create_lead_days": resolve_int(
            DEFAULT_LEAD_DAYS, _record("auto_create_lead_days", None)),
        "zero_point_lookback_days": resolve_int(
            DEFAULT_ZERO_POINT_LOOKBACK_DAYS,
            _record("zero_point_lookback_days", None)),
    }


def get_generation_time():
    """站点配置的生成时刻，返回 ``(hour, minute)``。"""
    return parse_generation_time(get_settings().get("auto_create_time"))


def get_lead_days():
    """站点配置的提前天数（0 = 目标日期当天）。"""
    return get_settings().get("auto_create_lead_days")


def get_zero_point_lookback_days():
    """站点配置的零点回溯窗口（天）。"""
    return get_settings().get("zero_point_lookback_days")


def is_site_enabled():
    """站点级自动登样总开关。"""
    return bool(get_settings().get("auto_create_enabled"))


def _first_uid(value):
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    if not value:
        return u""
    return value.strip() if isinstance(value, str) else api.safe_unicode(value).strip()


def _resolve_object(value, portal_type=None):
    uid = _first_uid(value)
    if not api.is_uid(uid):
        return None
    obj = api.get_object(uid, None)
    if obj is None:
        return None
    if portal_type and api.get_portal_type(obj) != portal_type:
        return None
    return obj


def get_plan_template(plan):
    """方案关联的方案模板（``plan_details`` 的默认来源）。"""
    if plan is None:
        return None
    return _resolve_object(getattr(plan, "plan_template", None),
                           portal_type="StabilityPlanTemplate")


def get_row_sample_template(row):
    """**某一个时间点行**选的样品模板（``plan_details[*].sample_template``）。

    2026-09-29 需求订正：样品模板不再维护在方案模板上，而是**逐个时间点**维护 ——
    因为不同时间点要验的东西不一样（例如 0/3 月全项、12 月只做稳定性指标）。
    登样时这一行的客户（兜底）、样品类型与检验项全部由它决定。
    """
    if not isinstance(row, dict):
        return None
    return _resolve_object(row.get("sample_template"),
                           portal_type="SampleTemplate")


def get_sample_template(plan, row=None):
    """取样品模板。

    传 ``row``（明细行）时返回**该时间点**的模板 —— 这是唯一正常的用法；
    不传 ``row`` 时返回 ``None``（方案级没有样品模板了，保留签名只为兼容旧调用）。
    """
    if row is not None:
        return get_row_sample_template(row)
    return None


def get_contact(plan):
    """方案生效的联系人：方案 → 方案模板。"""
    if plan is None:
        return None
    contact = _resolve_object(getattr(plan, "contact", None),
                              portal_type="Contact")
    if contact is not None:
        return contact
    template = get_plan_template(plan)
    if template is None:
        return None
    return _resolve_object(getattr(template, "contact", None),
                           portal_type="Contact")


def get_client(plan, row=None):
    """方案生效的客户 —— **登样时样品登记到哪个委托方名下**。

    三级解析（**需求已确认：客户维护在方案上，登样时自动带过去**）：

    1. ``plan.client``（方案级，日常维护就在这里）；
    2. ``plan.plan_template.client``（方案模板级，建方案时带入初值）；
    3. ``row.sample_template.getClient()``（兜底：该时间点的样品模板
       "挂在客户下"时靠它的归属）。

    为什么必须有个客户：样品（AR）只能建在客户容器下，``Client`` 还是必填字段；
    而自动/批量登样时**没有人在界面上点客户**，只能从配置里取。
    第 3 条兜底是为了兼容"按客户建样品模板"的用法，
    但日常口径是第 1 条 —— 这样 setup 级通用模板也能用。
    """
    if plan is None:
        return None
    client = _resolve_object(getattr(plan, "client", None),
                             portal_type="Client")
    if client is not None:
        return client
    template = get_plan_template(plan)
    if template is not None:
        client = _resolve_object(getattr(template, "client", None),
                                 portal_type="Client")
        if client is not None:
            return client
    sample_template = get_row_sample_template(row)
    if sample_template is None:
        return None
    try:
        return sample_template.getClient()
    except Exception:
        return None


def get_client_source(plan, row=None):
    """客户是从哪一级取到的（``plan`` / ``template`` / ``sample_template`` / ``""``）。

    只用于排查与自检：现场问"这个方案的客户怎么来的"时，一眼能看出是方案上写的、
    模板带过来的，还是靠该时间点样品模板的归属兜底来的。
    """
    if plan is None:
        return u""
    if _resolve_object(getattr(plan, "client", None),
                       portal_type="Client") is not None:
        return u"plan"
    template = get_plan_template(plan)
    if template is not None and _resolve_object(
            getattr(template, "client", None), portal_type="Client") is not None:
        return u"template"
    sample_template = get_row_sample_template(row)
    if sample_template is None:
        return u""
    try:
        if sample_template.getClient() is not None:
            return u"sample_template"
    except Exception:
        return u""
    return u""


def is_plan_enabled(plan):
    """该方案是否启用自动登样。

    三个条件都成立才算启用（阶段 6a 起是**三条**，原来是两条）：

    1. **站点总开关**（``auto_create_enabled``）—— 全站急停；
    2. **方案状态是「进行中」** —— 暂停 / 终止的方案一律不自动登样。
       这是需求里"暂停后到时间不再自动请验"的落点；
    3. **方案开关**（``auto_create_samples``）—— 这个品种要不要。

    ★ 为什么状态这一条加在这里就够了：本函数是自动登样的**唯一闸门**
      （见 samplegeneration.generate_due_samples），
      cron 定时入口、看板「生成到期样品」按钮、看板懒触发三条路径全都过它 ——
      一处改动覆盖三条路径。

    ★ 空状态按「进行中」处理（``plan_status.normalize_state``）：
      存量方案在升级迁移跑到之前也必须照常自动登样，
      否则一次升级就等于把全站方案停掉。
    """
    if plan is None:
        return False
    if not is_site_enabled():
        return False
    if not plan_status.can_auto_generate(get_plan_state(plan)):
        return False
    return resolve_bool(False, getattr(plan, "auto_create_samples", None))


def get_plan_state(plan):
    """方案当前状态（``in_progress`` / ``paused`` / ``terminated``）。

    唯一实现在 ``plan_status``；这里只是给调用方一个"从 automation 拿状态"的
    便利入口（看板、登样页、冻结拦截都从这一层取，避免各处直接 import 两个模块）。
    """
    return plan_status.get_plan_state(plan)


def can_modify_plan(plan):
    """该方案现在还能不能被写（编辑 / 登样 / 关联 / 放置 / 撤销 / 删加行）。

    返回 ``(ok, reason)``；reason 是拒绝原因码（见 ``plan_status.BLOCK_*``）。
    """
    return plan_status.can_modify_plan(get_plan_state(plan))


def window_end(start_time, months, window_days=None):
    """时间点的**窗口结束日**（阶段 6b）= 目标日期 + 窗口天数。

    ★ 唯一实现在 ``sampleautomation.window_end``（纯逻辑、可离线自检）；
      本函数只是把口径**透出到对象层**，理由与 ``get_plan_state`` 相同：
      看板 / 任务镜像这些调用方本来就 import ``automation``，
      让它们各自写一遍 ``target + timedelta(days=n)`` 就是
      "看板说过期、任务上写着另一个结束日"的来源。

    ⚠️ 2026-09-30 真机教训：这个函数**当时漏写了** —— 看板的
      ``automation.window_end(...)`` 一直在，本地源码守卫只核对"调用点写法"
      （assert 源码里有没有这行字符串），于是 AttributeError 直奔生产
      （看板整个 500）。现在除了本函数归位，还加了
      ``tools/checks/check_module_attrs.py``：逐个模块核对"被引用的属性
      到底存不存在"，这类错不再只靠真机发现。

    参数形态与 ``sampleautomation.window_end`` **完全一致**（不是 plan/row）：
    调用方手里就是 ``start_time`` + 行上的 ``timepoint_days`` / ``window_days``。
    """
    return sa.window_end(start_time, months, window_days)


def row_is_expired(plan, row, now=None):
    """这一行时间点现在是否**已过期**（阶段 6b）。

    ★ 唯一判据在 ``sampleautomation.row_is_expired``（纯逻辑、可离线自检）；
      本函数只是把"方案 + 行"喂给它，给各个入口一个**对象级**的统一入口。

    ★ 为什么必须只有这一个入口：过期的判定被**四处**用到 ——
      看板的过期标记（browser/view.py）、登样预览与写库
      （samplegeneration）、零点关联、编辑页的行锁（browser/edit.py）。
      任何一处自己写一遍日期比较，都会出现"看板说过期、登样说能登"
      这类自相矛盾（与 ``can_modify_plan`` 是同一条纪律）。
    """
    if plan is None:
        return False
    if now is None:
        from datetime import datetime
        now = datetime.now()
    try:
        return sa.row_is_expired(getattr(plan, "start_time", None), row, now)
    except Exception:
        logger.exception(
            "Failed to evaluate the expiry of a timepoint of %r", plan)
        return False


def row_is_voided(row):
    """这一行是否**已作废**（阶段 6c 的软删除）。

    ★ 唯一判据在 ``timepoints.is_voided``（纯逻辑：``voided_at`` 非空）；
      本函数只是给调用方一个"从对象层拿"的入口，与 ``row_is_expired``
      并列 —— 界面、写库路径、编辑页行锁都从这里取，
      免得各处自己去读那个标记键（读法不一致 = 有的地方认、有的地方不认）。
    """
    return tp.is_voided(row)


def row_is_locked(plan, row, now=None):
    """这一行在**编辑页**是否"只读"（改值不生效）。

    两类：**已作废**（阶段 6c：已经退出流程的行不该再被改）
    与**已过期**（阶段 6b：需求原文"过期的时间点不允许修改…"）。

    ★ 放在这里而不是各页面各写一遍：编辑页的锁、看板上的标记、
      以及将来的新入口必须给出同一个结论（与 ``can_modify_plan`` 同一条纪律）。
    """
    if row_is_voided(row):
        return True
    return row_is_expired(plan, row, now=now)


def can_void_row(plan, row):
    """对象级作废判据：``(ok, reason_code, detail)``。

    ★ 唯一实现在 ``voiding.can_void_row``（它把样品状态读出来喂给
      ``plan_status.void_precondition``）；这里只是让浏览器层不必同时
      import 两个模块（``voiding`` 会 import ``samplegeneration`` 等一堆东西）。
    """
    try:
        from maitux.stability import voiding
        return voiding.can_void_row(plan, row)
    except Exception:
        logger.exception(
            "Failed to evaluate the void precondition of a timepoint of %r",
            plan)
        return (False, u"void_precondition_error", u"")


def describe(plan, row=None):
    """把生效配置摊平成一份可读摘要（日志、排查、自检都用它）。

    只描述"配置解析结果"，不查样品、不判定到点与否。
    传 ``row``（明细行）时描述的是**该时间点**的配置（样品模板现在是逐行维护的）。
    """
    sample_template = get_row_sample_template(row)
    contact = get_contact(plan)
    client = None
    if sample_template is not None:
        try:
            client = sample_template.getClient()
        except Exception:
            client = None
    return {
        "plan": api.get_id(plan) if plan is not None else u"",
        "site_enabled": is_site_enabled(),
        # 阶段 6a：方案状态（进行中 / 已暂停 / 已终止）。
        # 排查"这个方案为什么没自动登样"时，第一个要看的字段 ——
        # 站点开着、方案开着，但状态是 paused 的话同样一条都不会生成。
        "plan_state": get_plan_state(plan) if plan is not None else u"",
        "plan_modifiable": can_modify_plan(plan)[0] if plan is not None else True,
        "plan_enabled": resolve_bool(
            False, getattr(plan, "auto_create_samples", None)
            if plan is not None else None),
        "enabled": is_plan_enabled(plan),
        "sample_template": api.get_id(sample_template) if sample_template else u"",
        "sample_template_title": api.get_title(sample_template) if sample_template else u"",
        "sample_template_client": api.get_title(client) if client else u"",
        "client": api.get_title(get_client(plan, row)) or u"",
        "client_source": get_client_source(plan, row),
        "contact": api.get_title(contact) if contact else u"",
        "generation_time": u"%02d:%02d" % get_generation_time(),
        "lead_days": get_lead_days(),
        "zero_point_lookback_days": get_zero_point_lookback_days(),
    }


def get_template_sample_type(sample_template):
    """样品模板的样品类型。

    优先取模板自身的 ``sampletype``；没填时退回**分装记录里的第一个样品类型** ——
    平台建样时本身就是按分装记录解析样品类型的（``SampleTemplate.getPartitions()``），
    所以"模板没填、分装填了"的模板是合法可用的，不该被我们的配置检查拦下。
    两者都没有则返回 ``None``。
    """
    if sample_template is None:
        return None
    sample_type = None
    try:
        sample_type = sample_template.getSampleType()
    except Exception:
        sample_type = None
    if sample_type is not None:
        return sample_type

    partitions = []
    try:
        partitions = sample_template.getPartitions() or []
    except Exception:
        partitions = []
    for record in partitions:
        if not isinstance(record, dict):
            continue
        uid = record.get("sampletype")
        if isinstance(uid, (list, tuple)):
            uid = uid[0] if uid else None
        if not uid:
            continue
        obj = api.get_object(uid, None)
        if obj is not None:
            return obj
    return None


def get_template_service_uids(sample_template):
    """样品模板里**启用的**检验项 UID 列表（模板没配检验项时返回空列表）。"""
    if sample_template is None:
        return []
    try:
        return list(sample_template.getServiceUIDs() or [])
    except Exception:
        logger.exception(
            "maitux.stability: failed to read service uids of sample template %r",
            api.get_id(sample_template))
        return []


def contact_belongs_to_other_client(contact, client):
    """联系人是否**属于另一个客户**（属于谁都不属于的"全局联系人"不算）。

    为什么要判：``Contact`` 是 AR 的必填字段，但它的字段校验**不检查是否同属一个客户**
    —— 方案上误选了别家客户的联系人，照样能建出样品，结果是"样品挂在 A 客户名下、
    联系人是 B 客户的人"。这种数据一旦进库，追责与发报告都会出错，所以在这里拦掉。

    平台支持"全局联系人"（父对象不是 Client），那种情况返回 ``False``（放行）——
    那是合法用法，不能一刀切。
    """
    if contact is None or client is None:
        return False
    try:
        parent = contact.getParent()
    except Exception:
        try:
            parent = api.get_parent(contact)
        except Exception:
            parent = None
    if parent is None:
        return False
    if api.get_portal_type(parent) != "Client":
        return False
    return api.get_uid(parent) != api.get_uid(client)


def contact_client_title(contact):
    """联系人**所属客户**的标题（全局联系人 / 取不到返回空串）。"""
    if contact is None:
        return u""
    try:
        parent = contact.getParent()
    except Exception:
        try:
            parent = api.get_parent(contact)
        except Exception:
            parent = None
    if parent is None or api.get_portal_type(parent) != "Client":
        return u""
    # ★ 统一成 unicode：py2 下 `api.get_title` 可能是 utf-8 字节串
    #   （如 "Ŝunnyside"），拿去 `.format()` 拼进 unicode 模板会抛
    #   UnicodeDecodeError —— 提示信息本身炸掉，用户就看不到原因了。
    return api.safe_unicode(api.get_title(parent) or api.get_id(parent) or u"")


def get_own_contact(obj):
    """对象**自身字段**上的联系人（``obj.contact``，不回溯方案模板）。

    与 :func:`get_contact` 的区别：后者是"生效值"（方案 → 方案模板），
    用来判断"这套配置能不能登样"；本函数只取对象自己写的那个值，
    用在**写操作**上（清掉错配的联系人不能去改模板）。
    """
    if obj is None:
        return None
    return _resolve_object(getattr(obj, "contact", None), portal_type="Contact")


def drop_mismatched_contact(obj):
    """客户与（自身字段上的）联系人不是同一家时，把联系人清掉。

    为什么要有这个动作：``Contact`` 的下拉是"全站联系人"，
    而客户是在同一张表单里另选的 —— 很容易出现"A 客户 + B 家联系人"的组合。
    这种组合一旦落库，登样会被 :func:`get_generation_config` 拦下
    （``PROBLEM_CONTACT_OTHER_CLIENT``），用户只能靠报错才发现自己选错了。
    所以在**保存时**就把错配值清掉并提示，别让错误配置留在库里。

    返回 ``(联系人标题, 联系人所属客户标题, 方案客户标题)``；
    没有可清的就返回 ``None``（调用方据此决定要不要提示）。
    """
    contact = get_own_contact(obj)
    if contact is None:
        return None
    client = get_client(obj)
    if not contact_belongs_to_other_client(contact, client):
        return None

    removed = (
        api.safe_unicode(api.get_title(contact) or api.get_id(contact) or u""),
        contact_client_title(contact),
        api.safe_unicode(api.get_title(client) or api.get_id(client) or u""),
    )
    try:
        obj.contact = None
    except Exception:
        logger.exception(
            "Failed to clear the mismatching contact of %s", api.get_path(obj))
        return None
    return removed


def get_generation_config(plan, row=None):
    """解析"给这一行（时间点）登样"所需的全部对象与问题清单。

    返回一个 dict（**不抛异常**：配置不全时把原因攒进 ``problems``，
    由调用方决定怎么提示 —— 页面要能打开并说明"缺什么"，
    而不是给用户一个 500）：

    ``sample_template`` / ``client`` / ``contact`` / ``sample_type`` / ``service_uids``
        解析出来的对象与取值（缺失为 ``None`` / 空列表）；
    ``problems``
        原因码列表（``sampleautomation.PROBLEM_*``），非空即"这套配置登不了样"；
    ``warnings``
        不阻断但需要提示的原因码列表（目前只有"联系人属于其它客户"）。

    ★ 配置链路（2026-09-29 需求订正）：
    **样品模板逐个时间点维护在明细行上**（``row["sample_template"]``）——
    不同时间点要验的东西不一样，所以样品类型与检验项都按该行的模板算；
    行上原有的「检验标准 / 分析套餐」已删除。
    客户仍在方案上（方案 → 方案模板 → 该行模板自身归属兜底）。
    """
    result = {
        "sample_template": None,
        "sample_template_title": u"",
        "client": None,
        "client_title": u"",
        "client_source": u"",
        "contact": None,
        "contact_title": u"",
        "sample_type": None,
        "sample_type_title": u"",
        "service_uids": [],
        "problems": [],
        "warnings": [],
        # 逐条问题的**参数**（给"带名字的报错文案"用）：code -> {占位符: 值}。
        # 例：PROBLEM_CONTACT_OTHER_CLIENT ->
        #     {"contact": "contact-7", "contact_client": "Ŝunnyside",
        #      "client": "Klaymore"}
        "problem_data": {},
    }

    sample_template = get_row_sample_template(row)
    if sample_template is None:
        # ⚠️ 只有**传了行**时才报"缺样品模板"：样品模板是行级配置，
        #    而本函数在 `row=None` 时被用来取"方案级配置"（登样页的方案信息卡），
        #    那种场景下报"该时间点没有选择样品模板"是驴唇不对马嘴。
        if row is not None:
            result["problems"].append(PROBLEM_NO_SAMPLE_TEMPLATE)
    else:
        result["sample_template"] = sample_template
        result["sample_template_title"] = (api.get_title(sample_template)
                                           or api.get_id(sample_template))

    # 客户：方案 -> 方案模板 -> 该行样品模板归属（见 get_client 的说明）
    client = get_client(plan, row)
    result["client_source"] = get_client_source(plan, row)
    if client is None:
        result["problems"].append(PROBLEM_NO_CLIENT)
    else:
        result["client"] = client
        result["client_title"] = api.get_title(client) or api.get_id(client)
        # 该行的样品模板自己是"客户级"的、且与方案客户不是同一家 —— 这是配置矛盾：
        # 用 A 客户的样品模板去做 B 客户的样品，平台不拦（Template 字段不校验归属），
        # 但数据会串（样品挂 A、检验项来自 B 的模板），所以在这里拦下来。
        if sample_template is not None:
            try:
                template_client = sample_template.getClient()
            except Exception:
                template_client = None
            if template_client is not None and \
                    api.get_uid(template_client) != api.get_uid(client):
                result["problems"].append(PROBLEM_CLIENT_TEMPLATE_MISMATCH)
                result["problem_data"][PROBLEM_CLIENT_TEMPLATE_MISMATCH] = {
                    "template": api.safe_unicode(
                        result["sample_template_title"] or u""),
                    "template_client": api.safe_unicode(
                        api.get_title(template_client)
                        or api.get_id(template_client) or u""),
                    "client": api.safe_unicode(result["client_title"] or u""),
                }

    contact = get_contact(plan)
    if contact is None:
        result["problems"].append(PROBLEM_NO_CONTACT)
    else:
        result["contact"] = contact
        result["contact_title"] = api.get_title(contact) or api.get_id(contact)
        if contact_belongs_to_other_client(contact, client):
            result["problems"].append(PROBLEM_CONTACT_OTHER_CLIENT)
            # 报错要能直接说清"错在哪"：带上联系人与两家客户的名字
            # （只说"联系人与客户不是同一家"，用户还得自己去翻是谁家）。
            result["problem_data"][PROBLEM_CONTACT_OTHER_CLIENT] = {
                "contact": api.safe_unicode(result["contact_title"] or u""),
                "contact_client": contact_client_title(contact),
                "client": api.safe_unicode(result["client_title"] or u""),
            }

    if sample_template is not None:
        sample_type = get_template_sample_type(sample_template)
        if sample_type is None:
            result["problems"].append(PROBLEM_NO_SAMPLE_TYPE)
        else:
            result["sample_type"] = sample_type
            result["sample_type_title"] = (api.get_title(sample_type)
                                           or api.get_id(sample_type))

        service_uids = get_template_service_uids(sample_template)
        if not service_uids:
            # 没有检验项也能建出样品，但那种"空样品"在稳定性研究里没有意义，
            # 而且现场很难看出问题出在模板上 —— 直接按配置错误拦下。
            result["problems"].append(PROBLEM_NO_SERVICES)
        result["service_uids"] = service_uids

    return result
