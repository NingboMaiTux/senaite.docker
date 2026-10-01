# -*- coding: utf-8 -*-
"""任务看板的"选中行"解析 —— **唯一实现**。

看板上的每一行是"某个方案的第 N 个明细行"，行标识是 ``<plan_uid>::<seq>``
（``seq`` 从 1 起）。所有批量操作页（样品放置 / 关联样品 / 建样 / 登样）
都从这里取"用户选了哪些行"，规则必须**完全一致**：

* 只认 ``uid::seq`` 形态：``plan_uid`` 必须是合法 UID、``seq`` 必须是正整数；
* 去重且保持顺序 —— 重复提交同一行会让同一个样品被建两次；
* 非字符串 / 空值一律丢弃（表单可能提交列表、也可能提交单个字符串）。

为什么抽出来：这四条规则原先在 4 个视图里各写了一遍，
改一条（例如"同时接受 detail_uid"）就要改四处，漏一处就是安全/数据问题。
"""

import six

from bika.lims import api


def selected_row_ids(request):
    """取本次请求提交的选中行（``row_ids`` / ``row_ids:list``）。

    兼容三种提交形态：单值、列表、缺失。
    """
    value = request.get("row_ids", request.form.get("row_ids", []))
    if not isinstance(value, (list, tuple)):
        value = [value]

    result = []
    for row_id in value:
        if not row_id or not isinstance(row_id, six.string_types):
            continue
        if "::" not in row_id:
            continue
        if row_id not in result:
            result.append(row_id)
    return result


def submitted_detail_uids(request):
    """取页面提交上来的"行标识 -> 该行的 ``detail_uid``"，返回 ``{row_id: uid}``。

    模板把 ``row_ids:list`` 与 ``row_uids:list`` **按同一顺序**写进表单，
    所以这里按下标对齐；重复的行标识只认第一个（与 ``selected_row_ids`` 的去重口径一致）。

    为什么要把它提交回来：登样是写操作，而页面渲染到提交之间方案可能被别的用户
    删行/排序过 —— 那时行号指向的已经是**另一行**。带上 ``detail_uid``
    就能在服务端判出"要登的不是原来那行"并拒绝，而不是把样品挂错行。

    提交里缺这个字段时返回空串（不是"跳过校验"）：服务端拿空串与库里的 id 比对，
    不一致即拒绝 —— 手写 POST 绕不过这道门。
    """
    ids = request.get("row_ids", request.form.get("row_ids", []))
    uids = request.get("row_uids", request.form.get("row_uids", []))
    if not isinstance(ids, (list, tuple)):
        ids = [ids]
    if not isinstance(uids, (list, tuple)):
        uids = [uids]

    result = {}
    for index, row_id in enumerate(ids):
        if not row_id or not isinstance(row_id, six.string_types):
            continue
        if "::" not in row_id or row_id in result:
            continue
        uid = uids[index] if index < len(uids) else u""
        result[row_id] = api.safe_unicode(uid).strip() if uid else u""
    return result


def parse_row_id(row_id):
    """把 ``<plan_uid>::<seq>`` 解析成 ``(plan_uid, seq)``；非法返回 ``(None, None)``。"""
    try:
        plan_uid, seq = row_id.split("::", 1)
        seq = int(seq)
    except Exception:
        return (None, None)
    if not api.is_uid(plan_uid):
        return (None, None)
    if seq <= 0:
        return (None, None)
    return (plan_uid, seq)


def group_by_plan(row_ids):
    """把行标识按方案分组，返回 ``[(plan_uid, [seq, ...]), ...]``（保序、去重）。"""
    groups = []
    index = {}
    for row_id in row_ids:
        plan_uid, seq = parse_row_id(row_id)
        if plan_uid is None:
            continue
        if plan_uid not in index:
            index[plan_uid] = len(groups)
            groups.append((plan_uid, []))
        seqs = groups[index[plan_uid]][1]
        if seq not in seqs:
            seqs.append(seq)
    return groups
