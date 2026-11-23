"""字段抽取器领域服务。

抽取模板消费格式适配器转换后的目标字段，而不是直接读源 JSON：

- ``delivered``：转换成功、精度可靠的值才会交付；
- ``missing``：源记录真正缺该字段，且模板没有配置默认值；
- ``defaulted``：源记录真正缺该字段，按模板配置套用了默认值（显式标注）；
- ``pending_fix``：源单元格存在但转换失败（例如金额精度溢出），
  该值不可信，不交付、也绝不触发缺字段默认值，只给出待修引用，
  通过 ``rejection_id`` / ``line_no`` / ``source_field`` 可定位回原始行和字段。
"""
from __future__ import annotations

from typing import Any

from app.pipeline_store import pipeline_store
from app.services.base import BaseModuleService
from app.services.format_adapter import CELL_MISSING, CELL_REJECTED
from app.store import store

# 抽取字段级状态。
FIELD_DELIVERED = "delivered"
FIELD_MISSING = "missing"
FIELD_DEFAULTED = "defaulted"
FIELD_PENDING_FIX = "pending_fix"


class FieldExtractorService(BaseModuleService):
    MODULE = "field_extractor"
    ENTITY = "字段模板"
    OPERATION_TERM = "清洗"
    LIST_FIELDS = ["模板名称", "源字段路径", "目标字段名", "清洗函数", "默认值"]
    REQUIRED_FIELDS = ["模板名称", "源字段路径", "目标字段名"]
    STATUS_ORDER = ["待验证", "已验证", "已废弃"]
    ACTION_RULES = {"验证字段": "已验证", "废弃模板": "已废弃"}
    NEGATIVE_ACTIONS = []

    def _find_cell(
        self, converted_row: dict[str, Any], target_field: str
    ) -> dict[str, Any] | None:
        for cell in converted_row.get("cells", []):
            if cell["target_field"] == target_field:
                return cell
        return None

    def extract_row(self, template: dict[str, Any], converted_row: dict[str, Any]) -> dict[str, Any]:
        """对一条转换后的记录执行单个抽取模板。"""
        # 模板的「源字段路径」指向适配器产出的目标字段名。
        source_path = str(template["源字段路径"])
        output_field = str(template["目标字段名"])
        default_value = template.get("默认值")
        has_default = default_value is not None and str(default_value).strip() != ""

        cell = self._find_cell(converted_row, source_path)
        base = {
            "line_no": converted_row["line_no"],
            "template_id": template["id"],
            "template_name": template["模板名称"],
            "source_path": source_path,
            "output_field": output_field,
        }
        if cell is None:
            return {
                **base,
                "status": FIELD_MISSING,
                "value": None,
                "detail": f"转换结果中不存在目标字段 {source_path}",
                "rejection_id": None,
                "source_field": None,
                "raw_value": None,
                "default_applied": False,
            }

        if cell["status"] == CELL_REJECTED:
            # 转换失败：值不可信，不交付；同时禁止套用缺字段默认值。
            # rejection_id 由 run_extraction 用批次拒绝索引回填。
            return {
                **base,
                "status": FIELD_PENDING_FIX,
                "value": None,
                "detail": cell["detail"],
                "reason": cell["reason"],
                "rejection_id": None,
                "source_field": cell["source_field"],
                "raw_value": cell["raw_value"],
                "default_applied": False,
            }

        if cell["status"] == CELL_MISSING:
            # 真正缺字段：只有这种情况才允许套用默认值，且必须显式标注。
            if has_default:
                return {
                    **base,
                    "status": FIELD_DEFAULTED,
                    "value": default_value,
                    "detail": "源记录缺少该字段，按模板默认值补位",
                    "rejection_id": None,
                    "source_field": cell["source_field"],
                    "raw_value": None,
                    "default_applied": True,
                }
            return {
                **base,
                "status": FIELD_MISSING,
                "value": None,
                "detail": "源记录缺少该字段且模板未配置默认值",
                "rejection_id": None,
                "source_field": cell["source_field"],
                "raw_value": None,
                "default_applied": False,
            }

        # 转换成功：只交付精度可靠的值。
        return {
            **base,
            "status": FIELD_DELIVERED,
            "value": converted_row["converted_fields"].get(source_path),
            "detail": "转换成功，值可无损表达",
            "rejection_id": None,
            "source_field": cell["source_field"],
            "raw_value": cell["raw_value"],
            "default_applied": False,
        }

    def run_extraction(
        self,
        *,
        template_id: int,
        batch_id: int,
    ) -> dict[str, Any]:
        """把一个抽取模板应用到一个转换批次的全部行。"""
        template = store.find(self.MODULE, template_id)
        if template is None:
            raise ValueError(f"字段模板 {template_id} 不存在")
        batch = pipeline_store.get_conversion_batch(batch_id)
        if batch is None:
            raise ValueError(f"转换批次 {batch_id} 不存在")

        # 建立 (line_no, target_field) -> rejection_id 索引，便于待修结果回溯。
        rejection_index: dict[tuple[int, str], int] = {}
        for ref in batch["rejections"]:
            rejection_index[(ref["line_no"], ref["target_field"])] = ref["rejection_id"]

        results: list[dict[str, Any]] = []
        for converted_row in batch["rows"]:
            result = self.extract_row(template, converted_row)
            if result["status"] == FIELD_PENDING_FIX:
                result["rejection_id"] = rejection_index.get(
                    (result["line_no"], result["source_path"])
                )
            results.append(result)

        run = {
            "template_id": template_id,
            "template_name": template["模板名称"],
            "batch_id": batch_id,
            "total_rows": len(results),
            "delivered_count": sum(1 for item in results if item["status"] == FIELD_DELIVERED),
            "pending_fix_count": sum(1 for item in results if item["status"] == FIELD_PENDING_FIX),
            "missing_count": sum(1 for item in results if item["status"] == FIELD_MISSING),
            "defaulted_count": sum(1 for item in results if item["status"] == FIELD_DEFAULTED),
            "results": results,
        }
        return pipeline_store.save_extraction_run(run)

    def get_extraction_run(self, run_id: int) -> dict[str, Any] | None:
        return pipeline_store.get_extraction_run(run_id)

    def list_extraction_runs(self) -> list[dict[str, Any]]:
        return pipeline_store.list_extraction_runs()
