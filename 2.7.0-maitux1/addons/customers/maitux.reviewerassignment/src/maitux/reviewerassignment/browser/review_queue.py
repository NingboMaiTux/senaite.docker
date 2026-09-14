# -*- coding: utf-8 -*-
"""审核人工作表队列视图"""

import collections

from bika.lims import api
from senaite.core.browser.listing.base import ListingView
from senaite.core.browser.worksheets.view import WorksheetsView
from zope.i18n import translate as ztranslate

from maitux.reviewerassignment.assignment import get_member_fullname
from maitux.reviewerassignment.config import REVIEWER_INDEX
from maitux.reviewerassignment import _


class ReviewerQueueView(WorksheetsView):
    """仅展示当前审核人待审核工作表"""

    default_review_state = "to_be_verified"

    def __init__(self, context, request):
        super(ReviewerQueueView, self).__init__(context, request)
        self.title = self.translate_message(_(
            u"review_queue_title",
            default=u"Review Worksheets",
        ))
        self.description = self.translate_message(_(
            u"review_queue_description",
            default=u"Shows only worksheets assigned to the current reviewer "
                    u"and waiting for verification.",
        ))
        self.context_actions = {}
        self.show_workflow_action_buttons = True
        self.show_select_column = True
        self.show_select_all_checkbox = True
        self.columns = collections.OrderedDict((
            ("Title", {
                "title": self.translate_message(_(
                    u"column_worksheet",
                    default=u"Worksheet",
                )),
                "index": "getId",
            }),
            ("Analyst", {
                "title": self.translate_message(_(
                    u"column_analyst",
                    default=u"Analyst",
                )),
                "index": "getAnalyst",
            }),
            (REVIEWER_INDEX, {
                "title": self.translate_message(_(
                    u"column_reviewer",
                    default=u"Reviewer",
                )),
                "index": REVIEWER_INDEX,
            }),
            ("CreationDate", {
                "title": self.translate_message(_(
                    u"column_created",
                    default=u"Created",
                )),
                "index": "created",
            }),
            ("state_title", {
                "title": self.translate_message(_(
                    u"column_status",
                    default=u"Status",
                )),
                "index": "review_state",
                "attr": "state_title",
            }),
        ))
        self.review_states = [{
            "id": "to_be_verified",
            "title": self.translate_message(_(
                u"state_to_be_verified",
                default=u"To be verified",
            )),
            "contentFilter": {
                "review_state": "to_be_verified",
                "sort_on": "created",
                "sort_order": "reverse",
            },
            "transitions": [],
            "custom_transitions": [{
                "id": "verify_assigned",
                "title": self.translate_message(_(
                    u"action_verify",
                    default=u"Verify",
                )),
            }],
            "columns": self.columns.keys(),
        }]

    def before_render(self):
        """渲染前固定加入当前审核人过滤条件"""
        # 这里不能调用 WorksheetsView.before_render，
        # 因为父类会强制访问 "mine" 状态，而当前页面只保留待审核状态。
        ListingView.before_render(self)
        self.request.set("disable_border", 1)
        self.selected_state = "to_be_verified"
        self.allow_edit = self.is_edit_allowed()
        self.can_manage = self.is_manage_allowed()
        current_userid = self.member.getId()
        self.contentFilter["review_state"] = "to_be_verified"
        self.contentFilter[REVIEWER_INDEX] = current_userid
        for state in self.review_states:
            state["contentFilter"][REVIEWER_INDEX] = current_userid
        self.selected_state = "to_be_verified"
        self.context_actions = {}

    def folderitems(self):
        """把审核人 id 转成更友好的全名显示"""
        items = super(ReviewerQueueView, self).folderitems()
        for item in items:
            reviewer_userid = item.get(REVIEWER_INDEX, u"")
            item[REVIEWER_INDEX] = get_member_fullname(
                self.context, reviewer_userid)
        return items

    def can_add(self):
        return False

    def is_manage_allowed(self):
        return False

    def is_edit_allowed(self):
        return False

    def show_only_mine(self):
        """该页面只按审核人过滤，不叠加分析员限制"""
        return False

    def translate_message(self, msg):
        translated = ztranslate(msg, context=self.request)
        return api.safe_unicode(translated)
