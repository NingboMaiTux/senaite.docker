# -*- coding: utf-8 -*-
from maitux.roles import _

PROJECTNAME = "maitux.roles"
PROFILE_ID = "profile-%s:default" % PROJECTNAME

# 基础权限：所有业务管理类角色共享的 LabManager 级别子集
BASE_PERMISSIONS = [
    "View",
    "Access contents information",
    "Add portal content",
    "Modify portal content",
    "senaite.core: View Navigation",
    "senaite.core: View Dashboard",
    "senaite.core: Manage Bika",
    "senaite.core: View Results",
]

# 角色定义
#   role_id       : Plone 角色 ID（= 组 ID，英文去空格）
#   title_msg     : 界面显示名（i18n Message，msgid 为英文全名）
#   permissions   : 该角色预设的权限（增量授予，不覆盖已有授权）
#   inherit_labmanager : 是否直接继承 LabManager 的全部权限
ROLE_DEFINITIONS = [
    {
        "role_id": "MethodAdministrator",
        "title_msg": _(u"Method Administrator", default=u"Method Administrator"),
        "permissions": BASE_PERMISSIONS + [
            "senaite.core: Add Method",
            "senaite.core: Manage Reference",
        ],
        "inherit_labmanager": False,
    },
    {
        "role_id": "InstrumentAdministrator",
        "title_msg": _(u"Instrument Administrator", default=u"Instrument Administrator"),
        "permissions": BASE_PERMISSIONS + [
            "senaite.core: Add Instrument",
            "senaite.core: Add InstrumentLocation",
            "senaite.core: Add InstrumentType",
            "senaite.core: Import Instrument Results",
        ],
        "inherit_labmanager": False,
    },
    {
        "role_id": "InventoryAdministrator",
        "title_msg": _(u"Inventory Administrator", default=u"Inventory Administrator"),
        "permissions": BASE_PERMISSIONS + [
            "senaite.core: Add StorageLocation",
            "senaite.core: Add Supplier",
        ],
        "inherit_labmanager": False,
    },
    {
        "role_id": "StabilityAdministrator",
        "title_msg": _(u"Stability Administrator", default=u"Stability Administrator"),
        "permissions": BASE_PERMISSIONS + [
            "maitux.stability: Add Stability Plan Template",
            "senaite.core: Add StorageLocation",
        ],
        "inherit_labmanager": False,
    },
    {
        "role_id": "StabilityInventoryAdministrator",
        "title_msg": _(u"Stability-Inventory Administrator",
                       default=u"Stability-Inventory Administrator"),
        "permissions": BASE_PERMISSIONS + [
            "maitux.stability: Add Stability Plan Template",
            "senaite.core: Add StorageLocation",
            "senaite.core: Add Supplier",
        ],
        "inherit_labmanager": False,
    },
    {
        "role_id": "BusinessSystemAdministrator",
        "title_msg": _(u"Business System Administrator",
                       default=u"Business System Administrator"),
        "permissions": BASE_PERMISSIONS + [
            "senaite.core: Manage Analysis Requests",
            "senaite.core: Manage Worksheets",
            "senaite.core: Manage Invoices",
            "senaite.core: Manage Reference",
        ],
        "inherit_labmanager": True,
    },
    {
        "role_id": "ITSystemEngineer",
        "title_msg": _(u"IT System Engineer", default=u"IT System Engineer"),
        "permissions": BASE_PERMISSIONS + [
            "Manage users",
            "Manage groups",
            "Manage portal",
            "senaite.core: Access JSON API",
            "senaite.core: Manage Login Details",
        ],
        "inherit_labmanager": False,
    },
    {
        "role_id": "Verifier",
        "title_msg": _(u"Verifier", default=u"Verifier"),
        "permissions": BASE_PERMISSIONS + [
            "senaite.core: View Results",
            "senaite.core: Transition: Verify",
        ],
        "inherit_labmanager": False,
    },
    {
        "role_id": "LabClerk",
        "title_msg": _(u"Lab Clerk", default=u"Lab Clerk"),
        "permissions": BASE_PERMISSIONS + [
            "senaite.core: Manage Analysis Requests",
            "senaite.core: Manage Worksheets",
        ],
        "inherit_labmanager": False,
    },
]
