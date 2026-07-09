"""Deterministic 需求解析引擎：自然语言 → change_spec（AddField）。

零依赖、规则驱动、可预测。设计理念（见现状分析 3.1）：AI 只用于理解
自然语言，一旦产出 change_spec，后续全部确定性处理。此引擎是离线兜底，
不依赖任何大模型。

支持的模式（中/英）：
  "为 AnalysisRequest 添加一个名为 maitux_sample_code 的字符串字段"
  "给 Sample 加一个必填的整数字段 foo"
  "add a string field named bar to Client"
并可选识别「在 X 列表视图显示该字段」→ 追加 UpdateListing。
"""

from __future__ import annotations

import re
from typing import Optional

from shared.result import Result

# 中文/英文字段类型 → change_spec fieldType
_TYPE_KEYWORDS = [
    (("字符串", "文本行", "string", "textline", "text line"), "StringField"),
    (("长文本", "多行文本", "text", "textarea"), "TextField"),
    (("整数", "整型", "数字", "integer", "int"), "IntegerField"),
    (("小数", "浮点", "float", "decimal"), "FloatField"),
    (("布尔", "是否", "boolean", "bool", "checkbox"), "BooleanField"),
]

_REQUIRED_KEYWORDS = ("必填", "必须", "required", "mandatory")
_LISTING_KEYWORDS = ("列表", "列表视图", "listing", "list view", "列中显示", "列表中显示")


def _infer_field_type(text: str) -> str:
    low = text.lower()
    for keys, ftype in _TYPE_KEYWORDS:
        if any(k in text or k in low for k in keys):
            return ftype
    return "StringField"  # 默认字符串


def _extract_field_name(text: str) -> Optional[str]:
    """从描述中提取字段名。支持中英文，中文自动转为英文标识。"""
    # 英文模式
    patterns = [
        r"名为\s*([A-Za-z_][A-Za-z0-9_]*)",
        r"叫\s*([A-Za-z_][A-Za-z0-9_]*)",
        r"字段\s*[名]?\s*[为叫]?\s*([A-Za-z_][A-Za-z0-9_]*)",
        r"named\s+([A-Za-z_][A-Za-z0-9_]*)",
        r"called\s+([A-Za-z_][A-Za-z0-9_]*)",
        r"field\s+([A-Za-z_][A-Za-z0-9_]*)",
        r"\[([A-Za-z_][A-Za-z0-9_]*)\]",  # [field_name] 方括号
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return m.group(1)

    # 中文模式：用方括号包住的中文 → 转拼音/英文标识
    m = re.search(r"\[(.+?)\]", text)
    if m:
        cn = m.group(1)
        # 简单映射常见词，否则用拼音首字母
        cn_map = {"详情": "detail", "备注": "remark", "电话": "phone",
                   "地址": "address", "名称": "name", "编号": "code",
                   "日期": "date", "状态": "status", "描述": "description",
                   "数量": "quantity", "价格": "price"}
        return cn_map.get(cn, "maitux_" + _cn_abbr(cn))

    # 中文模式：直接出现中文字段名（如"添加详情字段"）
    m = re.search(r"添加\s*(\S{1,4})\s*字段", text)
    if m:
        cn = m.group(1)
        cn_map = {"详情": "detail", "备注": "remark", "电话": "phone",
                   "地址": "address", "名称": "name", "编号": "code",
                   "日期": "date", "状态": "status", "描述": "description",
                   "数量": "quantity", "价格": "price"}
        return cn_map.get(cn, "maitux_" + _cn_abbr(cn))

    return None


def _cn_abbr(text: str) -> str:
    """中文→拼音首字母简写。"""
    import unicodedata
    result = []
    for ch in text:
        if '一' <= ch <= '鿿':
            # 用 Unicode 码点做简单映射
            result.append(hex(ord(ch))[3:])
        elif ch.isascii() and ch.isalnum():
            result.append(ch)
    return "f_" + "".join(result[:6]) if result else "field"


def _resolve_type_id(text: str, known_types: dict) -> Optional[str]:
    """在文本里找目标类型：不区分大小写，优先 type_id 其次 title。
    注意：中文环境下 \b 失效（中文字符在 Python 正则中被视为单词字符），
    改用 (?<![a-zA-Z]) 和 (?![a-zA-Z]) 确保不匹配到其他英文单词的子串。"""
    for type_id in known_types:
        pat = r"(?<![a-zA-Z])%s(?![a-zA-Z])" % re.escape(type_id)
        if re.search(pat, text, re.IGNORECASE):
            return type_id
    for type_id, meta in known_types.items():
        title = (meta or {}).get("title") or ""
        if not title:
            continue
        pat = r"(?<![a-zA-Z])%s(?![a-zA-Z])" % re.escape(title)
        if re.search(pat, text, re.IGNORECASE):
            return type_id
    return None


class DeterministicEngine:
    name = "deterministic"

    def parse_to_change_spec(
        self,
        natural_language: str,
        site_code: str,
        inventory_ref: str,
        inventory_summary: Optional[dict] = None,
    ) -> Result:
        text = (natural_language or "").strip()
        if not text:
            return Result.failure("需求描述为空", code="CHANGE_SPEC_INVALID")

        known_types = (inventory_summary or {}).get("types") or {}

        type_id = _resolve_type_id(text, known_types)
        field_name = _extract_field_name(text)
        field_type = _infer_field_type(text)
        required = any(k in text.lower() or k in text for k in _REQUIRED_KEYWORDS)

        if not type_id:
            return Result.failure(
                "无法从描述中识别目标内容类型",
                code="CHANGE_SPEC_INVALID",
                suggestion="明确写出目标类型，如「为 AnalysisRequest 添加…」",
            )
        if not field_name:
            return Result.failure(
                "无法从描述中识别字段名",
                code="CHANGE_SPEC_INVALID",
                suggestion="写明字段名，如「名为 maitux_sample_code 的字段」",
            )

        framework = (known_types.get(type_id) or {}).get("framework", "unknown")

        changes = [
            {
                "changeType": "AddField",
                "description": "为 %s 添加%s字段 %s"
                % (type_id, "必填" if required else "", field_name),
                "typeId": type_id,
                "fieldName": field_name,
                "fieldType": field_type,
                "required": required,
                "framework": framework,
            }
        ]

        # 可选：识别「在列表视图显示」
        if any(k in text for k in _LISTING_KEYWORDS):
            changes.append(
                {
                    "changeType": "UpdateListing",
                    "description": "在 %s 列表视图显示 %s 列" % (type_id, field_name),
                    "typeId": type_id,
                    "addColumns": [field_name],
                    "removeColumns": [],
                }
            )

        spec = {
            "version": "1.0",
            "siteCode": site_code,
            "inventoryRef": inventory_ref,
            "changes": changes,
            "risks": [
                {"level": "low", "message": "仅新增字段/列表列，不影响现有数据"}
            ],
        }
        return Result.success(spec)
