"""端到端场景核对脚本（标准库 urllib，无第三方依赖）。

用法：先启动后端（./run.sh），再执行
    python3 tests/e2e_pipeline.py http://127.0.0.1:8016

按题目场景逐步核对：
  1. 一行编码 K7、金额 12.345、库存 0、备注空串且缺渠道的 JSON，目标金额两位小数；
  2. 分别运行「只取编码」和「引用金额」两个抽取模板；
  3. 核对能交付什么、哪格待修、是否错误套用默认值；
  4. 金额补正为 12.34 后重新提交，比对抽取结果；
  5. 重新打开先前拒绝记录，确认原值和字段位置仍可查。
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8016"

BAD_LINE = '{"编码": "K7", "金额": 12.345, "库存": 0, "备注": ""}'
FIXED_LINE = '{"编码": "K7", "金额": 12.34, "库存": 0, "备注": ""}'

TARGET_SCHEMA = [
    {"source_field": "编码", "target_field": "product_code", "type": "string"},
    {"source_field": "金额", "target_field": "amount", "type": "decimal", "scale": 2},
    {"source_field": "库存", "target_field": "stock", "type": "integer"},
    {"source_field": "备注", "target_field": "remark", "type": "string"},
    {"source_field": "渠道", "target_field": "channel", "type": "string", "nullable": True},
]

failures: list[str] = []


def call(method: str, path: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise AssertionError(f"{method} {path} 失败：{exc.code} {exc.read().decode('utf-8')}") from exc


def check(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"  [{mark}] {label}{(' —— ' + detail) if detail else ''}")
    if not condition:
        failures.append(label)


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> int:
    section("0. 健康检查")
    health = call("GET", "/api/health")
    check("后端在线且模块已加载", health.get("ok") is True, str(health.get("modules")))

    section("1. 登记两个抽取模板")
    code_template = call("POST", "/api/field_extractor", {"values": {
        "模板名称": "E2E只取商品编码", "源字段路径": "product_code",
        "目标字段名": "product_code", "默认值": ""}})
    check("编码模板登记成功", code_template["ok"], code_template["message"])
    code_id = code_template["entry"]["id"]

    amount_template = call("POST", "/api/field_extractor", {"values": {
        "模板名称": "E2E引用金额", "源字段路径": "amount",
        "目标字段名": "amount", "默认值": "0.00"}})
    check("金额模板登记成功（带默认值 0.00 用于反证）", amount_template["ok"])
    amount_id = amount_template["entry"]["id"]

    section("2. 首轮转换：金额 12.345 进入 decimal(2)")
    batch = call("POST", "/api/pipeline/conversions", {
        "raw_text": BAD_LINE, "target_schema": TARGET_SCHEMA,
        "source_name": "E2E首轮"})
    batch_id = batch["id"]
    row = batch["rows"][0]
    check("源行号=1 可定位", row["line_no"] == 1)
    check("编码 K7 转换成功可继续使用",
          row["converted_fields"].get("product_code") == "K7")
    check("库存 0 转换成功可继续使用",
          row["converted_fields"].get("stock") == 0)
    check("备注空串被保留为空串",
          row["converted_fields"].get("remark") == "")
    check("金额未被静默舍入（转换结果里没有 amount）",
          "amount" not in row["converted_fields"])
    rejected = row["rejected_cells"]
    check("恰好一格被拒", len(rejected) == 1)
    check("被拒格定位到源行1、源字段「金额」、目标字段 amount",
          rejected[0]["line_no"] == 1 and rejected[0]["source_field"] == "金额"
          and rejected[0]["target_field"] == "amount")
    check("拒绝原因是精度溢出且原值 12.345 完整保留",
          rejected[0]["reason"] == "precision_overflow"
          and rejected[0]["raw_value"] == 12.345, rejected[0]["detail"])
    channel_cell = next(c for c in row["cells"] if c["target_field"] == "channel")
    check("缺渠道被识别为真正缺字段而非转换失败",
          channel_cell["status"] == "missing" and channel_cell["reason"] is None)
    check("批次统计：1 行、1 格拒绝、0 行完全转换",
          batch["total_rows"] == 1 and batch["rejected_cell_count"] == 1
          and batch["fully_converted_row_count"] == 0)

    section("3. 模板A「只取编码」抽取")
    code_run = call("POST", "/api/pipeline/extractions",
                    {"template_id": code_id, "batch_id": batch_id})
    code_result = code_run["results"][0]
    check("编码可交付，值为 K7",
          code_result["status"] == "delivered" and code_result["value"] == "K7")
    check("未套用任何默认值", code_result["default_applied"] is False)

    section("4. 模板B「引用金额」抽取")
    amount_run = call("POST", "/api/pipeline/extractions",
                      {"template_id": amount_id, "batch_id": batch_id})
    amount_result = amount_run["results"][0]
    check("金额状态为待修 pending_fix 而非交付",
          amount_result["status"] == "pending_fix")
    check("没有交付任何金额值", amount_result["value"] is None)
    check("转换失败未触发缺字段默认值 0.00",
          amount_result["default_applied"] is False
          and amount_result["value"] != "0.00")
    check("待修结果带拒绝记录号与字段位置",
          amount_result["rejection_id"] is not None
          and amount_result["source_field"] == "金额"
          and amount_result["line_no"] == 1)

    section("5. 重新打开拒绝记录")
    rejection = call("GET", f"/api/pipeline/rejections/{amount_result['rejection_id']}")
    check("拒绝记录状态为待修", rejection["status"] == "待修")
    check("可定位源行1、字段「金额」",
          rejection["line_no"] == 1 and rejection["source_field"] == "金额")
    check("原值 12.345 与整行原始记录仍在",
          rejection["raw_value"] == 12.345
          and rejection["source_record"]["编码"] == "K7"
          and "渠道" not in rejection["source_record"])

    section("6. 金额补正为 12.34 后重新提交")
    fixed_batch = call("POST", f"/api/pipeline/conversions/{batch_id}/resubmit",
                       {"raw_text": FIXED_LINE})
    fixed_batch_id = fixed_batch["id"]
    check("新批次零拒绝", fixed_batch["rejected_cell_count"] == 0)
    check("新批次金额为 12.34",
          fixed_batch["rows"][0]["converted_fields"]["amount"] == "12.34")

    code_run2 = call("POST", "/api/pipeline/extractions",
                     {"template_id": code_id, "batch_id": fixed_batch_id})
    amount_run2 = call("POST", "/api/pipeline/extractions",
                       {"template_id": amount_id, "batch_id": fixed_batch_id})
    check("补正后编码仍交付 K7",
          code_run2["results"][0]["status"] == "delivered"
          and code_run2["results"][0]["value"] == "K7")
    check("补正后金额交付 12.34 且未用默认值",
          amount_run2["results"][0]["status"] == "delivered"
          and amount_run2["results"][0]["value"] == "12.34"
          and amount_run2["results"][0]["default_applied"] is False)

    section("7. 旧拒绝记录回溯")
    old_rejection = call("GET", f"/api/pipeline/rejections/{amount_result['rejection_id']}")
    check("旧记录已标记已补正并关联新批次",
          old_rejection["status"] == "已补正"
          and old_rejection["fixed_batch_id"] == fixed_batch_id)
    check("旧记录仍保留原值 12.345 与源行/字段位置",
          old_rejection["raw_value"] == 12.345
          and old_rejection["line_no"] == 1
          and old_rejection["source_field"] == "金额")
    old_batch = call("GET", f"/api/pipeline/conversions/{batch_id}")
    check("首轮批次现场未被覆盖（仍无 amount、拒绝原值仍在）",
          "amount" not in old_batch["rows"][0]["converted_fields"]
          and old_batch["rows"][0]["rejected_cells"][0]["raw_value"] == 12.345)

    print("\n" + ("全部核对通过 ✅" if not failures else f"存在 {len(failures)} 项失败 ❌"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
