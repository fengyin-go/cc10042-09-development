"""转换-抽取管线接口。

把「格式适配器 → 字段抽取器」的协作显式暴露成 HTTP 接口，
资源路由保持通用 CRUD 不变，管线专属动作集中在本文件。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services import SERVICES

router = APIRouter(prefix="/api/pipeline", tags=["转换抽取管线"])

adapter_service = SERVICES["format_adapter"]
extractor_service = SERVICES["field_extractor"]


class TargetFieldSpec(BaseModel):
    source_field: str
    target_field: str
    type: str = "string"
    scale: int | None = None
    nullable: bool = True


class ConvertPayload(BaseModel):
    raw_text: str | None = None
    records: list[dict[str, Any]] | None = None
    target_schema: list[TargetFieldSpec]
    config_id: int | None = None
    source_name: str = "离线JSON行"


class ResubmitPayload(BaseModel):
    raw_text: str | None = None
    records: list[dict[str, Any]] | None = None
    source_name: str | None = None


class ExtractionPayload(BaseModel):
    template_id: int
    batch_id: int


@router.post("/conversions")
def create_conversion(payload: ConvertPayload) -> dict[str, Any]:
    if not payload.raw_text and not payload.records:
        raise HTTPException(status_code=422, detail="raw_text 与 records 至少提供一个")
    schema = [item.model_dump() for item in payload.target_schema]
    return adapter_service.convert_batch(
        raw_text=payload.raw_text,
        records=payload.records,
        target_schema=schema,
        config_id=payload.config_id,
        source_name=payload.source_name,
    )


@router.get("/conversions")
def list_conversions() -> dict[str, Any]:
    items = adapter_service.list_conversion_batches()
    return {"items": items, "total": len(items)}


@router.get("/conversions/{batch_id}")
def get_conversion(batch_id: int) -> dict[str, Any]:
    batch = adapter_service.get_conversion_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail=f"转换批次 {batch_id} 不存在")
    return batch


@router.post("/conversions/{batch_id}/resubmit")
def resubmit_conversion(batch_id: int, payload: ResubmitPayload) -> dict[str, Any]:
    if not payload.raw_text and not payload.records:
        raise HTTPException(status_code=422, detail="raw_text 与 records 至少提供一个")
    try:
        return adapter_service.resubmit_batch(
            previous_batch_id=batch_id,
            raw_text=payload.raw_text,
            records=payload.records,
            source_name=payload.source_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/rejections")
def list_rejections(only_open: bool = False) -> dict[str, Any]:
    items = adapter_service.list_rejections(only_open=only_open)
    return {"items": items, "total": len(items)}


@router.get("/rejections/{rejection_id}")
def get_rejection(rejection_id: int) -> dict[str, Any]:
    record = adapter_service.get_rejection(rejection_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"拒绝记录 {rejection_id} 不存在")
    return record


@router.post("/extractions")
def run_extraction(payload: ExtractionPayload) -> dict[str, Any]:
    try:
        return extractor_service.run_extraction(
            template_id=payload.template_id, batch_id=payload.batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/extractions")
def list_extractions() -> dict[str, Any]:
    items = extractor_service.list_extraction_runs()
    return {"items": items, "total": len(items)}


@router.get("/extractions/{run_id}")
def get_extraction(run_id: int) -> dict[str, Any]:
    run = extractor_service.get_extraction_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"抽取结果 {run_id} 不存在")
    return run
