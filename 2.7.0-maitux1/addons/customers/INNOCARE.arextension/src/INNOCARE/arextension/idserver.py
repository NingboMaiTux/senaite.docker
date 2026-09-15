# -*- coding: utf-8 -*-
"""ID Server variables adapter for Analysis Request.

URS-025 样品编号 = <前缀><类型简码><YYMMDD><序号>，例如 BA260724001。
本适配器为 ID Server 提供两个变量：

``deptCode``（部门简码，历史变量，保持不变）
    通过 AR 的检测项目（Analysis -> Department）关联到部门，
    取部门的 ``department_id``（Department ID）作为简码，
    未配置时回退到部门对象 ID（getId）。

``labId``（实验室编号）
    取 Laboratory（Setup -> Laboratory Information）上的 ``Lab ID`` 字段，
    该字段由 add-on ``INNOCARE.labid`` 提供；未配置时回退为 ``deptCode``，
    避免编号前缀整体丢失。

模板配置（Setup -> ID Formatting，AnalysisRequest 行）二选一：
    form:          {deptCode}{sampleType}{yymmdd}{seq:03d}     # 原规则
    form:          {labId}{sampleType}{yymmdd}{seq:03d}        # 新规则
    sequence_type: generated
    split_length:  3
"""
import logging

from bika.lims import api
from bika.lims.interfaces import IAnalysisRequest
from senaite.core.interfaces import IIdServerVariables
from zope.component import adapter
from zope.interface import implementer

logger = logging.getLogger("INNOCARE.arextension")

# 每个进程只提示一次"Lab ID 未配置"，避免每条样品都刷日志
_warned_missing_lab_id = [False]


@implementer(IIdServerVariables)
@adapter(IAnalysisRequest)
class ARIdServerVariables(object):
    """Provides extra ID Server variables for AnalysisRequest
    """

    def __init__(self, context):
        self.context = context

    def get_variables(self, **kw):
        dept_code = self._get_department_code()
        lab_id = self._get_lab_id()
        if not lab_id:
            # 未配置 Lab ID：回退部门简码，避免编号前缀整体丢失
            if not _warned_missing_lab_id[0]:
                _warned_missing_lab_id[0] = True
                logger.warn(
                    "ARIdServerVariables: Laboratory has no 'Lab ID', "
                    "falling back to the department code ('%s'). "
                    "Set it in Setup -> Laboratory Information.", dept_code)
            lab_id = dept_code
        return {
            "deptCode": dept_code,
            "labId": lab_id,
        }

    def _get_lab_id(self):
        """实验室编号：取 Laboratory 对象的 ``lab_id``（INNOCARE.labid 提供）。

        Laboratory 是 ``bika_setup/laboratory`` 下的单例，本身是 Dexterity 内容
        （``senaite.core.content.laboratory``），字段值直接存在对象属性上。
        取不到对象或未填写时返回空串，由调用方决定回退策略。
        """
        try:
            setup = api.get_senaite_setup()
            laboratory = setup.get("laboratory") if setup is not None else None
            if laboratory is None:
                return u""
            value = getattr(laboratory, "lab_id", None)
            if value is None:
                return u""
            return api.safe_unicode(value).strip()
        except Exception as exc:
            logger.warn("ARIdServerVariables: cannot read Lab ID: %s", exc)
            return u""

    def _get_department_code(self):
        """部门简码：取第一个关联部门（经检测项目 -> Department）。

        注意：不能走 getAnalyses()（目录查询）。AR 创建时先以临时 ID
        建对象，其分析子对象在编号生成（renameAfterCreation）时尚未写入
        senaite_catalog_analysis（临时对象被 CatalogMultiplexProcessor
        跳过索引），目录查询为空会导致部门取不到。直接遍历 AR 容器内的
        分析对象即可，与目录状态无关。
        """
        code = u""
        try:
            for analysis in self.context.objectValues(spec="Analysis"):
                department = analysis.getDepartment()
                if department is None:
                    continue
                getter = getattr(department, "getDepartmentID", None)
                if callable(getter):
                    code = getter() or u""
                if not code:
                    code = department.getId() or u""
                if code:
                    break
        except Exception:
            code = u""
        return code
