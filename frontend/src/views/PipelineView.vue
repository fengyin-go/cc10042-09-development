<template>
  <section class="page pipeline-page">
    <header class="page-head">
      <div>
        <h2>转换抽取管线</h2>
        <p class="page-desc">
          格式适配器把离线 JSON 行转成目标字段，高精度放不下的单元格拒绝转换并留档；
          字段抽取器只交付精度可靠的值，转换失败不套用缺字段默认值。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" data-testid="load-demo" @click="fillDemo">
          填入题目演示行
        </button>
      </div>
    </header>

    <div class="pipeline-grid">
      <!-- 左栏：输入与 Schema -->
      <article class="analysis-card">
        <h3>① 离线 JSON 行与目标 Schema</h3>
        <label class="create-field">
          <span>来源名称</span>
          <input v-model="sourceName" data-testid="source-name" />
        </label>
        <label class="create-field">
          <span>JSONL 输入（每行一条 JSON 对象）</span>
          <textarea
            v-model="rawText"
            class="json-input"
            data-testid="raw-json"
            rows="6"
          ></textarea>
        </label>

        <table class="data-table schema-table">
          <thead>
            <tr><th>源字段</th><th>目标字段</th><th>目标类型</th><th>小数位</th><th>可空</th></tr>
          </thead>
          <tbody>
            <tr v-for="(spec, index) in schemaSpecs" :key="index">
              <td><input v-model="spec.source_field" :data-testid="`schema-source-${index}`" /></td>
              <td><input v-model="spec.target_field" :data-testid="`schema-target-${index}`" /></td>
              <td>
                <select v-model="spec.type">
                  <option value="string">string</option>
                  <option value="decimal">decimal</option>
                  <option value="number">number</option>
                  <option value="integer">integer</option>
                </select>
              </td>
              <td>
                <input
                  v-model.number="spec.scale"
                  type="number"
                  min="0"
                  :disabled="spec.type !== 'decimal' && spec.type !== 'number'"
                />
              </td>
              <td><input v-model="spec.nullable" type="checkbox" /></td>
            </tr>
          </tbody>
        </table>
        <div class="page-actions">
          <button class="btn primary" type="button" data-testid="run-convert" @click="submitConvert">
            执行格式转换
          </button>
        </div>
      </article>

      <!-- 右栏：转换结果 -->
      <article class="analysis-card">
        <h3>② 转换结果（目标字段与被拒绝的源单元格分开存放）</h3>
        <p v-if="errorMessage" class="error-text" data-testid="pipeline-error">{{ errorMessage }}</p>
        <p v-if="!batch" class="empty-state">尚未执行转换。</p>
        <template v-else>
          <p class="status-legend" data-testid="batch-summary">
            <span class="legend-item">批次 #{{ batch.id }}</span>
            <span class="legend-item">总行数：{{ batch.total_rows }}</span>
            <span class="legend-item">完全转换：{{ batch.fully_converted_row_count }}</span>
            <span class="legend-item">拒绝单元格：{{ batch.rejected_cell_count }}</span>
            <span class="legend-item">坏行：{{ batch.bad_line_count }}</span>
            <span v-if="batch.previous_batch_id" class="legend-item">
              补正自批次 #{{ batch.previous_batch_id }}
            </span>
          </p>

          <div v-for="row in batch.rows" :key="row.line_no" class="row-block" :data-testid="`conv-row-${row.line_no}`">
            <h4>源行 {{ row.line_no }} —— {{ row.convert_ok ? '全部可转换' : '存在待修单元格' }}</h4>
            <table class="data-table">
              <thead>
                <tr>
                  <th>源字段</th><th>目标字段</th><th>原值</th><th>转换后</th><th>单元格状态</th><th>说明</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="cell in row.cells"
                  :key="cell.target_field"
                  :data-testid="`cell-${row.line_no}-${cell.target_field}`"
                  :data-status="cell.status"
                  :class="{ 'cell-rejected': cell.status === 'rejected', 'cell-missing': cell.status === 'missing' }"
                >
                  <td>{{ cell.source_field }}</td>
                  <td>{{ cell.target_field }}</td>
                  <td>{{ displayValue(cell.raw_value) }}</td>
                  <td>{{ displayValue(cell.converted_value) }}</td>
                  <td>{{ statusLabel(cell.status) }}</td>
                  <td>{{ cell.detail }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
      </article>
    </div>

    <!-- 抽取区 -->
    <article v-if="batch" class="analysis-card">
      <h3>③ 交给字段抽取器（按模板区分真正缺字段与转换失败）</h3>
      <div class="filter-bar">
        <label class="filter-item">
          <span>抽取模板</span>
          <select v-model="selectedTemplateId" data-testid="template-select">
            <option v-for="item in templates" :key="item.id" :value="item.id">
              #{{ item.id }} {{ item['模板名称'] }}（读 {{ item['源字段路径'] }}，默认值：{{ item['默认值'] || '无' }}）
            </option>
          </select>
        </label>
        <button class="btn primary" type="button" data-testid="run-extract" @click="submitExtract">
          运行抽取
        </button>
        <button class="btn ghost" type="button" data-testid="resubmit" @click="submitResubmit">
          按当前 JSONL 补正重提
        </button>
      </div>

      <table v-if="extractionRun" class="data-table" data-testid="extraction-table">
        <thead>
          <tr>
            <th>源行</th><th>输出字段</th><th>状态</th><th>交付值</th>
            <th>是否默认值</th><th>待修定位</th><th>说明</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="result in extractionRun.results"
            :key="result.line_no"
            :data-testid="`extract-result-${result.line_no}`"
            :data-status="result.status"
          >
            <td>{{ result.line_no }}</td>
            <td>{{ result.output_field }}</td>
            <td>{{ extractionStatusLabel(result.status) }}</td>
            <td>{{ displayValue(result.value) }}</td>
            <td>{{ result.default_applied ? '是（缺字段补位）' : '否' }}</td>
            <td>
              <template v-if="result.rejection_id">
                <button class="link" type="button" @click="openRejection(result.rejection_id)">
                  拒绝记录 #{{ result.rejection_id }}（行{{ result.line_no }} · {{ result.source_field }}）
                </button>
              </template>
              <span v-else>—</span>
            </td>
            <td>{{ result.detail }}</td>
          </tr>
        </tbody>
      </table>
    </article>

    <!-- 拒绝记录抽屉 -->
    <article v-if="batch" class="analysis-card">
      <h3>④ 待修 / 拒绝记录（关联原始行与字段位置，可重新打开）</h3>
      <table class="data-table" data-testid="rejection-table">
        <thead>
          <tr>
            <th>记录号</th><th>批次</th><th>源行</th><th>源字段</th><th>目标字段</th>
            <th>原值</th><th>原因</th><th>状态</th><th>补正批次</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in rejections" :key="item.id" :data-testid="`rejection-${item.id}`">
            <td>#{{ item.id }}</td>
            <td>#{{ item.batch_id }}</td>
            <td>{{ item.line_no }}</td>
            <td>{{ item.source_field }}</td>
            <td>{{ item.target_field }}</td>
            <td>{{ displayValue(item.raw_value) }}</td>
            <td>{{ item.reason }}</td>
            <td>{{ item.status }}</td>
            <td>{{ item.fixed_batch_id ? `#${item.fixed_batch_id}` : '—' }}</td>
            <td><button class="link" type="button" @click="openRejection(item.id)">查看原值</button></td>
          </tr>
          <tr v-if="!rejections.length">
            <td colspan="10" class="empty-state">暂无拒绝记录</td>
          </tr>
        </tbody>
      </table>
    </article>

    <div v-if="activeRejection" class="modal-backdrop" data-testid="rejection-modal" @click.self="activeRejection = null">
      <div class="modal">
        <h3>拒绝记录 #{{ activeRejection.id }}（{{ activeRejection.status }}）</h3>
        <p class="status-legend">
          <span class="legend-item">源行：{{ activeRejection.line_no }}</span>
          <span class="legend-item">源字段：{{ activeRejection.source_field }}</span>
          <span class="legend-item">目标字段：{{ activeRejection.target_field }}</span>
          <span class="legend-item">目标类型：{{ activeRejection.target_type }}</span>
        </p>
        <p><strong>被拒绝的原值：</strong>{{ displayValue(activeRejection.raw_value) }}</p>
        <p><strong>原因：</strong>{{ activeRejection.detail }}</p>
        <p><strong>补正说明：</strong>{{ activeRejection.resolution || '尚未补正' }}</p>
        <pre class="raw-record" data-testid="rejection-raw-record">{{ JSON.stringify(activeRejection.source_record, null, 2) }}</pre>
        <div class="page-actions">
          <button class="btn primary" type="button" @click="activeRejection = null">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { listEntries } from '@/api/backend-service'
import {
  convertBatch,
  getRejection,
  listRejections,
  resubmitBatch,
  runExtraction,
  type ConversionBatch,
  type ExtractionRun,
  type Rejection,
  type TargetFieldSpec,
} from '@/api/pipeline'
import type { EntryRow } from '@/data/types'

const DEMO_LINE = '{"编码": "K7", "金额": 12.345, "库存": 0, "备注": ""}'

const DEMO_SCHEMA: TargetFieldSpec[] = [
  { source_field: '编码', target_field: 'product_code', type: 'string', scale: null, nullable: false },
  { source_field: '金额', target_field: 'amount', type: 'decimal', scale: 2, nullable: false },
  { source_field: '库存', target_field: 'stock', type: 'integer', scale: null, nullable: true },
  { source_field: '备注', target_field: 'remark', type: 'string', scale: null, nullable: true },
  { source_field: '渠道', target_field: 'channel', type: 'string', scale: null, nullable: true },
]

const sourceName = ref('题目演示数据')
const rawText = ref(DEMO_LINE)
const schemaSpecs = ref<TargetFieldSpec[]>(DEMO_SCHEMA.map((item) => ({ ...item })))
const templates = ref<EntryRow[]>([])
const selectedTemplateId = ref<number | null>(null)
const batch = ref<ConversionBatch | null>(null)
const extractionRun = ref<ExtractionRun | null>(null)
const rejections = ref<Rejection[]>([])
const activeRejection = ref<Rejection | null>(null)
const errorMessage = ref('')

function displayValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (value === '') return '（空串）'
  return String(value)
}

function statusLabel(status: string): string {
  return { converted: '转换成功', missing: '真正缺字段', rejected: '转换失败·待修' }[status] ?? status
}

function extractionStatusLabel(status: string): string {
  return {
    delivered: '已交付（精度可靠）',
    pending_fix: '待修（转换失败，未套默认值）',
    missing: '缺字段（无默认值）',
    defaulted: '缺字段（已套默认值）',
  }[status] ?? status
}

function fillDemo() {
  sourceName.value = '题目演示数据'
  rawText.value = DEMO_LINE
  schemaSpecs.value = DEMO_SCHEMA.map((item) => ({ ...item }))
  errorMessage.value = ''
}

async function refreshRejections() {
  const payload = await listRejections()
  rejections.value = payload.items
}

async function submitConvert() {
  errorMessage.value = ''
  try {
    batch.value = await convertBatch({
      raw_text: rawText.value,
      target_schema: schemaSpecs.value,
      source_name: sourceName.value,
    })
    extractionRun.value = null
    await refreshRejections()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '转换失败'
  }
}

async function submitResubmit() {
  if (!batch.value) return
  errorMessage.value = ''
  try {
    batch.value = await resubmitBatch(batch.value.id, { raw_text: rawText.value })
    extractionRun.value = null
    await refreshRejections()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '补正重提失败'
  }
}

async function submitExtract() {
  if (!batch.value || selectedTemplateId.value === null) return
  errorMessage.value = ''
  try {
    extractionRun.value = await runExtraction({
      template_id: selectedTemplateId.value,
      batch_id: batch.value.id,
    })
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '抽取失败'
  }
}

async function openRejection(rejectionId: number) {
  activeRejection.value = await getRejection(rejectionId)
}

onMounted(async () => {
  const payload = await listEntries('field_extractor')
  templates.value = payload.items
  if (templates.value.length) selectedTemplateId.value = Number(templates.value[0].id)
  await refreshRejections()
})
</script>

<style scoped>
.pipeline-grid {
  display: grid;
  grid-template-columns: minmax(320px, 1fr) minmax(360px, 1.2fr);
  gap: 16px;
}

.json-input {
  width: 100%;
  font-family: 'SFMono-Regular', Consolas, monospace;
}

.schema-table input,
.schema-table select {
  width: 100%;
}

.row-block {
  margin-bottom: 16px;
}

.cell-rejected {
  background: rgba(220, 53, 69, 0.12);
}

.cell-missing {
  background: rgba(255, 193, 7, 0.12);
}

.raw-record {
  background: #f5f6f8;
  padding: 12px;
  border-radius: 6px;
  max-height: 260px;
  overflow: auto;
}

@media (max-width: 1100px) {
  .pipeline-grid {
    grid-template-columns: 1fr;
  }
}
</style>
