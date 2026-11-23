"""转换-抽取管线的单元测试（仅依赖标准库，直接用 unittest 运行）。

覆盖题目要求的全部不变量：
- 高精度数值无法无损表达时拒绝转换、绝不静默舍入；
- 转换失败与真正缺字段是两种状态，失败不触发缺字段默认值；
- 只交付精度可靠的值，待修结果能定位到源行和具体字段；
- 补正重提后旧拒绝记录仍可查到原值、原始行与字段位置。
"""
from __future__ import annotations

import unittest

from app.pipeline_store import pipeline_store
from app.services import SERVICES
from app.services.field_extractor import (
    FIELD_DEFAULTED,
    FIELD_DELIVERED,
    FIELD_MISSING,
    FIELD_PENDING_FIX,
)
from app.services.format_adapter import (
    CELL_MISSING,
    CELL_OK,
    CELL_REJECTED,
    REASON_PRECISION_OVERFLOW,
)

BAD_LINE = '{"编码": "K7", "金额": 12.345, "库存": 0, "备注": ""}'
FIXED_LINE = '{"编码": "K7", "金额": 12.34, "库存": 0, "备注": ""}'

TARGET_SCHEMA = [
    {"source_field": "编码", "target_field": "product_code", "type": "string"},
    {"source_field": "金额", "target_field": "amount", "type": "decimal", "scale": 2},
    {"source_field": "库存", "target_field": "stock", "type": "integer"},
    {"source_field": "备注", "target_field": "remark", "type": "string"},
    {"source_field": "渠道", "target_field": "channel", "type": "string", "nullable": True},
]


class PipelineTestCase(unittest.TestCase):
    def setUp(self) -> None:
        # 重置单例仓库，避免批次/拒绝 ID 在不同用例间串扰。
        pipeline_store.__init__()
        self.adapter = SERVICES["format_adapter"]
        self.extractor = SERVICES["field_extractor"]

        code_template, missing = self.extractor.create_entry({
            "模板名称": "只取商品编码",
            "源字段路径": "product_code",
            "目标字段名": "product_code",
            "默认值": "",
        })
        self.assertFalse(missing)
        self.code_template_id = code_template["id"]

        amount_template, missing = self.extractor.create_entry({
            "模板名称": "引用金额",
            "源字段路径": "amount",
            "目标字段名": "amount",
            # 故意配置默认值，用来证明转换失败时不会错误套用默认值。
            "默认值": "0.00",
        })
        self.assertFalse(missing)
        self.amount_template_id = amount_template["id"]

    # ------------------------------------------------------------------
    def test_precision_overflow_is_rejected_not_rounded(self) -> None:
        batch = self.adapter.convert_batch(
            raw_text=BAD_LINE, target_schema=TARGET_SCHEMA, source_name="精度冲突样例")
        row = batch["rows"][0]

        self.assertEqual(row["line_no"], 1)
        # 能放下的字段照常转换，补正前这些值仍然可用。
        self.assertEqual(row["converted_fields"]["product_code"], "K7")
        self.assertEqual(row["converted_fields"]["stock"], 0)
        self.assertEqual(row["converted_fields"]["remark"], "")
        # 金额绝不能被悄悄舍入成 12.34 或 12.35。
        self.assertNotIn("amount", row["converted_fields"])
        self.assertFalse(row["convert_ok"])

        rejected = row["rejected_cells"]
        self.assertEqual(len(rejected), 1)
        cell = rejected[0]
        self.assertEqual(cell["source_field"], "金额")
        self.assertEqual(cell["target_field"], "amount")
        self.assertEqual(cell["line_no"], 1)
        self.assertEqual(cell["reason"], REASON_PRECISION_OVERFLOW)
        self.assertEqual(cell["raw_value"], 12.345)

        statuses = {c["target_field"]: c["status"] for c in row["cells"]}
        self.assertEqual(statuses["amount"], CELL_REJECTED)
        self.assertEqual(statuses["product_code"], CELL_OK)
        # 缺渠道是真正缺字段，不能被记成转换失败。
        self.assertEqual(statuses["channel"], CELL_MISSING)
        missing_cell = next(c for c in row["cells"] if c["target_field"] == "channel")
        self.assertFalse(missing_cell["required"])
        self.assertIsNone(missing_cell["reason"])

    def test_extraction_distinguishes_failure_from_missing(self) -> None:
        batch = self.adapter.convert_batch(
            raw_text=BAD_LINE, target_schema=TARGET_SCHEMA, source_name="精度冲突样例")

        code_run = self.extractor.run_extraction(
            template_id=self.code_template_id, batch_id=batch["id"])
        self.assertEqual(code_run["delivered_count"], 1)
        code_result = code_run["results"][0]
        self.assertEqual(code_result["status"], FIELD_DELIVERED)
        self.assertEqual(code_result["value"], "K7")
        self.assertFalse(code_result["default_applied"])

        amount_run = self.extractor.run_extraction(
            template_id=self.amount_template_id, batch_id=batch["id"])
        self.assertEqual(amount_run["delivered_count"], 0)
        self.assertEqual(amount_run["pending_fix_count"], 1)
        amount_result = amount_run["results"][0]
        self.assertEqual(amount_result["status"], FIELD_PENDING_FIX)
        self.assertIsNone(amount_result["value"])
        # 关键：转换失败不触发缺字段默认值 0.00。
        self.assertFalse(amount_result["default_applied"])
        self.assertNotEqual(amount_result["value"], "0.00")
        self.assertEqual(amount_result["raw_value"], 12.345)
        self.assertEqual(amount_result["source_field"], "金额")
        self.assertEqual(amount_result["line_no"], 1)
        self.assertIsNotNone(amount_result["rejection_id"])

        # 待修记录可以定位回原始行和具体字段，并保留整行原值。
        rejection = self.adapter.get_rejection(amount_result["rejection_id"])
        self.assertEqual(rejection["status"], "待修")
        self.assertEqual(rejection["line_no"], 1)
        self.assertEqual(rejection["source_field"], "金额")
        self.assertEqual(rejection["raw_value"], 12.345)
        self.assertEqual(rejection["source_record"]["编码"], "K7")
        self.assertEqual(rejection["source_record"]["金额"], 12.345)

    def test_default_value_only_applies_to_real_missing(self) -> None:
        # 给可选字段渠道配一个带默认值的模板：真正缺字段才允许默认值补位。
        channel_template, _ = self.extractor.create_entry({
            "模板名称": "补渠道",
            "源字段路径": "channel",
            "目标字段名": "channel",
            "默认值": "ONLINE",
        })
        batch = self.adapter.convert_batch(
            raw_text=BAD_LINE, target_schema=TARGET_SCHEMA, source_name="缺字段样例")
        channel_run = self.extractor.run_extraction(
            template_id=channel_template["id"], batch_id=batch["id"])
        result = channel_run["results"][0]
        self.assertEqual(result["status"], FIELD_DEFAULTED)
        self.assertEqual(result["value"], "ONLINE")
        self.assertTrue(result["default_applied"])

        # 没有默认值且真正缺字段时，状态是 missing 而不是 pending_fix。
        no_default_template, _ = self.extractor.create_entry({
            "模板名称": "补渠道无默认",
            "源字段路径": "channel",
            "目标字段名": "channel",
        })
        run = self.extractor.run_extraction(
            template_id=no_default_template["id"], batch_id=batch["id"])
        self.assertEqual(run["results"][0]["status"], FIELD_MISSING)
        self.assertFalse(run["results"][0]["default_applied"])

    def test_resubmit_fixes_value_and_keeps_old_rejection_traceable(self) -> None:
        first_batch = self.adapter.convert_batch(
            raw_text=BAD_LINE, target_schema=TARGET_SCHEMA, source_name="首轮提交")
        first_run = self.extractor.run_extraction(
            template_id=self.amount_template_id, batch_id=first_batch["id"])
        rejection_id = first_run["results"][0]["rejection_id"]
        self.assertIsNotNone(rejection_id)

        second_batch = self.adapter.resubmit_batch(
            previous_batch_id=first_batch["id"], raw_text=FIXED_LINE)
        self.assertEqual(second_batch["rejected_cell_count"], 0)
        fixed_row = second_batch["rows"][0]
        self.assertEqual(fixed_row["converted_fields"]["amount"], "12.34")
        self.assertTrue(fixed_row["convert_ok"])

        code_run = self.extractor.run_extraction(
            template_id=self.code_template_id, batch_id=second_batch["id"])
        self.assertEqual(code_run["results"][0]["status"], FIELD_DELIVERED)
        self.assertEqual(code_run["results"][0]["value"], "K7")
        amount_run = self.extractor.run_extraction(
            template_id=self.amount_template_id, batch_id=second_batch["id"])
        self.assertEqual(amount_run["results"][0]["status"], FIELD_DELIVERED)
        self.assertEqual(amount_run["results"][0]["value"], "12.34")
        self.assertFalse(amount_run["results"][0]["default_applied"])

        # 重新打开先前的拒绝记录：原值、原始行、字段位置都还在，且已关联补正批次。
        old_rejection = self.adapter.get_rejection(rejection_id)
        self.assertEqual(old_rejection["status"], "已补正")
        self.assertEqual(old_rejection["raw_value"], 12.345)
        self.assertEqual(old_rejection["line_no"], 1)
        self.assertEqual(old_rejection["source_field"], "金额")
        self.assertEqual(old_rejection["fixed_batch_id"], second_batch["id"])
        self.assertEqual(old_rejection["source_record"]["金额"], 12.345)

        # 首轮批次不可变，仍保留当时的拒绝现场。
        old_batch = self.adapter.get_conversion_batch(first_batch["id"])
        self.assertEqual(old_batch["rows"][0]["rejected_cells"][0]["raw_value"], 12.345)
        self.assertNotIn("amount", old_batch["rows"][0]["converted_fields"])

    def test_bad_json_line_is_reported_with_line_number(self) -> None:
        raw = BAD_LINE + "\n{这不是合法JSON}\n" + FIXED_LINE
        batch = self.adapter.convert_batch(
            raw_text=raw, target_schema=TARGET_SCHEMA, source_name="坏行样例")
        self.assertEqual(batch["total_rows"], 2)
        self.assertEqual(batch["bad_line_count"], 1)
        self.assertEqual(batch["bad_lines"][0]["line_no"], 2)
        self.assertEqual(batch["bad_lines"][0]["reason"], "invalid_json")


if __name__ == "__main__":
    unittest.main()
