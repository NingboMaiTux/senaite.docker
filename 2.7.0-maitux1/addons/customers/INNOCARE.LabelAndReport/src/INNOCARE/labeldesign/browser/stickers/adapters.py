# -*- coding: utf-8 -*-
# ADD(2026-08-21) - 标签模板适配器。
from senaite.core.interfaces.stickers import IGetStickerTemplates
from zope.interface import implementer


@implementer(IGetStickerTemplates)
class StockBatchLabelTemplates(object):
    """库存标签模板适配器。"""
    default_template = "INNOCARE.LabelAndReport:InventoryNormal_40x20mm.pt"

    def __init__(self, context):
        self.context = context

    def __call__(self, request):
        return [
            {
                "id": "INNOCARE.LabelAndReport:InventoryNormal_40x20mm.pt",
                "title": "库存标签 (Inventory Normal)",
            },
            {
                "id": "INNOCARE.LabelAndReport:InventoryReference_40x20mm.pt",
                "title": "库存标签·对照品 (Inventory Reference)",
            },
            {
                "id": "INNOCARE.LabelAndReport:InventoryStability_40x20mm.pt",
                "title": "库存标签·稳定性样品 (Inventory Stability)",
            },
        ]


@implementer(IGetStickerTemplates)
class SampleLabelTemplates(object):
    """样品标签模板适配器。"""
    default_template = "INNOCARE.LabelAndReport:SampleNormal_40x30mm.pt"

    def __init__(self, context):
        self.context = context

    def __call__(self, request):
        return [
            {
                "id": "INNOCARE.LabelAndReport:SampleNormal_40x30mm.pt",
                "title": "样品标签 (Sample Normal)",
            },
            {
                "id": "INNOCARE.LabelAndReport:SampleNormal_60x40mm.pt",
                "title": "样品标签·大号 60x40mm (Sample Normal 60x40mm)",
            },
            {
                "id": "INNOCARE.LabelAndReport:SampleStability_40x30mm.pt",
                "title": "样品标签·稳定性 (Sample Stability)",
            },
            {
                "id": "INNOCARE.LabelAndReport:SampleStability_60x40mm.pt",
                "title": "样品标签·稳定性大号 60x40mm (Sample Stability 60x40mm)",
            },
        ]
