# -*- coding: utf-8 -*-

from plone.supermodel import model
from senaite.core.interfaces import ISenaiteCore
from zope import schema
from zope.interface import Interface
from zope.publisher.interfaces.browser import IDefaultBrowserLayer

from maitux.glossary import _


class IGlossaryLayer(ISenaiteCore, IDefaultBrowserLayer):
    """Browser layer for maitux.glossary.

    The package registers nothing against foreign (senaite/bika/plone)
    interfaces, so this layer is not used for gating (rules R14). It is
    declared to keep the door open should such a registration be needed later.
    """


class IGlossaryEntries(Interface):
    """Marker interface for the middle table container.
    """


class IGlossaryEntry(Interface):
    """Marker interface for one row of the middle table.

    A row is one combination ``(analysis_keyword, calc_keyword)``.
    """


class IGlossaryEntriesSchema(model.Schema):
    """Schema for the middle table container. Intentionally empty.
    """


class IGlossaryEntrySchema(model.Schema):
    """Schema for one middle table row.

    注意：**没有** ``translation_status`` 字段 —— 原先的"翻译进度"列已按需求移除。
    ``zh`` / ``en`` 都**默认为空**，由人工填写；同步不会从站点回填中文名。
    """

    analysis_keyword = schema.TextLine(
        title=_(u"Analysis Keyword"),
        description=_(
            u"Keyword of the Analysis Service this row belongs to. "
            u"Part of the row key; written by the sync and never changed."
        ),
        required=True,
    )

    calc_keyword = schema.TextLine(
        title=_(u"calc keyword"),
        description=_(
            u"Keyword of the Calculation interim field (the 'Keyword' column "
            u"on the Calculation edit page). Part of the row key."
        ),
        required=True,
    )

    category = schema.TextLine(
        title=_(u"Analysis category"),
        description=_(u"Analysis category of the Analysis Service."),
        required=False,
    )

    zh = schema.TextLine(
        title=_(u"zh"),
        description=_(
            u"Chinese name of the formula field. Empty by default - filled "
            u"in by hand. Editing it applies to every row of the same calc "
            u"keyword."
        ),
        required=False,
    )

    en = schema.TextLine(
        title=_(u"en"),
        description=_(
            u"English name of the formula field. Empty by default - filled "
            u"in by hand. Editing it applies to every row of the same calc "
            u"keyword."
        ),
        required=False,
    )

    sync_state = schema.Choice(
        title=_(u"State"),
        description=_(
            u"Whether the combination still exists on the site. Maintained "
            u"by the sync; the only field the sync is allowed to change on an "
            u"existing row."
        ),
        vocabulary=u"maitux.glossary.vocabularies.SyncStates",
        required=True,
        default=u"active",
    )

    first_seen = schema.Datetime(
        title=_(u"First seen"),
        description=_(u"When the sync appended this row."),
        required=False,
    )

    state_changed_on = schema.Datetime(
        title=_(u"State changed on"),
        description=_(
            u"When the sync set the current state. Written only when the row "
            u"is created or its state changes - existing rows are never "
            u"touched otherwise."
        ),
        required=False,
    )

    last_sync_by = schema.TextLine(
        title=_(u"Last sync by"),
        description=_(
            u"Who triggered the sync that wrote or re-stated this row. The "
            u"write itself is performed with elevated privileges, so this is "
            u"the only attribution available."
        ),
        required=False,
    )

    note = schema.Text(
        title=_(u"Note"),
        required=False,
    )

    # ------------------------------------------------------------------
    # 报告导入映射（消费方：maitux.instrument_acquisition 的报告落位）
    #
    # ★ 这 7 列是**人工配置**、以本页为唯一权威；同步只写 sync_state 与
    #   新行的种子字段，**不会**碰它们（见 sync/core.py 的 R2）。
    # ★ 编辑语义 = **只写当前行**（不能像 zh/en 那样按 calc keyword 批量）：
    #   同一个 calc keyword 在不同分析上来源不同（实测 `g_rt` 有 8 行，
    #   分别来自 SYS / 供试品 / 稳定性 / 破坏样品），批量写必然错。
    # ------------------------------------------------------------------

    acq_enabled = schema.Bool(
        title=_(u"报告导入目标位"),
        description=_(
            u"勾选 = 该公式字段是仪器报告导入的落位目标位。只有勾选的行会被"
            u"采集侧读取；未勾选一律不写（宁缺勿错）。"
        ),
        required=False,
        default=False,
    )

    acq_source_sample = schema.TextLine(
        title=_(u"来源 SampleName"),
        description=_(
            u"报告正文里供数的 SampleName（命名规范 §4 受控词表），如 "
            u"`STD-1` / `STD-2` / `SYS`。解析器只认正文里的 SampleName，"
            u"不认文件名。**峰级槽位模式下写逗号分隔清单**（与「行槽位」"
            u"按位置一一对应、必须等长），如 "
            u"`ACC-100%-SPIKED-1(T0), ACC-100%-SPIKED-2`。"
        ),
        required=False,
    )

    acq_pick = schema.Choice(
        title=_(u"取值规则"),
        description=_(
            u"该针怎么取值。受控词表，与采集侧 report_targets.PICK_RULES 一一"
            u"对应；写错会导致「没落位」或「写错值」。"
        ),
        vocabulary=u"maitux.glossary.vocabularies.AcquisitionPick",
        required=False,
    )

    acq_decimals = schema.Choice(
        title=_(u"写法"),
        description=_(
            u"按站点现值保留几位小数（空 = 原样）。**必须以站点现值写法为准**："
            u"实测 `imp_sep_res_before` 存的是 `5.0`，写成 `5` 会与现值不一致。"
        ),
        vocabulary=u"maitux.glossary.vocabularies.AcquisitionDecimals",
        required=False,
    )

    acq_length = schema.Int(
        title=_(u"期望长度"),
        description=_(
            u"该字段应有的长度（针数或峰数），来自 M0 映射表的实测长度。"
            u"报告给的长度不符 → 跳过该目标位并点名（防「单针报告覆盖完整数组」）。"
            u"0 = 不校验。"
        ),
        required=False,
        default=0,
    )

    acq_injection = schema.Int(
        title=_(u"第 N 针"),
        description=_(
            u"只取该来源的第 N 针（按 Injection # 排序）。M0 §6.3 实测确认"
            u"`imp_loq1_area`…`imp_loq6_area` 是「第 N 针的 6 峰面积」这种"
            u"**针优先**语义。0 / 空 = 该来源的全部针按序拼接。"
        ),
        required=False,
        default=0,
    )

    acq_peaks = schema.Int(
        title=_(u"取前 N 峰"),
        description=_(
            u"每针只取**前 N 个峰**（按峰序）。用于同一份报告喂两个宽度不同的"
            u"目标位：实测 `imp_linearity` 每列 3 值 = 报告 6 峰的前 3 峰，"
            u"而 `imp_linearity_shared` 每列 6 值 = 全 6 峰。0 / 空 = 全部峰。"
        ),
        required=False,
        default=0,
    )

    acq_rt = schema.Float(
        title=_(u"目标 RT(min)"),
        description=_(
            u"只保留 **RT 落在「目标 RT ± 0.5 min」窗口内**的峰（窗口容差是"
            u"采集侧的工程常量，见 report_import.RT_MATCH_TOLERANCE）。"
            u"用于「按峰位置挑峰」，实测 `imp_rec_spec.g_area` = 各进样里"
            u"RT≈24.3 的峰（指定杂质 Z7）面积 → 12/12 逐值一致。"
            u"0 / 空 = 不按 RT 筛选。"
        ),
        required=False,
        default=0.0,
    )

    acq_peak_indexes = schema.TextLine(
        title=_(u"峰序号清单"),
        description=_(
            u"只保留这些**峰序号**（按报告里的峰序，1 起，逗号分隔），"
            u"如 `3,6,7,8,15,16`。用于「从整列峰里挑一组峰」（现有维度表达不了），"
            u"实测 `imp_specificity` 取自 SYS 16 峰里的第 3/6/7/8/15/16 个。"
            u"空 = 不按序号筛选。"
        ),
        required=False,
    )

    acq_row_key = schema.TextLine(
        title=_(u"行键列"),
        description=_(
            u"**峰级字段（行同步）用**：峰级数组的行键列名，如 `g_sample_id` / "
            u"`imp_deg_id` / `imp_qc_point`。峰级数组是「扁平列表 + 行键重复标号」，"
            u"落位时用它定出目标槽位的**连续块**（布局的唯一权威）。"
            u"与「行槽位」**必须成对填写**。"
        ),
        required=False,
    )

    acq_slot = schema.TextLine(
        title=_(u"行槽位"),
        description=_(
            u"**峰级字段（行同步）用**：本次落位要写的行键取值，**逗号分隔清单**，"
            u"与「来源 SampleName」按位置一一对应（如来源 6 个、槽位写 "
            u"`1,2,3,4,5,6`）。每个槽位在行键列里的块长必须**恰好等于**该来源取到的"
            u"值的个数，不一致就跳过该槽位（不覆盖）。空 = 整列语义。"
        ),
        required=False,
    )

    acq_drop_rt = schema.TextLine(
        title=_(u"排除 RT"),
        description=_(
            u"剔除 RT 落在任一值 ± 0.5 min 内的峰（逗号分隔，如 `10.12,47.48`）。"
            u"这是**站点自己的报告阈值口径**：实测同一针在站点不同分析里存的峰表不同"
            u"（`imp_chrom` 比报告少 RT 47.48、`imp_degradation` 少 RT 10.12，"
            u"而 `imp_repeat` 一个都不少）。空 = 不剔除。"
        ),
        required=False,
    )
