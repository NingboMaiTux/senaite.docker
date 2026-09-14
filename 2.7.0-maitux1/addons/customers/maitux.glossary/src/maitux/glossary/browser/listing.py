# -*- coding: utf-8 -*-
#
# 中间表列表页
#
# 四件事：
#   1. **进页面即与站点对账同步**（每次打开都跑，只追加/只改状态）
#   2. 活跃 / 未激活 / 全部 三个筛选按钮，默认只显示活跃
#   3. zh、en 可**就地编辑**（走 core 原生保存链路，见 datamanagers），
#      并且按 calc keyword 批量生效
#   4. **搜索**：分析类别 / 检测项目（keyword 与标题）/ 公式字段 keyword /
#      中文名 / 英文名 —— 中英双语都能命中
#
# 工具栏还有「刷新」按钮（browser/sync.py），用于手动重新对账。

import collections

from Products.CMFCore.permissions import ModifyPortalContent
from bika.lims import api
from bika.lims.api.security import check_permission
from bika.lims.utils import get_link
from senaite.app.listing import ListingView
from senaite.core.i18n import translate as _t
from xml.sax.saxutils import escape as html_escape
from zope.i18n import translate as _ztranslate
from zope.publisher.browser import BrowserView

from maitux.glossary import _
from maitux.glossary.config import EDITABLE_FIELDS
from maitux.glossary.config import LISTING_ICON
from maitux.glossary.config import PROJECTNAME
from maitux.glossary.config import REFRESH_ICON
from maitux.glossary.config import STATE_ACTIVE
from maitux.glossary.config import STATE_INACTIVE
from maitux.glossary.config import SYNC_VIEW_NAME
from maitux.glossary.keys import safe_unicode
from maitux.glossary.keys import text
from maitux.glossary.sync.runner import get_remembered_snapshot
from maitux.glossary.sync.runner import run_sync
from maitux.glossary.utils import get_container
from maitux.glossary.utils import iter_entries

STATE_CLASS = {
    STATE_ACTIVE: "glossary-state-active",
    STATE_INACTIVE: "glossary-state-inactive",
}
STATE_LABEL = {
    STATE_ACTIVE: _(u"Active"),
    STATE_INACTIVE: _(u"Inactive"),
}


def language_from_request(request):
    """当前**界面语言**（用于列表标签的翻译）。

    为什么要自己取：列头 / 筛选按钮 / 状态徽标是**通过 AJAX 的 JSON 响应**送到
    前端的，而 core 这条路径不认请求语言 —— 实测（见 README §8.1.4）：

    * `json.dumps(Message)` 只输出 msgid；把它翻成中文的是列表视图里的翻译调用，
      而它拿不到用户界面的语言，于是**无论界面切成什么语言都返回中文**；
    * 给 AJAX 请求带 `Accept-Language: en` 或 `I18N_LANGUAGE=en` 都不改变结果。

    所以这里显式取：**只用** Plone 语言选择器写下的 `I18N_LANGUAGE` cookie
    （用户显式选择的界面语言）；没有 cookie 就返回 None，交给 zope 自己协商
    （等于站点默认语言，保持老行为）。

    **注意不要再去看 `request.get("LANGUAGE")`**：Zope 会默认把它设成 ``en``
    （实测：没有任何语言线索的请求也是 ``en``），用它会让中文站点的列头在
    没选语言时变成英文 —— 踩过一次。
    """
    if request is None:
        return None
    try:
        cookie = request.cookies.get("I18N_LANGUAGE")
    except Exception:
        cookie = None
    return text(cookie) or None


def translated(msgid, request=None):
    """``Message`` -> 当前界面语言的 **unicode**。

    凡是**要拼进 HTML 或送到前端显示的值**都必须显式翻译一次：
    ``html_escape(Message)`` 只会拿到 msgid（英文），而 core 的 JSON 序列化
    也只会输出 msgid 或站点默认语言。

    返回 unicode 而不是 utf-8 字节串，因为下面要往 unicode 模板里做 ``%``
    拼接，而 Py2 的 ``unicode % str`` 会按 ASCII 解码字节串。
    """
    try:
        language = language_from_request(request)
    except Exception:
        language = None
    try:
        if language:
            return _ztranslate(msgid, domain=PROJECTNAME,
                               target_language=language)
        return _t(msgid, to_utf8=False)
    except Exception:
        return safe_unicode(msgid)


#: 搜索覆盖的列（中文名/英文名/两个 keyword/分析类别/检测项目标题）
SEARCH_FIELDS = (
    u"category",
    u"service_title",
    u"analysis_keyword",
    u"calc_keyword",
    u"zh",
    u"en",
)

ADAPTIVE_STYLE = u"""
<style type="text/css">
.glossary-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 3px;
  font-size: 11px;
  font-weight: 500;
  line-height: 16px;
  white-space: nowrap;
}
.glossary-state-active { background: #e7f5e7; color: #2e7d32; border: 1px solid #a5d6a7; }
.glossary-state-inactive { background: #f0f0f0; color: #757575; border: 1px solid #cfcfcf; }
.glossary-ref { color: #6c757d; }
</style>
"""


class GlossaryListingView(ListingView):

    def label(self, msgid):
        """当前**界面语言**下的标签文本。

        列头 / 筛选按钮 / 状态徽标 / 顶部提示都走这里 —— core 的 AJAX 序列化
        不会按界面语言翻译（详见模块里的 ``translated`` 与 ``language_from_request``）。
        """
        return translated(msgid, self.request)

    def __init__(self, context, request):
        super(GlossaryListingView, self).__init__(context, request)

        self.catalog = "portal_catalog"
        self.contentFilter = {}

        # 工具栏标题图标：**必须给**，否则 ListingTableTitleViewlet 会退回
        # bootstrap_view.get_icon_for(context)，对没有图标的内容类型会抛异常，
        # 页面上表现为 listingtitle viewlet 报 LocationError。
        self.icon = LISTING_ICON

        # 允许就地编辑（真正的门禁在 allow_edit 列 + DataManager 的权限检查）
        self.allow_edit = True
        self.show_select_column = True
        self.show_search = True

        self.title = self.label(_(u"Keyword glossary"))

        # 表格上方的固定提示。**必须有**：core 的 Save 按钮在表格**最底部**
        # （senaite.app.listing 的 ButtonBar，与分页同一行），而且是**有未保存
        # 改动时才出现**（show_ajax_save）。用户反馈"刷新页面看不到保存按钮"，
        # 就是因为刷新后队列为空、按钮本来就不该出现。core 没有其它可写的
        # 提示位；这个位置由 senaite.core 的 ListingTableDescriptionViewlet
        # （manager: senaite.listingtabledescription）渲染 view.description，
        # 支持 HTML（structure）。
        self.description = (
            u'<span class="text-muted">%s</span>'
            % self.label(_(
                u"zh / en are editable in place. Changes are kept in the page "
                u"(this listing does NOT autosave): click the Save button at "
                u"the bottom of the table, or tick the row, to store them. "
                u"Unsaved changes are lost when you leave the page.")))

        # 工具栏按钮：手动刷新（重新与站点对账）
        self.context_actions = {
            self.label(_(u"Refresh from site")): {
                "url": "@@" + SYNC_VIEW_NAME,
                "icon": REFRESH_ICON,
            }
        }

        self.columns = collections.OrderedDict((
            ("category", {
                "title": self.label(_(u"Analysis category")),
                "sortable": True,
            }),
            ("analysis_keyword", {
                "title": self.label(_(u"Analysis Keyword")),
                "sortable": True,
            }),
            ("service_title", {
                "title": self.label(_(u"Analysis Service")),
                "sortable": True,
                "toggle": True,
            }),
            ("calc_keyword", {
                "title": self.label(_(u"calc keyword")),
                "sortable": True,
            }),
            # zh / en 就地编辑：**刻意不要 autosave**
            #
            # senaite.app.listing 的 JS（listing.coffee:2017）语义是：
            #   if column.autosave then me.ajax_save()
            # 即 autosave 会在**每次单元格变化时立刻**发一个 set_fields 请求。
            # 而本表的保存要按 calc keyword **批量写所有兄弟行**（R5），于是
            # 边填边存的连续请求会并发改同一批对象 -> ZODB ConflictError ->
            # 提交阶段 500（前端弹 "Oops, an error occurred"，且那一格的修改
            # 可能丢）。去掉 autosave 后：改动只进 ajax_save_queue，界面出现
            # Save 按钮，点一次 = 一个请求 = 一个事务，冲突面消失。
            ("zh", {
                "title": self.label(_(u"zh")),
                "sortable": True,
                "ajax": True,
            }),
            ("en", {
                "title": self.label(_(u"en")),
                "sortable": True,
                "ajax": True,
            }),
            ("site_title", {
                "title": self.label(_(u"Site Field title (reference)")),
                "sortable": False,
                "toggle": True,
            }),
            ("sync_state", {
                "title": self.label(_(u"State")),
                "sortable": True,
            }),
            ("first_seen", {
                "title": self.label(_(u"First seen")),
                "sortable": True,
                "toggle": True,
            }),
            ("state_changed_on", {
                "title": self.label(_(u"State changed on")),
                "sortable": True,
                "toggle": True,
            }),
            ("last_sync_by", {
                "title": self.label(_(u"Last sync by")),
                "sortable": True,
                "toggle": True,
            }),
        ))

        self.review_states = [
            {
                "id": "default",
                "title": self.label(_(u"Active")),
                "contentFilter": {"sync_state": STATE_ACTIVE},
                "columns": self.columns.keys(),
            }, {
                "id": "inactive",
                "title": self.label(_(u"Inactive")),
                "contentFilter": {"sync_state": STATE_INACTIVE},
                "columns": self.columns.keys(),
            }, {
                "id": "all",
                "title": self.label(_(u"All")),
                "contentFilter": {},
                "columns": self.columns.keys(),
            },
        ]

    # ------------------------------------------------------------------
    # 进页面即同步
    # ------------------------------------------------------------------

    def __call__(self):
        is_page = self._is_html_page_request()
        if is_page:
            # 同步失败不影响页面渲染（run_sync 内部已 try/except + 记日志）
            try:
                run_sync(self.get_container())
            except Exception as exc:  # 兜底：绝不让列表页因为同步打不开
                from maitux.glossary import logger
                logger.error("maitux.glossary: sync raised in view: %s", exc)

        result = super(GlossaryListingView, self).__call__()
        if not is_page:
            return result
        if isinstance(result, unicode):
            return ADAPTIVE_STYLE + result
        if isinstance(result, str):
            return ADAPTIVE_STYLE.encode("utf-8") + result
        return result

    def get_container(self):
        """本视图的容器：优先用中间表容器，找不到就退回 context。"""
        container = get_container()
        if container is not None:
            return container
        return self.context

    def _is_html_page_request(self):
        """区分"人打开页面"与 AJAX 子请求（只有前者才自动同步）。"""
        request = self.request
        if request.getHeader("X-Requested-With") == "XMLHttpRequest":
            return False
        accept = request.getHeader("Accept") or ""
        if accept and "json" in accept.lower() and "html" not in accept.lower():
            return False
        path = request.get("PATH_INFO") or request.get("URL") or ""
        lower = path.lower().rstrip("/")
        for suffix in ("/folderitems", "/columns", "/review_states",
                       "/transitions", "/folderactions", "/listitems",
                       "/uid_listing", "/set_fields", "/on_change",
                       "/listing_config"):
            if lower.endswith(suffix):
                return False
        if request.form.get("form_id") or request.form.get("action") == "folderitems":
            return False
        return True

    # ------------------------------------------------------------------
    # 行渲染
    # ------------------------------------------------------------------

    def _state_filter(self):
        """当前筛选按钮 -> 需要保留的 sync_state（None = 全部）。"""
        key = self.request.get("list_review_state") or \
            (self.review_states[0] or {}).get("id", "default")
        if key == "default":
            return STATE_ACTIVE
        if key == "inactive":
            return STATE_INACTIVE
        return None

    def _can_edit(self):
        try:
            return check_permission(ModifyPortalContent, self.context)
        except Exception:
            return False

    def _searchterm(self):
        """搜索词。基类从 ``list_filter`` 取（React listing 的搜索框）。"""
        try:
            term = self.get_searchterm()
        except Exception:
            term = self.request.get("list_filter")
        return text(term).lower()

    def _matches(self, term, values):
        """任一列包含搜索词即命中（大小写不敏感，中英双语通用）。"""
        if not term:
            return True
        for value in values:
            if term in text(value).lower():
                return True
        return False

    def folderitems(self):
        container = self.get_container()
        objects = iter_entries(container)

        state_filter = self._state_filter()
        can_edit = self._can_edit()
        site_keys, _age = get_remembered_snapshot(container)
        term = self._searchterm()

        # 保存单元格时 core 会把 contentFilter["UID"] 设成刚改过的对象，
        # 然后调 folderitems() 只取这几行回给前端
        # （senaite.app.listing.ajax.ajax_set_fields）。本视图自己遍历容器，
        # 所以必须自己尊重这个 UID 限制 —— 否则会把整页行都回给前端。
        uid_filter = self.contentFilter.get("UID")
        if uid_filter and not isinstance(uid_filter, (list, tuple, set)):
            uid_filter = [uid_filter]
        uid_filter = set(uid_filter) if uid_filter else None

        sort_key = (self.request.get("list_sort_on") or "analysis_keyword").lower()
        sort_reverse = (
            self.request.get("list_sort_order") or "ascending").lower() \
            in ("descending", "reverse", "desc")

        items = []
        for obj in objects:
            analysis_keyword = text(getattr(obj, "analysis_keyword", None))
            calc_keyword = text(getattr(obj, "calc_keyword", None))
            if not analysis_keyword or not calc_keyword:
                continue

            state = text(getattr(obj, "sync_state", None)) or STATE_INACTIVE
            if state_filter is not None and state != state_filter:
                continue
            if uid_filter is not None and api.get_uid(obj) not in uid_filter:
                continue

            category = text(getattr(obj, "category", None))
            zh = text(getattr(obj, "zh", None))
            en = text(getattr(obj, "en", None))

            key = (analysis_keyword, calc_keyword)
            info = site_keys.get(key) or {}
            service_title = text(info.get("service_title"))
            site_title = text(info.get("site_title"))

            # 搜索：字段清单只在 SEARCH_FIELDS 里维护一处，
            # 这里按名字取当前行的值（漏给某个名字会直接 KeyError，不会静默漏搜）
            search_values = {
                u"category": category,
                u"service_title": service_title,
                u"analysis_keyword": analysis_keyword,
                u"calc_keyword": calc_keyword,
                u"zh": zh,
                u"en": en,
            }
            values = tuple([search_values[name] for name in SEARCH_FIELDS])
            if not self._matches(term, values):
                continue

            try:
                item_info = self.get_item_info(obj)
            except Exception:
                item_info = {}
            item = self.make_empty_folderitem(**item_info)
            state_label = self.label(STATE_LABEL.get(state, state))
            item.update({
                "id": obj.getId(),
                "uid": api.get_uid(obj),
                "url": api.get_url(obj),
                "title": safe_unicode(api.get_title(obj)),
                "portal_type": api.get_portal_type(obj),
                "review_state": state,
                "state_class": "state-%s" % state,
                "state_title": state_label,
                "category": category,
                "category_sort": category.lower(),
                "analysis_keyword": analysis_keyword,
                "analysis_keyword_sort": analysis_keyword.lower(),
                "service_title": service_title,
                "service_title_sort": service_title.lower(),
                "calc_keyword": calc_keyword,
                "calc_keyword_sort": calc_keyword.lower(),
                "zh": zh,
                "zh_sort": zh.lower(),
                "en": en,
                "en_sort": en.lower(),
                "sync_state": state_label,
                "sync_state_sort": state,
                "site_title": site_title,
                "first_seen": _fmt_date(getattr(obj, "first_seen", None)),
                "state_changed_on": _fmt_date(
                    getattr(obj, "state_changed_on", None)),
                "last_sync_by": text(getattr(obj, "last_sync_by", None)),
                "last_sync_by_sort": text(
                    getattr(obj, "last_sync_by", None)).lower(),
            })

            # 可编辑字段：只有拿到 ModifyPortalContent 才给输入框，
            # 否则只读（免得只读用户点了保存必然失败）
            item["allow_edit"] = list(EDITABLE_FIELDS) if can_edit else []
            item["field"] = {"zh": "zh", "en": "en"}

            item["replace"] = item.get("replace") or {}
            # 能编辑的人点 analysis keyword 直接进该行的编辑表单
            if can_edit:
                item["replace"]["analysis_keyword"] = get_link(
                    href=item["url"] + "/@@edit",
                    value=analysis_keyword, csrf=False)
            else:
                item["replace"]["analysis_keyword"] = html_escape(
                    analysis_keyword)

            item["replace"]["sync_state"] = (
                u'<span class="glossary-tag %s">%s</span>'
                % (STATE_CLASS.get(state, ""), html_escape(state_label)))

            # 站点 Field title 是**参考值**（供人工对照），不参与入库。
            # v2 起 zh 是独立术语，不再期望与站点 Field title 一致，
            # 因此不再做"与站点不一致"的差异高亮，一律灰显。
            if site_title:
                item["replace"]["site_title"] = (
                    u'<span class="glossary-ref">%s</span>'
                    % html_escape(site_title))
            else:
                item["replace"]["site_title"] = (
                    u'<span class="glossary-ref">-</span>')

            items.append(item)

        items.sort(key=lambda it: _sort_value(it, sort_key), reverse=sort_reverse)

        total = len(items)
        self.total = total
        pagesize = 50
        try:
            requested = int(self.request.get("list_pagesize") or 50)
            if requested > 0:
                pagesize = requested
        except Exception:
            pagesize = 50
        self.limit = pagesize
        pages = (total + pagesize - 1) // pagesize if pagesize else 1
        try:
            current = int(self.request.get("list_page_num") or 1)
        except Exception:
            current = 1
        current = max(1, min(current, pages if pages else 1))
        start = (current - 1) * pagesize
        return items[start:start + pagesize]


COLUMN_SORT_KEYS = {
    "category": "category_sort",
    "analysis_keyword": "analysis_keyword_sort",
    "service_title": "service_title_sort",
    "calc_keyword": "calc_keyword_sort",
    "zh": "zh_sort",
    "en": "en_sort",
    "sync_state": "sync_state_sort",
    "last_sync_by": "last_sync_by_sort",
}


def _sort_value(item, sort_key):
    key = COLUMN_SORT_KEYS.get(sort_key)
    if not key:
        return item.get("analysis_keyword_sort") or u""
    return item.get(key) or u""


def _fmt_date(value):
    if not value:
        return u""
    try:
        return value.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return safe_unicode(value)


class GlossaryEntryView(BrowserView):
    """条目自身的 view。

    行数据在列表页里维护，这里不重复做界面：
    能编辑的人跳到该行的编辑表单，不能编辑的跳回中间表列表页。
    """

    def __call__(self):
        response = self.request.response
        try:
            if check_permission(ModifyPortalContent, self.context):
                return response.redirect(
                    api.get_url(self.context) + "/@@edit")
        except Exception:
            pass
        container = get_container()
        if container is not None:
            return response.redirect(api.get_url(container))
        return response.redirect(api.get_url(api.get_portal()))
