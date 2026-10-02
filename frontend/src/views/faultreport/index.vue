<template>
  <section class="page" data-module="faultreport">
    <header class="page-head">
      <div>
        <h2>设备故障报送</h2>
        <p class="page-desc">故障单按「待受理 → 已受理 → 处理中 → 待复核 → 已收口」单向流转；同设备同故障只留一张未闭环单，收口后结论自动同步设备台账。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="showCreate = !showCreate">报送故障</button>
        <button class="btn" type="button" @click="exportRows">导出故障清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in cards" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <div class="panel-grid">
      <section class="panel">
        <h3 class="panel-title">故障按设备归类</h3>
        <table class="data-table">
          <thead>
            <tr><th>设备编号</th><th>设备名称</th><th>故障总数</th><th>未闭环</th><th>重复故障</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in byDevice" :key="row.设备编号">
              <td>{{ row.设备编号 }}</td>
              <td>{{ row.设备名称 }}</td>
              <td>{{ row.故障总数 }}</td>
              <td>{{ row.未闭环 }}</td>
              <td>{{ row.重复故障 }}</td>
            </tr>
            <tr v-if="!byDevice.length"><td colspan="5" class="empty-state">暂无故障数据</td></tr>
          </tbody>
        </table>
      </section>
      <section class="panel">
        <h3 class="panel-title">一个月内重复冒出来的故障</h3>
        <table class="data-table">
          <thead>
            <tr><th>设备编号</th><th>故障类别</th><th>重复次数</th><th>涉及工单</th><th>状态</th></tr>
          </thead>
          <tbody>
            <tr v-for="group in recurring" :key="`${group.设备编号}-${group.故障类别}`">
              <td>{{ group.设备编号 }}</td>
              <td>{{ group.故障类别 }}</td>
              <td>{{ group.重复次数 }}</td>
              <td>{{ group.涉及工单.join('、') }}</td>
              <td>{{ group.未闭环 ? '还有未闭环单' : '均已闭环' }}</td>
            </tr>
            <tr v-if="!recurring.length"><td colspan="5" class="empty-state">近 30 天没有重复故障</td></tr>
          </tbody>
        </table>
      </section>
    </div>

    <section v-if="showCreate" class="panel">
      <h3 class="panel-title">报送故障</h3>
      <form class="filter-bar" @submit.prevent="submitCreate">
        <label v-for="field in createFields" :key="field" class="filter-item">
          <span>{{ field }}</span>
          <input v-model="createForm[field]" :placeholder="`填写${field}`" />
        </label>
        <button class="btn primary" type="submit">提交报送</button>
        <button class="btn ghost" type="button" @click="showCreate = false">取消</button>
      </form>
      <p class="hint-text">同一台设备同一类故障已有未闭环工单时，不会再开新单，直接接着原单处置。</p>
    </section>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>故障单号</span>
        <input v-model="filters.keyword" placeholder="按故障单号检索" />
      </label>
      <label class="filter-item">
        <span>设备编号</span>
        <input v-model="filters.device" placeholder="按设备编号过滤" />
      </label>
      <label class="filter-item">
        <span>故障状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>重复</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td>{{ row.重复故障 ? '重复故障' : '—' }}</td>
          <td class="row-actions">
            <button
              v-if="nextAction(row)"
              class="link"
              type="button"
              @click="runAction(nextAction(row)!, row)"
            >
              {{ nextAction(row) }}
            </button>
            <button class="link" type="button" @click="openDetail(row)">详情</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无故障工单，可先报送故障</td>
        </tr>
      </tbody>
    </table>

    <section v-if="detail" class="panel">
      <h3 class="panel-title">工单 {{ detail.故障单号 }} · {{ detail.设备名称 }}（{{ detail.故障类别 }}）</h3>
      <div class="flow-steps">
        <span
          v-for="(status, index) in statuses"
          :key="status"
          class="flow-step"
          :class="{ done: statusIndex(detail.status) > index, current: statusIndex(detail.status) === index }"
        >
          {{ status }}
        </span>
      </div>
      <p class="hint-text">断线后重新打开会从「{{ detail.status }}」这一步接着走，已填写的处置记录不会被顶掉。</p>

      <h4 class="panel-subtitle">处置记录</h4>
      <div v-for="step in stepNames" :key="step" class="step-block">
        <template v-if="detail.处置记录 && detail.处置记录[step]">
          <p class="step-line">
            <strong>{{ step }}</strong>：{{ detail.处置记录[step].content }}
            <span class="hint-text">（{{ detail.处置记录[step].operator }} · {{ detail.处置记录[step].time }}）</span>
          </p>
        </template>
        <template v-else-if="stepReached(step)">
          <label class="filter-item step-editor">
            <span>{{ step }}记录（断点续填，保存后不可覆盖）</span>
            <input v-model="stepDrafts[step]" :placeholder="`填写${step}处置记录`" />
          </label>
          <button class="btn" type="button" @click="saveStep(step)">保存{{ step }}记录</button>
        </template>
        <p v-else class="hint-text">{{ step }}：工单还没流转到这一步</p>
      </div>

      <h4 class="panel-subtitle">处置结论</h4>
      <template v-if="canEditConclusion">
        <div class="step-block">
          <label class="filter-item step-editor">
            <span>仅本设备责任人（{{ detail.设备责任人 }}）可修改</span>
            <input v-model="conclusionDraft" placeholder="填写处置结论" />
          </label>
          <button class="btn" type="button" @click="saveConclusion">保存结论</button>
        </div>
      </template>
      <p v-else class="step-line">
        {{ detail.处置结论 || '尚未填写处置结论' }}
        <span class="hint-text">（仅本设备责任人「{{ detail.设备责任人 }}」可修改，其他班组只能查看）</span>
      </p>

      <h4 class="panel-subtitle">台账同步</h4>
      <p class="step-line">
        {{ detail.台账已同步 ? `已同步到设备台账（${detail.设备编号}），闭环时间 ${detail.收口时间 ?? '—'}` : '未同步：工单收口后会自动把处置结论写入设备台账' }}
      </p>
    </section>

    <footer class="page-foot">
      <span>共 {{ total }} 张故障工单</span>
      <span v-if="noticeMessage" class="notice-text">{{ noticeMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type Row = Record<string, any>
type RecurringGroup = {
  设备编号: string
  设备名称: string
  故障类别: string
  重复次数: number
  最近报送: string
  涉及工单: string[]
  未闭环: boolean
}
type Board = {
  cards: { label: string; value: number }[]
  by_device: { 设备编号: string; 设备名称: string; 故障总数: number; 未闭环: number; 重复故障: number }[]
  recurring: RecurringGroup[]
}

const ENDPOINT = '/api/faultreport'
const session = useSessionStore()
const columns = ['故障单号', '设备编号', '设备名称', '故障类别', '故障描述', '报修人', '报送时间']
const statuses = ['待受理', '已受理', '处理中', '待复核', '已收口']
const actionsByStatus: Record<string, string> = { 待受理: '受理', 已受理: '开始处理', 处理中: '提交复核', 待复核: '复核收口' }
const stepNames = ['受理', '处理', '复核']
const stepStage: Record<string, string> = { 受理: '已受理', 处理: '处理中', 复核: '待复核' }
const createFields = ['设备编号', '设备名称', '故障类别', '故障描述', '报修人', '设备责任人']

const rows = ref<Row[]>([])
const total = ref(0)
const cards = ref<Board['cards']>([])
const byDevice = ref<Board['by_device']>([])
const recurring = ref<RecurringGroup[]>([])
const filters = ref<Record<string, string>>({ keyword: '', device: '', status: '' })
const detail = ref<Row | null>(null)
const stepDrafts = ref<Record<string, string>>({})
const conclusionDraft = ref('')
const createForm = ref<Record<string, string>>({ 设备责任人: session.operator })
const showCreate = ref(false)
const errorMessage = ref('')
const noticeMessage = ref('')

const canEditConclusion = computed(
  () => !!detail.value && session.operator === String(detail.value.设备责任人 ?? ''),
)

function statusIndex(status: string) {
  return statuses.indexOf(status)
}

function nextAction(row: Row) {
  return actionsByStatus[String(row.status)] ?? ''
}

function stepReached(step: string) {
  if (!detail.value) return false
  return statusIndex(String(detail.value.status)) >= statusIndex(stepStage[step])
}

function resetMessages() {
  errorMessage.value = ''
  noticeMessage.value = ''
}

function showResult(payload: { ok: boolean; message?: string }) {
  if (payload.ok) {
    noticeMessage.value = payload.message ?? '操作完成'
  } else {
    errorMessage.value = payload.message ?? '操作未生效'
  }
}

async function postJson(path: string, values: Record<string, unknown>) {
  const response = await request(path, {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  if (!response.ok) {
    throw new Error(`接口返回 ${response.status}，操作未生效`)
  }
  return (await response.json()) as { ok: boolean; message: string; entry?: Row }
}

function resetFilters() {
  filters.value = { keyword: '', device: '', status: '' }
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function runAction(action: string, row: Row) {
  resetMessages()
  try {
    const payload = await postJson(`${ENDPOINT}/${row.id}/actions`, { action, operator: session.operator })
    showResult(payload)
    await reload()
    if (detail.value && detail.value.id === row.id) {
      await openDetail(row)
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '故障工单操作失败'
  }
}

async function openDetail(row: Row) {
  resetMessages()
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error('故障工单明细读取失败')
    }
    detail.value = await response.json()
    stepDrafts.value = {}
    conclusionDraft.value = String(detail.value?.处置结论 ?? '')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '故障工单明细读取失败'
  }
}

async function saveStep(step: string) {
  if (!detail.value) return
  resetMessages()
  try {
    const payload = await postJson(`${ENDPOINT}/${detail.value.id}/steps`, {
      step,
      content: stepDrafts.value[step] ?? '',
      operator: session.operator,
    })
    showResult(payload)
    if (payload.ok) {
      await openDetail(detail.value)
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '处置记录保存失败'
  }
}

async function saveConclusion() {
  if (!detail.value) return
  resetMessages()
  try {
    const payload = await postJson(`${ENDPOINT}/${detail.value.id}/conclusion`, {
      operator: session.operator,
      conclusion: conclusionDraft.value,
    })
    showResult(payload)
    if (payload.ok) {
      await openDetail(detail.value)
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '处置结论保存失败'
  }
}

async function submitCreate() {
  resetMessages()
  try {
    const payload = await postJson(ENDPOINT, { ...createForm.value })
    showResult(payload)
    if (payload.ok) {
      showCreate.value = false
      createForm.value = { 设备责任人: session.operator }
    }
    if (payload.entry) {
      await openDetail(payload.entry)
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '故障报送失败'
  }
}

async function reload() {
  const query = new URLSearchParams(
    Object.fromEntries(Object.entries(filters.value).filter(([, value]) => value)),
  ).toString()
  try {
    const [listResponse, boardResponse] = await Promise.all([
      request(`${ENDPOINT}?${query}`),
      request(`${ENDPOINT}/board`),
    ])
    if (!listResponse.ok || !boardResponse.ok) {
      throw new Error('故障工单列表读取失败')
    }
    const listPayload = await listResponse.json()
    rows.value = listPayload.items ?? []
    total.value = listPayload.total ?? rows.value.length
    const boardPayload = (await boardResponse.json()) as Board
    cards.value = boardPayload.cards ?? []
    byDevice.value = boardPayload.by_device ?? []
    recurring.value = boardPayload.recurring ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '故障工单列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.panel-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 12px; }
.panel { background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 12px; margin-bottom: 12px; }
.panel-title { margin: 0 0 8px; font-size: 14px; }
.panel-subtitle { margin: 12px 0 6px; font-size: 13px; }
.flow-steps { display: flex; gap: 8px; margin: 8px 0; }
.flow-step { flex: 1; text-align: center; padding: 6px 0; border: 1px solid var(--border); border-radius: 6px; color: var(--muted); font-size: 12px; }
.flow-step.done { border-color: var(--brand); color: var(--brand); background: #e8f0fe; }
.flow-step.current { background: var(--brand); border-color: var(--brand); color: #fff; }
.step-block { display: flex; gap: 8px; align-items: flex-end; margin-bottom: 6px; }
.step-line { margin: 4px 0; font-size: 13px; }
.step-editor { flex: 1; }
.step-editor input { width: 100%; }
.hint-text { color: var(--muted); font-size: 12px; margin: 4px 0; }
.notice-text { color: #067647; }
select { border: 1px solid var(--border); border-radius: 6px; padding: 4px 8px; }
input { border: 1px solid var(--border); border-radius: 6px; padding: 4px 8px; }
</style>
