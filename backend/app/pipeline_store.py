"""转换管线内存仓库：保存转换批次、拒绝记录和抽取结果。

与通用 :class:`~app.store.Store` 分开，避免污染 20 个业务模块的示例数据。
所有待修记录都带源行号（``line_no``）和源字段名（``source_field``），
重新打开拒绝记录即可定位到原始行与具体字段，并看到被拒绝时的原值。
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any


class PipelineStore:
    def __init__(self) -> None:
        self._conversion_batches: dict[int, dict[str, Any]] = {}
        self._rejections: dict[int, dict[str, Any]] = {}
        self._extraction_runs: dict[int, dict[str, Any]] = {}
        self._batch_seq = 0
        self._rejection_seq = 0
        self._run_seq = 0

    # ------------------------------------------------------------------
    # 转换批次
    # ------------------------------------------------------------------
    def save_conversion_batch(
        self,
        *,
        rows: list[dict[str, Any]],
        bad_lines: list[dict[str, Any]],
        target_schema: list[dict[str, Any]],
        config_id: int | None,
        source_name: str,
    ) -> dict[str, Any]:
        self._batch_seq += 1
        batch_id = self._batch_seq

        rejection_refs: list[dict[str, Any]] = []
        for row in rows:
            for cell in row["rejected_cells"]:
                self._rejection_seq += 1
                rejection_id = self._rejection_seq
                record = {
                    "id": rejection_id,
                    "batch_id": batch_id,
                    "status": "待修",
                    "line_no": cell["line_no"],
                    "source_field": cell["source_field"],
                    "target_field": cell["target_field"],
                    "target_type": cell["target_type"],
                    "raw_value": cell["raw_value"],
                    "reason": cell["reason"],
                    "detail": cell["detail"],
                    "source_record": deepcopy(row["source_record"]),
                    "resolution": None,
                    "fixed_batch_id": None,
                }
                self._rejections[rejection_id] = record
                rejection_refs.append({
                    "rejection_id": rejection_id,
                    "line_no": cell["line_no"],
                    "source_field": cell["source_field"],
                    "target_field": cell["target_field"],
                    "reason": cell["reason"],
                    "status": "待修",
                })

        rejected_line_set = {
            cell["line_no"] for row in rows for cell in row["rejected_cells"]
        }
        batch = {
            "id": batch_id,
            "source_name": source_name,
            "config_id": config_id,
            "target_schema": deepcopy(target_schema),
            "total_rows": len(rows),
            "bad_line_count": len(bad_lines),
            "rejected_row_count": len(rejected_line_set),
            "rejected_cell_count": len(rejection_refs),
            "fully_converted_row_count": sum(1 for row in rows if row["convert_ok"]),
            "rows": deepcopy(rows),
            "bad_lines": deepcopy(bad_lines),
            "rejections": rejection_refs,
        }
        self._conversion_batches[batch_id] = batch
        return deepcopy(batch)

    def get_conversion_batch(self, batch_id: int) -> dict[str, Any] | None:
        batch = self._conversion_batches.get(batch_id)
        return deepcopy(batch) if batch is not None else None

    def link_previous_batch(self, batch_id: int, previous_batch_id: int) -> None:
        batch = self._conversion_batches.get(batch_id)
        if batch is not None:
            batch["previous_batch_id"] = previous_batch_id

    def list_conversion_batches(self) -> list[dict[str, Any]]:
        summaries = []
        for batch in self._conversion_batches.values():
            summaries.append({
                key: batch[key]
                for key in (
                    "id", "source_name", "config_id", "total_rows", "bad_line_count",
                    "rejected_row_count", "rejected_cell_count",
                    "fully_converted_row_count",
                )
            })
        return deepcopy(summaries)

    # ------------------------------------------------------------------
    # 拒绝记录（待修结果，关联原始行和字段位置）
    # ------------------------------------------------------------------
    def list_rejections(self) -> list[dict[str, Any]]:
        return deepcopy(list(self._rejections.values()))

    def get_rejection(self, rejection_id: int) -> dict[str, Any] | None:
        record = self._rejections.get(rejection_id)
        return deepcopy(record) if record is not None else None

    def resolve_rejection(
        self, rejection_id: int, *, fixed_batch_id: int, resolution: str
    ) -> dict[str, Any] | None:
        record = self._rejections.get(rejection_id)
        if record is None:
            return None
        record["status"] = "已补正"
        record["fixed_batch_id"] = fixed_batch_id
        record["resolution"] = resolution
        for batch in self._conversion_batches.values():
            for ref in batch["rejections"]:
                if ref["rejection_id"] == rejection_id:
                    ref["status"] = "已补正"
                    ref["fixed_batch_id"] = fixed_batch_id
        return deepcopy(record)

    # ------------------------------------------------------------------
    # 抽取结果
    # ------------------------------------------------------------------
    def save_extraction_run(self, run: dict[str, Any]) -> dict[str, Any]:
        self._run_seq += 1
        run_id = self._run_seq
        record = {"id": run_id, **run}
        self._extraction_runs[run_id] = record
        return deepcopy(record)

    def get_extraction_run(self, run_id: int) -> dict[str, Any] | None:
        record = self._extraction_runs.get(run_id)
        return deepcopy(record) if record is not None else None

    def list_extraction_runs(self) -> list[dict[str, Any]]:
        return deepcopy(list(self._extraction_runs.values()))


pipeline_store = PipelineStore()
