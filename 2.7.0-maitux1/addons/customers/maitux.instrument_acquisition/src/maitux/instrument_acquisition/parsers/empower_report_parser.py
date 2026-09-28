# -*- coding: utf-8 -*-
"""Waters Empower 报告解析脚本（上传到 InstrumentParsingTemplate 的 Parser Script File）

配套规范：`doc/仪器采集/S1919_仪器进样数据采集与命名规范v1.md`
配套抽取：`services/pdf_text.py`（带坐标单元格）
配套实现：`services/empower_pdf.py`（列归属 + SampleName 拆分 + 多针聚合）

--------------------------------------------------------------------------
用法
--------------------------------------------------------------------------
1. LIMS 后台 → 仪器 → 解析模板，新建/编辑模板；
2. 把本文件上传到「Parser Script File」（`.py`，进程内执行，**不需要 node**）；
3. 手工导入 / 自动导入 / 调试页解析（`@@instrument_acquisition_pdf_test`）
   都会执行本文件的 `parse(payload)`。

--------------------------------------------------------------------------
契约
--------------------------------------------------------------------------
输入 `payload`：`services/pdf_text.extract_pdf()` 的产物::

    {u"method": u"python",
     u"note":   u"",
     u"filename": u"1 SYS.pdf",
     u"pages":  [{u"index": 0,
                  u"items": [{u"x": 86.5, u"y": 784.8, u"text": u"Sample Name:"}],
                  u"text":  u"..."}],
     u"text":   u"..."}

输出（dict，会被 `json.dumps` 交给调用方 `json.loads`）::

    {u"report_type": u"empower_pdf",
     u"report":   {u"sample_set_name", u"worksheet_id", u"project",
                   u"report_method", u"report_method_id", u"page_count"},
     u"injections": [ {u"sample_name", u"sample_type", u"vial", u"injection_no",
                       u"role", u"level", u"idx", u"is_batch", u"peaks": [...]} ],
     u"grouped":  [ {u"sample_name", u"role", u"idx", u"level",
                     u"injection_count", u"peak_count", u"injections": [...]} ],
     u"warnings": [u"..."]}

★ 注意：`injections` / `grouped` 是**报告语义**产物，不是调试通道 A 的
`{"samples": [...]}` 结构，所以调试页的「3. Write To System」不接受它；
写回由 M2（`services/report_import.py`）按目标位白名单处理。

★ 峰级数值不在这里做格式归一：归一在写回前做（整数不带 `.0`）。
"""

REPORT_TYPE = u"empower_pdf"


def _empty(warnings):
    return {
        u"report_type": REPORT_TYPE,
        u"report": {},
        u"injections": [],
        u"grouped": [],
        u"warnings": list(warnings),
    }


def parse(payload):
    """Empower 报告 → {report, injections, grouped, warnings}"""
    if not isinstance(payload, dict) or not payload.get(u"pages"):
        return _empty([
            u"Empower 报告只能走坐标抽取：payload 里没有 pages/items。"
            u"请确认 PDF 抽取走的是 pdf_text.extract_pdf()，而不是版式文本兜底。",
        ])

    from maitux.instrument_acquisition.services import empower_pdf

    result = empower_pdf.parse_extraction(payload)
    injections = result.get(u"injections") or []

    grouped = []
    for sample_name, items in empower_pdf.group_by_sample(injections):
        first = items[0] if items else {}
        grouped.append({
            u"sample_name": sample_name,
            u"role": first.get(u"role", u""),
            u"idx": first.get(u"idx", u""),
            u"level": first.get(u"level", u""),
            u"injection_count": len(items),
            u"peak_count": sum(len(item.get(u"peaks") or []) for item in items),
            u"injections": items,
        })

    return {
        u"report_type": REPORT_TYPE,
        u"report": result.get(u"report") or {},
        u"injections": injections,
        u"grouped": grouped,
        u"warnings": result.get(u"warnings") or [],
    }
