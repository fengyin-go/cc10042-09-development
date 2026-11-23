"""业务路由汇总：通用资源路由 + 转换抽取管线路由。"""
from __future__ import annotations

from app.routers import pipeline, resource

ROUTERS = [resource, pipeline]
