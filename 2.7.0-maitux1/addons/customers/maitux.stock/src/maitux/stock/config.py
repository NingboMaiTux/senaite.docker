# -*- coding: utf-8 -*-
from Products.CMFCore.permissions import AddPortalContent
from Products.CMFCore.permissions import ManagePortal

PROJECTNAME = "maitux.stock"

ADD_CONTENT_PERMISSIONS = {
    'StockItem': AddPortalContent,
    'StockFolder': ManagePortal,
}

# ---------------------------------------------------------------------------
# 目录结构 ID（setuphandlers / 视图共用，避免多处硬编码）
# ---------------------------------------------------------------------------
STOCK_MANAGER_ID = "stockmanager"
USAGE_REQUESTS_ID = "usage_requests"

# ---------------------------------------------------------------------------
# 领用申请审批
# ---------------------------------------------------------------------------
# 允许审批领用申请的角色白名单（已启用）。
#
# 说明与取舍：
#   * InventoryAdministrator —— 库存管理员。语义最贴合"复核库存领用"，
#     该角色由 maitux.roles 定义，并已自动创建同名组（用户加入该组即获得角色）。
#   * LabManager —— 实验室主管。作为兜底放在这里，避免"白名单里一个人都没有"
#     导致需审批的库存彻底无法领用（那属于运维事故，比范围略宽更糟）。
#
# 若现场要求"只能由库存管理员审批"，把 LabManager 去掉即可：
#     CONSUME_COUNTERSIGN_ROLES = (u"InventoryAdministrator",)
#
# 注意：
#   1) 白名单为空 () 时表示**不限制角色**（此时仍强制"审批人不能是申请人"）。
#   2) 无论白名单怎么配，**申请人都不能审批自己的申请**（守卫硬约束）。
CONSUME_COUNTERSIGN_ROLES = (
    u"LabManager",
    u"InventoryAdministrator",
)

# 需要电子签名的库存，领用时自动生成的申请单类型与工作流
USAGE_REQUEST_TYPE = "StockUsageRequest"
USAGE_REQUEST_WORKFLOW = "senaite_stockusagerequest_workflow"

# 哪些迁移必须有电子签名。
# 中文注释：**submit（发起领用）不需要签名** —— 需求确认的口径是：
#   提交申请 -> 直接进入待审核 -> 审核人（非申请人）签名后才会扣减。
# 也就是说一次领用只有一次签名，签名人就是审核人。
# 若现场要求"发起时也要申请人签名"，把 u"submit" 加回这里、并重跑
# install_usage_approval.py 写入对应规则即可（工作流与守卫都按这个常量走）。
USAGE_REQUEST_SIGNED_TRANSITIONS = (u"approve", u"reject")
