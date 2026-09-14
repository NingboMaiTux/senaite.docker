# -*- coding: utf-8 -*-
"""模块配置常量"""

from maitux.reviewerassignment import _

PROJECTNAME = "maitux.reviewerassignment"
ROOT_ID = "reviewerassignmentroot"
ROOT_TYPE = "ReviewerassignmentContainer"

# 根容器标题/描述。
#
# MSG 版本（Message）只用于运行时翻译：必须是 Message，翻译才会用本 addon 的
# 域（见 browser/sidebar.py）。
#
# 纯字符串版本用于**存储**：Dexterity 存 title/description 时会把 Message 拍平
# 成纯字符串（实测存进去再读出来是 str 的 msgid，domain 一并丢失），所以落库
# 只放英文基准值，界面显示交由 Message 翻译。
ROOT_TITLE_MSG = _(
    u"folder_title_review_worksheets",
    default=u"Review Worksheets")
ROOT_TITLE = u"Review Worksheets"
ROOT_DESCRIPTION_MSG = _(
    u"folder_description_review_worksheets",
    default=u"Reviewer-specific queue of worksheets waiting for verification.")
ROOT_DESCRIPTION = u"Reviewer-specific queue of worksheets waiting for verification."
WORKSHEET_REVIEWER_BEHAVIOR = "maitux.reviewerassignment.behavior.worksheetreviewer"
REVIEWER_FIELD = "reviewer_userid"
REVIEWER_INDEX = "getReviewerUserId"
VERIFIER_ROLE = "Verifier"


# 可修改审核人的工作表状态，与 senaite.core 的 edit_states 保持一致。
REVIEWER_EDIT_STATES = ("open", "to_be_verified")

# registry 记录前缀，与 IReviewerAssignmentControlPanelSettings 配套。
REGISTRY_PREFIX = "maitux.reviewerassignment"
