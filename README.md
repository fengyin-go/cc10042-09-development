# 智能网页采集与数据抽取平台

面向结构化网页和API的多源数据采集、字段抽取、反爬对抗与采集质量治理平台

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/WorkbenchView.vue|tsx  全部模块共享工作台
│   ├── src/data/modules.ts              18个业务模块配置
│   ├── src/api/              统一请求封装
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/resource.py  通用查询/导出/登记/动作接口
│   ├── app/services/<key>.py    每个模块独立领域逻辑
│   ├── app/services/base.py     共享服务骨架
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8016/api/health`

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5196/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8016`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 采集项目 | `crawl_project` | 采集项目 | 项目名称、目标站点、采集频率 |
| 页面解析规则 | `page_parser` | 解析规则 | 规则名称、目标元素选择器、字段映射 |
| 字段抽取器 | `field_extractor` | 字段模板 | 模板名称、源字段路径、目标字段名 |
| 反爬对抗 | `anti_crawl` | 反爬策略 | 策略名称、代理池来源、请求头模板 |
| 采集去重中心 | `data_dedupe` | 去重规则 | 规则名称、去重维度、去重窗口 |
| 采集结果审计 | `result_audit` | 审计记录 | 采集批次、总条数、成功条数 |
| 采集限速 | `rate_limiter` | 限速规则 | 规则名称、最大QPS、并发连接数 |
| 采集调度器 | `scheduler` | 调度计划 | 计划名称、关联项目、Cron表达式 |
| RPA工作流 | `rpa_workflow` | 工作流 | 流程名称、操作步骤序列、目标应用 |
| 批量接入 | `batch_ingest` | 接入任务 | 任务名称、数据来源、文件格式 |
| 数据质量校验 | `data_quality` | 质量规则 | 规则名称、校验维度、阈值 |
| 日志采集 | `log_collector` | 日志采集器 | 采集器名称、日志路径、解析模式 |
| 代理池管理 | `proxy_pool` | 代理节点 | 代理地址、地理位置、响应延迟 |
| 格式适配器 | `format_adapter` | 格式配置 | 配置名称、输入格式、输出格式 |
| 转换抽取管线 | `pipeline`（前端页面 `/pipeline`，接口前缀 `/api/pipeline`） | 转换批次/拒绝记录/抽取结果 | 源行号、源字段、目标类型、拒绝原因 |
| 采集执行日志 | `extraction_log` | 执行日志 | 执行时间、关联项目、状态 |
| 页面变更监控 | `page_change` | 变更记录 | 目标页面、监测时间、变更类型 |
| 数据采样器 | `data_sample` | 采样方案 | 方案名称、采样方式、采样比例 |
| 采集导出中心 | `export_center` | 导出任务 | 导出范围、目标格式、导出时间 |
| 数据源注册 | `source_registry` | 数据源 | 数据源名称、源类型、连接配置 |
| 采集重试策略 | `retry_policy` | 重试规则 | 规则名称、最大重试次数、退避间隔 |

## 约定

- 全部模块共享`frontend/src/views/WorkbenchView.vue|tsx`和一套资源路由。
- 每个模块仍保留独立`backend/app/services/<模块>.py`；纯前端保留
  `frontend/src/domain/<模块>.ts`，用于承载真实业务差异并维持36题位容量。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 转换抽取管线（格式适配器 → 字段抽取器）

格式适配器除输入输出配置外，新增离线 JSON 行到目标字段的转换管线
（`backend/app/services/format_adapter.py` + `app/pipeline_store.py`），
字段抽取器（`field_extractor.py`）消费转换后的目标字段而不是直接读源 JSON：

- **不静默舍入**：数值小数位超过目标精度（如 `12.345` → `decimal(2)`）时
  拒绝该单元格，原因码 `precision_overflow`，原值完整留档。
- **两种「没有值」严格区分**：源记录缺字段记为 `missing`（可选字段不报错）；
  单元格存在但转换失败记为 `rejected`。转换失败不会触发抽取模板的缺字段默认值。
- **只交付可靠值**：抽取结果状态为 `delivered / defaulted / missing / pending_fix`，
  待修结果带 `rejection_id`、源行号和源字段名，可定位到原始行和具体字段。
- **补正可回溯**：补正后重提生成新批次并回填旧拒绝记录（`已补正` + 新批次号），
  旧批次与旧拒绝记录的原值保持不变，重新打开仍能查到原始行和字段。

接口前缀 `/api/pipeline`：`POST /conversions`、`POST /conversions/{id}/resubmit`、
`GET /conversions`、`GET /rejections[?only_open=true]`、`POST /extractions` 等，
前端在侧边栏「转换抽取管线」页面（`/pipeline`）操作。

测试与场景走查（后端目录下）：

```bash
python3 -m unittest discover -s tests          # 单元测试，仅依赖标准库
python3 tests/walkthrough_pipeline.py          # 服务层题目场景逐步走查
# 启动服务后：python3 tests/e2e_pipeline.py    # HTTP 端到端核对
```

领域：数据工程
子方向：数据采集、爬虫与RPA
