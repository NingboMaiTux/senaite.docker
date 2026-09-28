# -*- coding: utf-8 -*-

import json

from bika.lims import api

from maitux.instrument_acquisition.extender.instrument import FIELD_NAME
from maitux.instrument_acquisition.browser.deemo import instrument_acquisition_test
from maitux.instrument_acquisition.services import report_import


def get_template_from_instrument(instrument):
    """优先读取 Instrument 扩展字段，未配置时回退到旧的一对一模板关系。"""
    if not api.is_object(instrument):
        return None

    field = getattr(instrument, "getField", lambda *a, **k: None)(FIELD_NAME)
    if field is not None:
        try:
            template = field.get(instrument)
            if api.is_object(template):
                return template
        except Exception:
            pass

    # 兼容旧数据：如果模板对象上已经绑定了该仪器，
    # 也允许继续被桥接逻辑识别。
    brains = api.search({
        "portal_type": "InstrumentParsingTemplate",
        "sort_on": "sortable_title",
        "sort_order": "ascending",
    }, catalog="senaite_catalog_setup")
    instrument_uid = api.get_uid(instrument)
    for brain in brains:
        try:
            template = api.get_object(brain)
            linked_instrument = getattr(template, "getInstrument", lambda: None)()
            if api.is_object(linked_instrument) and api.get_uid(linked_instrument) == instrument_uid:
                return template
        except Exception:
            continue
    return None


def parse_and_write_report(template, upload, allow_overwrite=False):
    """复用现有测试页的提取、解析、写回逻辑，供手工导入和自动导入共用。

    解析按模板 `script_file` 后缀分发：`.py` 进程内执行 `parse(payload)`
    （payload 带坐标，PDF 报告走这条），`.js` 仍走 node（兼容旧模板）。

    写回按**解析产物形态**分流：

    | 产物形态 | 通道 | 说明 |
    |---|---|---|
    | 报告产物（`injections` / `grouped`） | `report_import.run(confirm=True)` | 目标位由 `keyword_glossary` 页面配置；按槽位落位；**PDF 强制留档**；**默认不覆盖已有不同值** |
    | 调试通道 A 产物（`samples`） | `_write_parsed_results_to_sample` | 现有天平/读数链路，行为不变 |

    ★ 自动导入（目录 → `@@auto_import_results`）没有人工复核这一步，所以这里
    `confirm=True` 直接写、`allow_overwrite=False` 不碰已有不同值 —— 落位被闸门
    拦下时返回失败，由调用方（适配器）把文件归到 `failed/`。
    """
    success, message, text, filename, extraction = \
        instrument_acquisition_test._extract_pdf_payload(upload)
    if not success:
        return False, message, {
            "filename": filename,
            "extracted_text": text,
            "parsed_text": u"",
            "details": {},
        }

    parsed_text = instrument_acquisition_test._run_template_parser(
        template, text, extraction)

    try:
        parsed = json.loads(parsed_text)
    except Exception as exc:
        return False, u"Parser output is invalid JSON: {}".format(
            instrument_acquisition_test._ensure_text(exc)
        ), {
            "filename": filename,
            "extracted_text": text,
            "parsed_text": parsed_text,
            "details": {},
        }

    if report_import.is_report_payload(parsed):
        # ★ 报告产物：走 M2 报告落位（页面目标位 + 槽位 + 附件 + 覆盖门禁）
        success, message, details = report_import.run(
            parsed,
            confirm=True,
            allow_overwrite=allow_overwrite,
            attachment=upload,
            attachment_title=filename or u"Instrument report",
        )
        return success, message, {
            "filename": filename,
            "extracted_text": text,
            "parsed_text": parsed_text,
            "details": details,
        }

    success, message, details = instrument_acquisition_test._write_parsed_results_to_sample(
        parsed,
        attachment_file=upload,
        attachment_title=filename or u"Instrument report",
    )
    return success, message, {
        "filename": filename,
        "extracted_text": text,
        "parsed_text": parsed_text,
        "details": details,
    }

