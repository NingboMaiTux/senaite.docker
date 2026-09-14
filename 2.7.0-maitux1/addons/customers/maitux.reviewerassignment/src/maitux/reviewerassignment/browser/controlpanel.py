# -*- coding: utf-8 -*-
"""审核分配控制面板"""

from bika.lims import api
from plone.registry.interfaces import IRegistry
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from zope.component import getUtility
from zope.i18n import translate as ztranslate

from maitux.reviewerassignment.config import REGISTRY_PREFIX
from maitux.reviewerassignment.settings import DEFAULTS
from maitux.reviewerassignment import _


FIELDS = (
    ("require_reviewer_on_worksheet_submit",
     _(u"label_require_reviewer_on_worksheet_submit",
       default=u"Require reviewer before worksheet submit"),
     _(u"help_require_reviewer_on_worksheet_submit",
       default=u"When disabled, worksheets can be submitted without an "
               u"assigned reviewer.")),
    ("require_reviewer_on_analysis_submit",
     _(u"label_require_reviewer_on_analysis_submit",
       default=u"Require reviewer before analysis submit"),
     _(u"help_require_reviewer_on_analysis_submit",
       default=u"When disabled, analyses in the worksheet can still be "
               u"submitted even if no reviewer is assigned to the worksheet.")),
    ("restrict_verify_to_assigned_reviewer",
     _(u"label_restrict_verify_to_assigned_reviewer",
       default=u"Restrict verification to the assigned reviewer"),
     _(u"help_restrict_verify_to_assigned_reviewer",
       default=u"When disabled, the add-on no longer checks whether the "
               u"current user is the assigned reviewer. Verification still "
               u"follows SENAITE's own permission, self-verification and "
               u"dependency rules.")),
    ("exclude_submitter_from_reviewers",
     _(u"label_exclude_submitter_from_reviewers",
       default=u"Exclude the future submitter from reviewer options"),
     _(u"help_exclude_submitter_from_reviewers",
       default=u"Follows SENAITE's self-verification setting. When "
               u"self-verification is not allowed, the worksheet analyst is "
               u"removed from the reviewer dropdown so the submission does "
               u"not fail later during verification.")),
)


class ReviewerAssignmentControlPanelView(BrowserView):
    """四个站点级开关 + 站点前置条件状态"""

    index = ViewPageTemplateFile("templates/controlpanel.pt")

    def __call__(self):
        if self.request.form.get("form_submitted"):
            self.handle_save()
        return self.index()

    def handle_save(self):
        registry = getUtility(IRegistry)
        for name, _title, _description in FIELDS:
            key = "%s.%s" % (REGISTRY_PREFIX, name)
            value = bool(self.request.form.get(name))
            try:
                registry[key] = value
            except Exception:
                # 记录还没注册出来时不要让整个页面炸掉，重装 profile 即可修复。
                continue
        api.get_request().response.redirect(
            "%s/@@maitux-reviewerassignment-controlpanel"
            % api.get_url(api.get_portal()))

    def get_fields(self):
        """返回 (name, title, description, value) 供模板渲染"""
        registry = getUtility(IRegistry)
        items = []
        for name, title, description in FIELDS:
            key = "%s.%s" % (REGISTRY_PREFIX, name)
            try:
                value = registry[key]
            except Exception:
                value = DEFAULTS.get(name, True)
            items.append({
                "name": name,
                "title": self.translate_message(title),
                "description": self.translate_message(description),
                "value": bool(value),
            })
        return items

    def get_prerequisite_status(self):
        """站点前置条件：AllowToSubmitNotAssigned 打开时本 addon 形同虚设

        审核人规则只覆盖工作表内的分析项。该设置一旦打开，不建工作表也能提交，
        整套约束可被绕过。这里把状态显式摆在面板上，而不是只写进安装日志。
        """
        setup_tool = api.get_bika_setup()
        if setup_tool is None:
            return {"ok": True, "message": u""}
        try:
            allow_not_assigned = setup_tool.getAllowToSubmitNotAssigned()
        except Exception:
            return {"ok": True, "message": u""}

        if not allow_not_assigned:
            return {
                "ok": True,
                "message": self.translate_message(_(
                    u"prerequisite_allow_to_submit_not_assigned_disabled",
                    default=u'The site has disabled "Allow to submit '
                            u'unassigned analyses", so reviewer rules cover '
                            u'the submission path.',
                )),
            }
        return {
            "ok": False,
            "message": self.translate_message(_(
                u"prerequisite_allow_to_submit_not_assigned_enabled",
                default=u'The site has enabled "Allow to submit unassigned '
                        u'analyses". Analyses can be submitted without '
                        u'creating a worksheet, while reviewer rules only '
                        u'cover analyses inside worksheets, so this add-on can '
                        u'be bypassed completely. Please disable the option in '
                        u'Setup > Analyses.',
            )),
        }

    def translate_message(self, msg):
        translated = ztranslate(msg, context=self.request)
        return api.safe_unicode(translated)
