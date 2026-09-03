# -*- coding: utf-8 -*-
"""maitux.setupmenu - Role-based Setup menu management for SENAITE

- 用户端 Setup 界面 ``@@maitux-setup``：与 ``@@lims-setup`` 同风格，
  但菜单按当前用户角色过滤（管理员始终可见全部）。
- 管理界面 ``@@maitux-setupmenu``：表格配置每个菜单的启用状态与允许角色，
  入口位于 Site Setup（Menu Management）。
- Addon 菜单自动识别：内容建在 setup/bika_setup 文件夹，或实现
  ``IMenuEntryProvider`` 注册，即可自动进入管理界面，无需二次开发。
"""
