"""格式适配器领域服务。

除通用的格式配置登记/流转外，这里承载离线 JSON 行到目标字段的转换管线：

- 按目标 Schema 把源单元格逐个转换成目标类型，高精度数值放不下时拒绝转换，
  绝不静默舍入（``precision_overflow``）；
- 转换后的目标字段与被拒绝的源单元格分开存放，且都带源行号、源字段名等定位信息；
- 「源记录里根本没有该单元格」与「单元格存在但转换失败」是两种不同状态，
  转换失败不会被伪装成缺字段，也不会触发字段抽取器的默认值。

转换批次与拒绝记录保存在独立的管线仓库（``pipeline_store``）里，
重新打开先前的拒绝记录仍能查到原始行和字段位置。
"""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any

from app.pipeline_store import pipeline_store
from app.services.base import BaseModuleService

# 单元格级状态：转换成功 / 源记录缺该字段 / 源值无法放进目标类型。
CELL_OK = "converted"
CELL_MISSING = "missing"
CELL_REJECTED = "rejected"

# 拒绝原因码。
REASON_PRECISION_OVERFLOW = "precision_overflow"
REASON_TYPE_MISMATCH = "type_mismatch"
REASON_EMPTY_NOT_NULLABLE = "empty_not_nullable"


class FormatAdapterService(BaseModuleService):
    MODULE = "format_adapter"
    ENTITY = "格式配置"
    OPERATION_TERM = "采集"
    LIST_FIELDS = ["配置名称", "输入格式", "输出格式", "Schema映射", "校验规则"]
    REQUIRED_FIELDS = ["配置名称", "输入格式", "输出格式"]
    STATUS_ORDER = ["待验证", "已验证", "已废弃"]
    ACTION_RULES = {"验证格式": "已验证", "废弃配置": "已废弃"}
    NEGATIVE_ACTIONS = []

    # ------------------------------------------------------------------
    # 离线 JSON 行解析
    # ------------------------------------------------------------------
    def parse_jsonl(self, raw_text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """把离线 JSONL 文本解析成记录列表，坏行单独返回而不是中断整批。

        行号从 1 开始，与数据人员在原始文件里看到的行号一致。
        """
        records: list[dict[str, Any]] = []
        bad_lines: list[dict[str, Any]] = []
        for line_no, line in enumerate(raw_text.splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                value = json.loads(stripped)
            except json.JSONDecodeError as exc:
                bad_lines.append({
                    "line_no": line_no,
                    "raw_line": stripped,
                    "reason": "invalid_json",
                    "detail": str(exc),
                })
                continue
            if not isinstance(value, dict):
                bad_lines.append({
                    "line_no": line_no,
                    "raw_line": stripped,
                    "reason": "not_an_object",
                    "detail": f"JSON 顶层是 {type(value).__name__}，期望对象",
                })
                continue
            records.append({"line_no": line_no, "record": value})
        return records, bad_lines

    # ------------------------------------------------------------------
    # 单元格级类型转换
    # ------------------------------------------------------------------
    def _convert_cell(self, raw_value: Any, target: dict[str, Any]) -> tuple[bool, Any, str, str]:
        """转换单个源单元格。

        返回 ``(是否成功, 转换后的值, 拒绝原因码, 说明)``。
        成功时原因码为 :data:`CELL_OK`；放不下目标类型时返回拒绝原因，
        调用方负责保留原值，本方法不做任何舍入或截断。
        """
        target_type = str(target.get("type", "string")).lower()
        nullable = bool(target.get("nullable", True))

        # 空串是真实存在的源值：字符串目标可以承接，其它类型则拒绝。
        if raw_value is None or (isinstance(raw_value, str) and raw_value == ""):
            if target_type == "string":
                return True, "" if raw_value == "" else None, CELL_OK, ""
            if raw_value is None and nullable:
                return True, None, CELL_OK, ""
            return (
                False,
                None,
                REASON_EMPTY_NOT_NULLABLE,
                f"空值无法写入非空 {target_type} 目标字段",
            )

        if target_type == "string":
            return True, str(raw_value), CELL_OK, ""

        if target_type == "integer":
            if isinstance(raw_value, bool):
                return False, None, REASON_TYPE_MISMATCH, "布尔值不能当作整数"
            if isinstance(raw_value, int):
                return True, raw_value, CELL_OK, ""
            try:
                text = str(raw_value).strip()
                decimal_value = Decimal(text)
            except (InvalidOperation, ValueError):
                return False, None, REASON_TYPE_MISMATCH, f"原值 {raw_value!r} 不是整数"
            if not decimal_value.to_integral_value() == decimal_value:
                return False, None, REASON_TYPE_MISMATCH, f"原值 {raw_value!r} 含小数部分，无法无损转为整数"
            return True, int(decimal_value), CELL_OK, ""

        if target_type in ("decimal", "number"):
            scale = int(target.get("scale", 2))
            try:
                decimal_value = Decimal(str(raw_value))
            except (InvalidOperation, ValueError):
                return False, None, REASON_TYPE_MISMATCH, f"原值 {raw_value!r} 不是数值"
            if not decimal_value.is_finite():
                return False, None, REASON_TYPE_MISMATCH, f"原值 {raw_value!r} 不是有限数值"
            # 关键约束：小数位超过目标精度时直接拒绝，绝不四舍五入。
            negative_scale = decimal_value.as_tuple().exponent
            source_digits = max(-negative_scale, 0) if isinstance(negative_scale, int) else 0
            if source_digits > scale:
                return (
                    False,
                    None,
                    REASON_PRECISION_OVERFLOW,
                    f"原值 {decimal_value} 有 {source_digits} 位小数，"
                    f"目标 {target_type}({scale}) 只能无损保留 {scale} 位，拒绝静默舍入",
                )
            quantized = decimal_value.quantize(Decimal(1).scaleb(-scale))
            if target_type == "number":
                return True, float(quantized), CELL_OK, ""
            return True, format(quantized, "f"), CELL_OK, ""

        return False, None, REASON_TYPE_MISMATCH, f"不支持的目标类型 {target_type!r}"

    def convert_record(
        self,
        line_no: int,
        record: dict[str, Any],
        target_schema: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """转换一条源记录，区分转换成功、真正缺字段与转换失败。"""
        converted: dict[str, Any] = {}
        cells: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        missing: list[dict[str, Any]] = []

        for target in target_schema:
            source_field = str(target["source_field"])
            target_field = str(target["target_field"])
            cell: dict[str, Any] = {
                "line_no": line_no,
                "source_field": source_field,
                "target_field": target_field,
                "target_type": target.get("type", "string"),
            }
            if source_field not in record:
                # 真正缺字段：源记录里就没有这个单元格，与转换失败严格区分。
                cell.update({
                    "status": CELL_MISSING,
                    "required": not bool(target.get("nullable", True)),
                    "raw_value": None,
                    "converted_value": None,
                    "reason": None,
                    "detail": "源记录缺少该字段",
                })
                missing.append(cell)
                cells.append(cell)
                continue

            raw_value = record[source_field]
            ok, converted_value, reason, detail = self._convert_cell(raw_value, target)
            cell.update({
                "raw_value": raw_value,
                "converted_value": converted_value if ok else None,
                "reason": None if ok else reason,
                "detail": detail,
                "required": not bool(target.get("nullable", True)),
            })
            if ok:
                cell["status"] = CELL_OK
                converted[target_field] = converted_value
            else:
                cell["status"] = CELL_REJECTED
                # 被拒绝的源单元格单独留档，原值完整保留以便补正。
                rejected.append({
                    "line_no": line_no,
                    "source_field": source_field,
                    "target_field": target_field,
                    "target_type": cell["target_type"],
                    "raw_value": raw_value,
                    "reason": reason,
                    "detail": detail,
                })
            cells.append(cell)

        return {
            "line_no": line_no,
            "source_record": record,
            "converted_fields": converted,
            "cells": cells,
            "rejected_cells": rejected,
            "missing_cells": missing,
            "convert_ok": not rejected,
        }

    # ------------------------------------------------------------------
    # 整批转换与持久化（待修结果关联原始行和字段位置）
    # ------------------------------------------------------------------
    def convert_batch(
        self,
        *,
        raw_text: str | None = None,
        records: list[dict[str, Any]] | None = None,
        target_schema: list[dict[str, Any]],
        config_id: int | None = None,
        source_name: str = "离线JSON行",
    ) -> dict[str, Any]:
        """转换一整批源记录并落库，返回带批次号的完整结果。"""
        if records is None:
            parsed_records, bad_lines = self.parse_jsonl(raw_text or "")
            indexed_records = parsed_records
        else:
            indexed_records = [
                {"line_no": idx, "record": record} for idx, record in enumerate(records, start=1)
            ]
            bad_lines = []

        rows = [
            self.convert_record(item["line_no"], item["record"], target_schema)
            for item in indexed_records
        ]
        batch = pipeline_store.save_conversion_batch(
            rows=rows,
            bad_lines=bad_lines,
            target_schema=target_schema,
            config_id=config_id,
            source_name=source_name,
        )
        return batch

    def resubmit_batch(
        self,
        *,
        previous_batch_id: int,
        raw_text: str | None = None,
        records: list[dict[str, Any]] | None = None,
        source_name: str | None = None,
    ) -> dict[str, Any]:
        """补正后重新提交同一批数据，生成新批次并回填先前拒绝记录的处理结果。

        旧批次和旧拒绝记录保持原样可查；同一 (源行号, 目标字段) 在新批次里
        转换成功的，旧拒绝记录标记为「已补正」并关联新批次，仍然放不下的保持「待修」。
        """
        previous = pipeline_store.get_conversion_batch(previous_batch_id)
        if previous is None:
            raise ValueError(f"转换批次 {previous_batch_id} 不存在")
        new_batch = self.convert_batch(
            raw_text=raw_text,
            records=records,
            target_schema=previous["target_schema"],
            config_id=previous["config_id"],
            source_name=source_name or f"{previous['source_name']}（补正重提）",
        )
        ok_cells = {
            (row["line_no"], cell["target_field"])
            for row in new_batch["rows"]
            for cell in row["cells"]
            if cell["status"] == CELL_OK
        }
        for ref in previous["rejections"]:
            rejection = pipeline_store.get_rejection(ref["rejection_id"])
            if rejection is None or rejection["status"] != "待修":
                continue
            key = (ref["line_no"], ref["target_field"])
            if key in ok_cells:
                fixed_row = next(
                    row for row in new_batch["rows"]
                    if row["line_no"] == ref["line_no"]
                )
                fixed_value = fixed_row["converted_fields"].get(ref["target_field"])
                pipeline_store.resolve_rejection(
                    ref["rejection_id"],
                    fixed_batch_id=new_batch["id"],
                    resolution=f"补正后转换成功，新值={fixed_value!r}",
                )
        new_batch["previous_batch_id"] = previous_batch_id
        pipeline_store.link_previous_batch(new_batch["id"], previous_batch_id)
        return new_batch

    def get_conversion_batch(self, batch_id: int) -> dict[str, Any] | None:
        return pipeline_store.get_conversion_batch(batch_id)

    def list_conversion_batches(self) -> list[dict[str, Any]]:
        return pipeline_store.list_conversion_batches()

    def get_rejection(self, rejection_id: int) -> dict[str, Any] | None:
        """重新打开先前的拒绝记录，仍可查到原始行和字段位置、原值。"""
        return pipeline_store.get_rejection(rejection_id)

    def list_rejections(self, *, only_open: bool = False) -> list[dict[str, Any]]:
        rejections = pipeline_store.list_rejections()
        if only_open:
            return [item for item in rejections if item["status"] == "待修"]
        return rejections
