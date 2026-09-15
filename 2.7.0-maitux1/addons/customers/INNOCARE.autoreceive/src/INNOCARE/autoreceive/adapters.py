# -*- coding: utf-8 -*-
"""样品列表：新增「接收人」列。

用 senaite.app.listing 官方提供的 `IListingViewAdapter` 订阅者扩展点，
不覆盖 SamplesView（避免 ZCML 加载顺序 / 权限注册问题）。

★ R14：本订阅者的签名是 `(view, context)` —— **不含 request**，
  ZCML 里无处插 `layer=`，而 `package-includes/` 的注册是全局的。
  所以必须在 `before_render()` 开头判本包 browser layer，
  否则没装本 addon 的站点也会多出一列。

★ review_states 里的 `columns` 是 `__init__` 时对 `self.columns.keys()`
  取的**快照（list）**，只改 `view.columns` 不会让新列出现在页签里，
  两处都要插。
"""

from collections import OrderedDict

from bika.lims import api
from senaite.app.listing.interfaces import IListingViewAdapter
from zope.interface import implements

from INNOCARE.autoreceive import _
from INNOCARE.autoreceive.interfaces import IAutoReceiveLayer
from INNOCARE.autoreceive.utils import get_received_by_fullname

# 新增列的 id（列 id 即取值时用的 key，无 catalog 索引）
COLUMN_ID = "ReceivedByName"
# 插在「接收时间」列后面；这一列是所有样品列表都有的列
AFTER_COLUMN_ID = "getDateReceived"


class SamplesReceivedByAdapter(object):
    """给样品列表注入「接收人」列"""

    implements(IListingViewAdapter)

    def __init__(self, view, context):
        self.view = view
        self.context = context

    def is_addon_installed(self):
        """本 addon 的 browser layer 是否在当前站点生效"""
        request = getattr(self.view, "request", None)
        if request is None:
            request = getattr(self.context, "REQUEST", None)
        if request is None:
            return False
        return IAutoReceiveLayer.providedBy(request)

    def before_render(self):
        # ★ 没装本 addon 的站点：什么都不注入（见模块 docstring / R14）
        if not self.is_addon_installed():
            return

        columns = getattr(self.view, "columns", None)
        if not isinstance(columns, dict):
            return
        if COLUMN_ID in columns or AFTER_COLUMN_ID not in columns:
            return

        # 1) 把新列插到「接收时间」之后
        new_columns = OrderedDict()
        for key, value in columns.items():
            new_columns[key] = value
            if key == AFTER_COLUMN_ID:
                new_columns[COLUMN_ID] = {
                    "title": _(u"Received By"),
                    # 无索引，不支持排序；可在列设置里开关（默认显示）
                    "sortable": False,
                    "toggle": True,
                }
        self.view.columns = new_columns

        # 2) 同步各页签的列快照
        for review_state in getattr(self.view, "review_states", []):
            names = review_state.get("columns")
            if not isinstance(names, list) or COLUMN_ID in names:
                continue
            try:
                index = names.index(AFTER_COLUMN_ID)
            except ValueError:
                continue
            names.insert(index + 1, COLUMN_ID)

    def folder_item(self, obj, item, index):
        columns = getattr(self.view, "columns", None)
        if not columns or COLUMN_ID not in columns:
            return item

        # 注意：`getReceivedBy` 只是 sample catalog 的**索引**、不是 metadata 列，
        # brain 上取不到值，只能唤醒对象来读工作流历史（核心列表自己也对
        # Client / Batch 做同类按行取对象的操作）。
        sample = api.get_object(obj, None)
        if sample is None:
            return item

        item[COLUMN_ID] = get_received_by_fullname(sample)
        return item
