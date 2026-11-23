"""题目场景走查脚本（服务层，标准库即可运行，无需启动 HTTP 服务）。

用法：
    cd backend && python3 tests/walkthrough_pipeline.py

逐步复现：K7 / 12.345 / 库存0 / 备注空串 / 缺渠道，目标金额 decimal(2)，
两个抽取模板分别取编码和引用金额，再补正 12.34 重提并回溯旧拒绝记录。
"""
from __future__ import annotations

from app.pipeline_store import pipeline_store
from app.services import SERVICES

BAD_LINE = '{"编码": "K7", "金额": 12.345, "库存": 0, "备注": ""}'
FIXED_LINE = '{"编码": "K7", "金额": 12.34, "库存": 0, "备注": ""}'

TARGET_SCHEMA = [
    {"source_field": "编码", "target_field": "product_code", "type": "string"},
    {"source_field": "金额", "target_field": "amount", "type": "decimal", "scale": 2},
    {"source_field": "库存", "target_field": "stock", "type": "integer"},
    {"source_field": "备注", "target_field": "remark", "type": "string"},
    {"source_field": "渠道", "target_field": "channel", "type": "string", "nullable": True},
]


def show(title: str) -> None:
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


def main() -> None:
    pipeline_store.__init__()
    adapter = SERVICES["format_adapter"]
    extractor = SERVICES["field_extractor"]

    show("准备：登记两个抽取模板（金额模板故意带默认值 0.00）")
    code_template, _ = extractor.create_entry({
        "模板名称": "只取商品编码", "源字段路径": "product_code",
        "目标字段名": "product_code", "默认值": ""})
    amount_template, _ = extractor.create_entry({
        "模板名称": "引用金额", "源字段路径": "amount",
        "目标字段名": "amount", "默认值": "0.00"})
    print(f"  编码模板 id={code_template['id']}，金额模板 id={amount_template['id']}")

    show("第一步：转换首轮 JSON 行（金额 12.345 → decimal(2)）")
    batch = adapter.convert_batch(
        raw_text=BAD_LINE, target_schema=TARGET_SCHEMA, source_name="题目首轮")
    row = batch["rows"][0]
    print(f"  批次号={batch['id']}，源行号={row['line_no']}")
    print(f"  转换成功的目标字段（补正前仍可用）：{row['converted_fields']}")
    for cell in row["cells"]:
        print(f"    - {cell['source_field']} → {cell['target_field']}: "
              f"状态={cell['status']}, 原值={cell['raw_value']!r}, "
              f"转换值={cell['converted_value']!r}, 说明={cell['detail']}")
    rejected = row["rejected_cells"][0]
    print(f"  放不下的单元格：源行{rejected['line_no']} 的「{rejected['source_field']}」"
          f"原值 {rejected['raw_value']}，原因={rejected['reason']}")
    print(f"  缺渠道被标记为：{next(c['status'] for c in row['cells'] if c['target_field'] == 'channel')}"
          "（真正缺字段，不是转换失败）")

    show("第二步：模板A「只取商品编码」抽取")
    code_run = extractor.run_extraction(template_id=code_template["id"], batch_id=batch["id"])
    result = code_run["results"][0]
    print(f"  状态={result['status']}，交付值={result['value']!r}，"
          f"是否套用默认值={result['default_applied']}")

    show("第三步：模板B「引用金额」抽取（验证不会静默舍入、不会错套默认值）")
    amount_run = extractor.run_extraction(template_id=amount_template["id"], batch_id=batch["id"])
    result = amount_run["results"][0]
    print(f"  状态={result['status']}，交付值={result['value']!r}，"
          f"是否套用默认值={result['default_applied']}（默认值 0.00 未被使用）")
    print(f"  待修定位：拒绝记录 id={result['rejection_id']}，"
          f"源行={result['line_no']}，源字段={result['source_field']}，原值={result['raw_value']}")

    show("第四步：重新打开拒绝记录（原始行与字段位置、原值）")
    rejection = adapter.get_rejection(result["rejection_id"])
    print(f"  拒绝记录 #{rejection['id']} 状态={rejection['status']}")
    print(f"  定位：源行 {rejection['line_no']}，源字段「{rejection['source_field']}」"
          f"→ 目标字段 {rejection['target_field']} {rejection['target_type']}")
    print(f"  被拒原值={rejection['raw_value']!r}")
    print(f"  原始整行={rejection['source_record']}")

    show("第五步：金额补正为 12.34，重新提交这一行")
    fixed_batch = adapter.resubmit_batch(previous_batch_id=batch["id"], raw_text=FIXED_LINE)
    print(f"  新批次号={fixed_batch['id']}，拒绝单元格数={fixed_batch['rejected_cell_count']}，"
          f"转换字段={fixed_batch['rows'][0]['converted_fields']}")

    show("第六步：对新批次重跑两个模板并比对")
    for template in (code_template, amount_template):
        run = extractor.run_extraction(template_id=template["id"], batch_id=fixed_batch["id"])
        item = run["results"][0]
        print(f"  {template['模板名称']}: 状态={item['status']}，"
              f"交付值={item['value']!r}，默认值={item['default_applied']}")

    show("第七步：再次打开先前的拒绝记录（补正后仍可回溯原值）")
    old = adapter.get_rejection(rejection["id"])
    print(f"  拒绝记录 #{old['id']} 状态={old['status']}，"
          f"原值仍为={old['raw_value']!r}，源行={old['line_no']}，"
          f"源字段={old['source_field']}，补正批次=#{old['fixed_batch_id']}")
    print(f"  补正说明：{old['resolution']}")
    print("\n走查完成。")


if __name__ == "__main__":
    main()
