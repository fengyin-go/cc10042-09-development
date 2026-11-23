<template>
  <div class="app-shell">
    <aside class="app-side">
      <h1 class="app-title">智能网页采集与数据抽取平台</h1>
      <nav class="nav-list">
        <RouterLink v-for="item in navItems" :key="item.path" :to="item.path" class="nav-item">
          {{ item.label }}
        </RouterLink>
      </nav>
    </aside>
    <main class="app-main">
      <header class="app-head">
        <span class="head-desc">面向结构化网页和API的多源数据采集、字段抽取、反爬对抗与采集质量治理平台</span>
        <span class="head-user">当前值班：数据工程组</span>
      </header>
      <RouterView />
    </main>
  </div>
</template>

<script setup lang="ts">
const navItems = [{ label: "运营概览", path: "/" }, { label: "采集项目", path: "/crawl_project" }, { label: "页面解析规则", path: "/page_parser" }, { label: "字段抽取器", path: "/field_extractor" }, { label: "反爬对抗", path: "/anti_crawl" }, { label: "采集去重中心", path: "/data_dedupe" }, { label: "采集结果审计", path: "/result_audit" }, { label: "采集限速", path: "/rate_limiter" }, { label: "采集调度器", path: "/scheduler" }, { label: "RPA工作流", path: "/rpa_workflow" }, { label: "批量接入", path: "/batch_ingest" }, { label: "数据质量校验", path: "/data_quality" }, { label: "日志采集", path: "/log_collector" }, { label: "代理池管理", path: "/proxy_pool" }, { label: "格式适配器", path: "/format_adapter" }, { label: "转换抽取管线", path: "/pipeline" }, { label: "采集执行日志", path: "/extraction_log" }, { label: "页面变更监控", path: "/page_change" }, { label: "数据采样器", path: "/data_sample" }, { label: "采集导出中心", path: "/export_center" }, { label: "数据源注册", path: "/source_registry" }, { label: "采集重试策略", path: "/retry_policy" }]
</script>
