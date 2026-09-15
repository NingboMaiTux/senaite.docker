# -*- coding: utf-8 -*-
"""通用工具：接收人显示名。"""

from bika.lims import api


def get_received_by_fullname(sample):
    """返回样品的接收人显示名（用户全名，取不到用户时回退登录名）。

    SENAITE 把「接收人」记在样品的工作流历史里 ——
    `AnalysisRequest.getReceivedBy()` 返回的是登录名（actor），
    界面上要显示全名，这里做一次转换。

    :param sample: 样品（AnalysisRequest）对象
    :returns: 接收人全名，未接收时返回空字符串
    """
    if sample is None:
        return ""

    user_id = sample.getReceivedBy()
    if not user_id:
        return ""

    return api.get_user_fullname(user_id) or user_id
