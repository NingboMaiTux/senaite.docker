# -*- coding: utf-8 -*-
"""模块级接口定义"""

from plone.supermodel import model
from senaite.core.interfaces import ISenaiteCore
from zope import schema
from zope.interface import Interface

from maitux.reviewerassignment import _


class IReviewerAssignmentLayer(ISenaiteCore):
    """审核分配浏览器层"""


class IReviewerAssignmentContainer(Interface):
    """审核分配根容器接口"""


class IReviewerAssignmentControlPanelSettings(model.Schema):
    """审核分配的站点级开关

    三条业务规则原来是硬编码的，站点无法调整。这里把它们做成开关，
    默认值与硬编码时的行为完全一致 —— 升级上来的站点行为不变。
    """

    require_reviewer_on_worksheet_submit = schema.Bool(
        title=_(u"label_require_reviewer_on_worksheet_submit",
               default=u"Require reviewer before worksheet submit"),
        description=_(
            u"help_require_reviewer_on_worksheet_submit",
            default=u"When disabled, worksheets can be submitted without an "
                    u"assigned reviewer."),
        default=True,
        required=False,
    )

    require_reviewer_on_analysis_submit = schema.Bool(
        title=_(u"label_require_reviewer_on_analysis_submit",
               default=u"Require reviewer before analysis submit"),
        description=_(
            u"help_require_reviewer_on_analysis_submit",
            default=u"When disabled, analyses in the worksheet can still be "
                    u"submitted even if no reviewer is assigned to the "
                    u"worksheet."),
        default=True,
        required=False,
    )

    restrict_verify_to_assigned_reviewer = schema.Bool(
        title=_(u"label_restrict_verify_to_assigned_reviewer",
               default=u"Restrict verification to the assigned reviewer"),
        description=_(
            u"help_restrict_verify_to_assigned_reviewer",
            default=u"When disabled, the add-on no longer checks whether the "
                    u"current user is the assigned reviewer. Verification "
                    u"still follows SENAITE's own permission, self-verification "
                    u"and dependency rules."),
        default=True,
        required=False,
    )

    exclude_submitter_from_reviewers = schema.Bool(
        title=_(u"label_exclude_submitter_from_reviewers",
               default=u"Exclude the future submitter from reviewer options"),
        description=_(
            u"help_exclude_submitter_from_reviewers",
            default=u"Follows SENAITE's self-verification setting. When "
                    u"self-verification is not allowed, the worksheet analyst "
                    u"is removed from the reviewer dropdown so the submission "
                    u"does not fail later during verification."),
        default=True,
        required=False,
    )
