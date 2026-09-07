# -*- coding: utf-8 -*-
"""模块级接口定义

浏览器层继承 maitux.instrument_acquisition 的浏览器层
（其又继承 maitux.reviewerassignment / senaite.core 的层），
保证本模块对 manage_results 的覆盖优先级最高：

    ISenaiteCore
      └─ IReviewerAssignmentLayer
           └─ IInstrumentAcquisitionLayer
                └─ IWorksheetFieldsLayer   ← 本模块
"""

from maitux.instrument_acquisition.interfaces import (
    IInstrumentAcquisitionLayer,
)


class IWorksheetFieldsLayer(IInstrumentAcquisitionLayer):
    """maitux.worksheetfields 浏览器层
    """
