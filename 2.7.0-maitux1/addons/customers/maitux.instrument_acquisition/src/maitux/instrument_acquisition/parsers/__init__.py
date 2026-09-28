# -*- coding: utf-8 -*-
"""解析脚本目录（InstrumentParsingTemplate → Parser Script File）

这里的 `.py` 文件是**可上传到模板的采集脚本**：LIMS 进程内执行其中的
`parse(payload)`。脚本作为版本库资产保留，便于随 addon 一起升级/复用；
模板上仍以 `script_file` 字段为准（上传哪份就执行哪份）。
"""
