# -*- coding: utf-8 -*-

import json

from bika.lims import api
from senaite.core.exportimport.instruments import IInstrumentAutoImportInterface
from senaite.core.exportimport.instruments import IInstrumentImportInterface
from senaite.core.exportimport.instruments.logger import Logger
from zope.interface import implementer

from maitux.instrument_acquisition.importer import auto_import_archive
from maitux.instrument_acquisition.services import acquisition


class InstrumentAcquisitionFileParser(object):
    """自动导入场景下的最小文件包装器。"""

    def __init__(self, infile):
        self._infile = infile

    def getInputFile(self):
        return self._infile


@implementer(IInstrumentImportInterface, IInstrumentAutoImportInterface)
class InstrumentAcquisitionImporter(Logger):
    """把 maitux.instrument_acquisition 桥接到原生导入入口。"""

    title = "Instrument Acquisition PDF/JS"

    def __init__(self, context):
        Logger.__init__(self)
        self.context = context
        self.instrument = None
        self.parser = None

    def get_automatic_parser(self, infile):
        return InstrumentAcquisitionFileParser(infile)

    def get_automatic_importer(self, instrument, parser, **kw):
        importer = self.__class__(self.context)
        importer.instrument = instrument
        importer.parser = parser
        return importer

    def process(self):
        """自动导入入口：按仪器上关联的模板执行提取、解析和写回。

        ★ 报告类文件（Empower PDF）会在 `acquisition.parse_and_write_report()`
        里分流到 `report_import.run(confirm=True)`：目标位来自 `keyword_glossary`
        页面、按槽位落位、**报告 PDF 强制留档**、**默认不覆盖已有不同值**。

        ★ 结论会记进 `auto_import_archive`（线程局部）：失败时由原生视图的包装器
        把文件移进 `<folder>/failed/` 并**不写** `imported.csv`，这样文件可以重投。
        """
        auto_import_archive.clear_outcome()
        if not api.is_object(self.instrument):
            self.err("Instrument not found")
            return False

        template = acquisition.get_template_from_instrument(self.instrument)
        if not api.is_object(template):
            self.err(
                "No Instrument Parsing Template linked to this Instrument"
            )
            return False

        upload = self.parser.getInputFile() if self.parser else None
        if upload is None:
            self.err("No file selected")
            return False

        # 自动导入目录里的**绝对路径**（原生 UploadFileWrapper 暴露 .name）
        source_path = getattr(upload, "name", None) or u""
        filename = getattr(upload, "filename", u"") or u""

        try:
            success, message, payload = acquisition.parse_and_write_report(
                template,
                upload,
            )
        except Exception as exc:
            # 未捕获异常也要留结论，否则原生会把这份文件当成"已导入"跳过
            auto_import_archive.remember_outcome(
                source_path, filename, False,
                u"导入过程抛出异常：%s" % exc)
            raise

        filename = payload.get("filename") or filename
        template_title = api.get_title(template)
        details = payload.get("details") or {}
        # ★ 自动导入没有人工复核：diff / 告警 / 失败明细都要落进日志
        self._log_details(details)

        if success:
            # 记录模板和文件名，便于从 auto import log 追踪实际桥接链路。
            self.log(
                u"Imported '{}' with template '{}'".format(
                    filename,
                    template_title,
                )
            )
            self.log(message)
            auto_import_archive.remember_outcome(
                source_path, filename, True, message)
            return True

        self.err(
            u"Failed to import '{}' with template '{}'".format(
                filename,
                template_title,
            )
        )
        self.err(message)
        parsed_text = payload.get("parsed_text")
        if parsed_text:
            self.warn(parsed_text)
        auto_import_archive.remember_outcome(
            source_path, filename, False, message)
        return False

    def _log_details(self, details):
        """把落位 diff / 告警 / 失败明细写进导入日志

        ★ 自动导入无人复核，`AutoImportLog` + 目录里的 `logs.log` 是**唯一**痕迹：
        每条目标位的最终状态（`MATCH` / `WRITTEN` / `SLOT_SKIPPED` /
        `SKIPPED_OVERWRITE` / `MISSING_*`）都要能查到。
        """
        if not isinstance(details, dict):
            return
        for row in details.get("diff") or []:
            if not isinstance(row, dict):
                continue
            self.log(u"{}  [{}]".format(
                u"%s.%s" % (row.get("analysis_keyword") or u"?",
                            row.get("interim_keyword") or u"?"),
                row.get("status") or u"?"))
            hint = row.get("hint")
            if hint:
                self.log(u"    {}".format(hint))
        for warning in details.get("warnings") or []:
            self.warn(warning)
        for error in details.get("errors") or []:
            self.err(error)

    def Import(self, context, request):
        """手工导入入口：复用与 auto_import_results 相同的后端逻辑。"""
        infile = request.form.get("instrument_results_file")
        instrument_uid = request.form.get("instrument", None)

        if not infile:
            return json.dumps({
                "errors": ["No file selected"],
                "log": [],
                "warns": [],
            })

        instrument = api.get_object(instrument_uid, None)
        importer = self.get_automatic_importer(
            instrument,
            self.get_automatic_parser(infile),
        )
        importer.process()
        # 手工导入的文件不在自动导入目录里，别把结论留在线程上
        auto_import_archive.clear_outcome()

        return json.dumps({
            "errors": importer.errors,
            "log": importer.logs,
            "warns": importer.warns,
        })

