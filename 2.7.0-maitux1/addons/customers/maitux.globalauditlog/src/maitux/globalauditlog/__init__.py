# -*- coding: utf-8 -*-
"""maitux.globalauditlog

把 SENAITE 设置里的「启用全局审计日志」钉成**始终开启**，并把它从
设置页面上隐藏掉。

模块级常量集中放在这里，是为了让 `browser/senaitesetup.py`（前端那一侧）
和 `subscribers.py`（服务端那一侧）以及测试引用**同一个**字段名 ——
字段名写错是本环境最典型的静默失效（R9）：表单里找不到控件，
`add_hide_field` / `add_update_field` 直接 `continue`，不报任何错。
"""

#: 分发名 / 目录名 / 包名三者一致（R5c）
PROJECTNAME = "maitux.globalauditlog"

#: 安装判定用的 profile id，供「本包装在这个站点上了吗」的运行时门控使用
PROFILE_ID = "%s:default" % PROJECTNAME

#: senaite.core 里「启用全局审计日志」的 schema 字段名
#: （senaite/core/content/senaitesetup.py 的 Setup.enable_global_auditlog）
AUDITLOG_FIELD_NAME = "enable_global_auditlog"

#: 该字段在编辑表单里的控件名。前缀 `form.widgets.` 与 core 自己的
#: browser/form/adapters/senaitesetup.py 一致，控件名同时出现在模板的
#: `data-fieldname` 与 `name=` 上（见 dexterity/templates/widget.pt）。
AUDITLOG_FORM_FIELD = "form.widgets." + AUDITLOG_FIELD_NAME
