# -*- coding: utf-8 -*-
"""SENAITE 设置编辑表单适配器：隐藏「启用全局审计日志」并把它固定为勾选

这个适配器是 `senaite.core.browser.form.ajax.FormView` 的服务端一半。
编辑表单加载完成后，前端 `editform.js` 会 POST 到
`<设置页>/ajax_form/initialized`，本类返回的指令由前端 `update_form()`
执行：

    hide    -> 给控件所在的 `.field` 包装加 d-none（Bootstrap 的 display:none）
    updates -> 找到同名控件并写值，复选框走的是 `field.checked = value`

两件事都必须做，而且理由是分开的：

* `hide` 满足「隐藏起来」—— 注意它只是 CSS 隐藏，控件仍然留在表单里、
  仍会被提交，这正是我们要的（下面 `updates` 依赖它）。
* `updates` 保证「默认勾选」在**保存时**成立。控件是勾选的，提交值才是
  z3c.form 认的 token（`selected`），否则这个布尔字段会以未勾选提交，
  等于把审计日志关掉。
"""

from maitux.globalauditlog import AUDITLOG_FORM_FIELD
from senaite.core.browser.form.adapters.senaitesetup import (
    EditForm as BaseEditForm,
)


class EditForm(BaseEditForm):
    """继承 core 的设置表单适配器，只追加「审计日志」这一项处理

    R6：覆盖原生组件时优先「继承 + 只改必要方法」，不整体复制实现。
    core 在这个类里还处理了

      * `enable_rejection_workflow` -> `rejection_reasons` 的显示/隐藏联动
      * `restrict_worksheet_users_access` -> `restrict_worksheet_management`
        的只读/勾选联动（含那个「readonly 不能再附带值更新」的坑）

    这些行为必须原样保留，所以只覆写 initialized / modified 并在里面
    先调**基类实现**（显式两参写法，本环境是 Python 2.7）——
    一旦将来 core 升级这两条联动，本包自动跟进。
    """

    def initialized(self, data):
        """表单加载完成：隐藏并勾选审计日志字段"""
        data = super(EditForm, self).initialized(data)
        self.conceal_auditlog_field()
        return data

    def modified(self, data):
        """某个字段被改动

        core 用 `data["name"]` 判断改的是哪个字段（前端已经剥掉
        `:converter` 后缀，见 editform.js 的 `get_field_name`）。
        字段被隐藏后用户在界面上够不到它，这里再拦一道：万一有脚本或
        扩展把它改回未勾选，立刻推回勾选态。

        ★ `name` 必须在调基类实现**之前**读出来：基类的返回值不是
          传进去的那份 payload，而是 `self.data`（要发给前端的指令字典）。
          写反了不报错，只是判断永远不成立 —— 又一次静默失效。
        """
        name = data.get("name")
        data = super(EditForm, self).modified(data)
        if name == AUDITLOG_FORM_FIELD:
            self.conceal_auditlog_field()
        return data

    def conceal_auditlog_field(self):
        """把审计日志字段设为「隐藏 + 勾选」

        两个指令都带上；前端 `update_form()` 先跑 hide 再跑 updates，
        顺序对我们没有影响 —— hide 只加 CSS 类，不碰控件本身。
        """
        # 隐藏：控件保留在表单里，仍参与提交（这是刻意的，见模块 docstring）
        self.add_hide_field(AUDITLOG_FORM_FIELD)
        # 勾选：布尔控件要的是 True，不是字符串 "selected"
        self.add_update_field(AUDITLOG_FORM_FIELD, True)
