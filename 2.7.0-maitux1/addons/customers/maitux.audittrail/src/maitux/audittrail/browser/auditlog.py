# -*- coding: utf-8 -*-
"""审计追踪增强视图"""

import collections
import json

import six
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from bika.lims import api
from bika.lims.api.snapshot import _process_value
from bika.lims.api.snapshot import compare_snapshots
from bika.lims.api.snapshot import get_snapshot_by_version
from bika.lims.api.snapshot import get_snapshot_metadata
from bika.lims.api.snapshot import get_snapshots
from bika.lims.browser.auditlog import AuditLogView as BaseAuditLogView

from maitux.audittrail.browser.formatter import extract_signature
from maitux.audittrail.browser.formatter import is_json_data
from maitux.audittrail.browser.formatter import is_worksheet_layout
from maitux.audittrail.browser.formatter import render_interim_fields_html
from maitux.audittrail.browser.formatter import render_json_html
from maitux.audittrail.browser.formatter import render_signature_html
from maitux.audittrail.browser.formatter import render_worksheet_layout_html


SIGNATURE_COLUMN_ID = "esignature"

# 每个 diff 行怎么渲染。一行的多个历史值可能形态不同，取最高的那个模式。
ROW_MODE_TEXT = "text"
ROW_MODE_STRUCTURED = "structured"
ROW_MODE_INTERIM = "interim"

ROW_MODE_PRIORITY = {
    ROW_MODE_TEXT: 0,
    ROW_MODE_STRUCTURED: 1,
    ROW_MODE_INTERIM: 2,
}


class AuditLogView(BaseAuditLogView):
    """覆盖原审计追踪页，提升 Interim Fields 的可读性并呈现电子签名"""

    diff_template = ViewPageTemplateFile("templates/auditlog_diff.pt")

    def __init__(self, context, request):
        super(AuditLogView, self).__init__(context, request)
        self.columns = self.add_signature_column(self.columns)
        # ★ 必须两处都改。基类 __init__ 里是
        #       "columns": self.columns.keys()
        #   Python 2 的 .keys() 返回的是列表快照，只往 self.columns 塞新键
        #   不会传导到这里，列不会出现 —— 静默失败。
        for review_state in self.review_states:
            review_state["columns"] = self.columns.keys()
        # UID → 标题的解析结果，同一次渲染里同一个样品/分析项只查一次
        self._uid_title_cache = {}

    def add_signature_column(self, columns):
        """在"工作流状态"之后插入签名列

        刻意不设 toggle：默认可见。21 CFR Part 11 §11.50(b) 要求签名
        manifestation 是人类可读形式的组成部分，藏进"显示列"里等人勾选不算已呈现。
        """
        column = {
            "title": u"电子签名",
            "sortable": False,
        }
        new_columns = collections.OrderedDict()
        for key, value in columns.items():
            new_columns[key] = value
            if key == "review_state":
                new_columns[SIGNATURE_COLUMN_ID] = column
        # 上游若改了列名导致锚点找不到，也要保证这一列存在，只是位置退到最后
        if SIGNATURE_COLUMN_ID not in new_columns:
            new_columns[SIGNATURE_COLUMN_ID] = column
        return new_columns

    def is_interim_fields(self, field, value):
        """只对 Calculation/Analysis 的 InterimFields 做结构化展示

        兼容快照里大小写两种字段名：InterimFields（Calculation）与
        interim_fields（Analysis 等 SuperModel 生成的小写字段名）。
        """
        field = (field or "").lower()
        return field in ("interimfields", "interim_fields") and \
            isinstance(value, (list, tuple))

    def is_layout_field(self, field, value):
        """Worksheet 布局（layout_view）也做结构化展示"""
        return is_worksheet_layout(field, value)

    def is_structured_json(self, value):
        """通用 JSON 数据（dict / list[dict] / JSON 串）走结构化展示"""
        return is_json_data(value)

    def resolve_uid_title(self, uid):
        """UID → 人类可读标题；解析不出来就返回空串

        formatter 拿到空串会回落到原 UID。审计页面宁可显示裸 UID，
        也不能因为对象已删除之类的原因把这一格变成空白。
        """
        if not uid:
            return u""
        if uid not in self._uid_title_cache:
            self._uid_title_cache[uid] = self._lookup_uid_title(uid)
        return self._uid_title_cache[uid]

    def _lookup_uid_title(self, uid):
        """单次 UID 解析，异常一律降级为空串"""
        try:
            obj = api.get_object_by_uid(uid, default=None)
        except Exception:
            obj = None
        if obj is None:
            return u""
        try:
            return api.get_title(obj) or api.get_id(obj) or u""
        except Exception:
            return u""

    def render_text_value(self, value):
        """复用原生的人类可读字符串转换逻辑"""
        return _process_value(value)

    def render_html_value(self, field, value):
        """结构化数据输出表格 HTML，其它字段保持普通文本"""
        if self.is_interim_fields(field, value):
            return render_interim_fields_html(value)
        if self.is_layout_field(field, value):
            return render_worksheet_layout_html(
                value, uid_resolver=self.resolve_uid_title)
        if self.is_structured_json(value):
            return render_json_html(value)
        return api.text_to_html(self.render_text_value(value), wrap="pre")

    def get_row_mode(self, field, current_value, previous_value):
        """判断一行该用哪种渲染模式"""
        if self.is_interim_fields(field, current_value) or \
                self.is_interim_fields(field, previous_value):
            return ROW_MODE_INTERIM
        if self.is_layout_field(field, current_value) or \
                self.is_layout_field(field, previous_value):
            return ROW_MODE_STRUCTURED
        if self.is_structured_json(current_value) or \
                self.is_structured_json(previous_value):
            return ROW_MODE_STRUCTURED
        return ROW_MODE_TEXT

    def merge_row_mode(self, current_mode, new_mode):
        """一行里多个历史值形态不同时，取"最能读出内容"的那个模式"""
        if ROW_MODE_PRIORITY.get(new_mode, 0) > \
                ROW_MODE_PRIORITY.get(current_mode, 0):
            return new_mode
        return current_mode

    def render_diff(self, diff):
        """先把 diff 预处理成模板更容易消费的结构"""
        rows = []
        for field in diff.keys():
            row = {
                "field": field,
                "label": self.get_widget_label_for(field, default=field),
                "mode": ROW_MODE_TEXT,
                "is_interim_fields": False,
                "is_structured": False,
                "is_text": True,
                "diffs": [],
            }
            for current_value, previous_value in diff[field]:
                row["mode"] = self.merge_row_mode(
                    row["mode"],
                    self.get_row_mode(field, current_value, previous_value))
                # 四种表示一律备齐：模板按 mode 只取一种，多算一点换来的是
                # "模板里不会出现取不到的键"，比按 mode 偷懒渲染更划算。
                row["diffs"].append({
                    "before_text": self.render_text_value(previous_value),
                    "after_text": self.render_text_value(current_value),
                    "before_html": self.render_html_value(field, previous_value),
                    "after_html": self.render_html_value(field, current_value),
                })
            # 模板只认这三个布尔量，别把优先级判断写进模板
            row["is_interim_fields"] = row["mode"] == ROW_MODE_INTERIM
            row["is_structured"] = row["mode"] == ROW_MODE_STRUCTURED
            row["is_text"] = row["mode"] == ROW_MODE_TEXT
            rows.append(row)
        return self.diff_template(self, rows=rows)

    def folderitems(self):
        """复制原逻辑，仅把 diff 改成 raw=True 以拿到原始结构"""
        items = []
        snapshots = get_snapshots(self.context)
        snapshots = list(reversed(snapshots))
        self.total = len(snapshots)
        batch = snapshots[self.limit_from:self.limit_from + self.pagesize]

        for num, snapshot in enumerate(batch):
            item = self.make_empty_item(**snapshot)
            version = self.total - self.limit_from - num - 1
            item["version"] = version

            snapshot_data = json.dumps(snapshot, indent=2, sort_keys=True)
            item["snapshot"] = api.text_to_html(snapshot_data, wrap="pre")

            metadata = get_snapshot_metadata(snapshot)
            m_date = metadata.get("modified")
            item["modified"] = self.to_localized_time(m_date)

            actor = metadata.get("actor")
            item["actor"] = actor

            properties = api.get_user_properties(actor)
            item["fullname"] = properties.get("fullname", actor)

            roles = metadata.get("roles", [])
            if not isinstance(roles, (list, tuple)):
                roles = [roles] if roles else []
            roles = [role for role in roles if isinstance(role, six.string_types)]
            item["roles"] = ", ".join(roles)

            item["remote_address"] = metadata.get("remote_address")
            item["action"] = self.translate_state(metadata.get("action"))

            review_state = metadata.get("review_state")
            item["review_state"] = self.translate_state(review_state)

            # 电子签名：优先取结构化的 metadata["esignature"]，
            # 回落到 DCWorkflow 带过来的 comments 摘要；无签名的行留空。
            item[SIGNATURE_COLUMN_ID] = render_signature_html(
                extract_signature(metadata), timestamp=item["modified"])

            prev_snapshot = get_snapshot_by_version(self.context, version - 1)
            if prev_snapshot:
                prev_metadata = get_snapshot_metadata(prev_snapshot)
                prev_review_state = prev_metadata.get("review_state")
                if prev_review_state != review_state:
                    item["replace"]["review_state"] = "{} &rarr; {}".format(
                        self.translate_state(prev_review_state),
                        self.translate_state(review_state))

                # 这里显式改用 raw=True，保留 InterimFields 的列表/字典结构，
                # 便于后续在模板里按表格方式渲染。
                diff = compare_snapshots(snapshot, prev_snapshot, raw=True)
                item["diff"] = self.render_diff(diff)

            items.append(item)

        return items
