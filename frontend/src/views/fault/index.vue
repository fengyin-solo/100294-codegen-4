<template>
  <section class="page" data-module="fault">
    <header class="page-head">
      <div>
        <h2>设备故障报送</h2>
        <p class="page-desc">故障单按「待受理 → 处理中 → 待复核 → 已关闭」向前流转；同设备同故障只保留一张未闭单。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="showCreate = !showCreate">
          {{ showCreate ? '收起报修单' : '报送故障' }}
        </button>
        <button class="btn" type="button" @click="exportRows">导出故障清单</button>
      </div>
    </header>

    <form v-if="showCreate" class="editor-card" @submit.prevent="submitFault">
      <h3>故障报修</h3>
      <div class="form-grid">
        <label>
          <span>设备编号 *</span>
          <input v-model="form.deviceCode" placeholder="例如 REGI-0001" required />
        </label>
        <label>
          <span>设备名称</span>
          <input v-model="form.deviceName" placeholder="选填，默认取设备台账" />
        </label>
        <label>
          <span>故障名称 *</span>
          <input v-model="form.faultName" placeholder="同一故障请使用相同名称" required />
        </label>
        <label>
          <span>故障级别</span>
          <select v-model="form.level">
            <option>一般</option>
            <option>严重</option>
            <option>紧急</option>
          </select>
        </label>
        <label class="wide-field">
          <span>故障现象 *</span>
          <textarea v-model="form.symptom" rows="3" required></textarea>
        </label>
      </div>
      <div class="form-actions">
        <button class="btn primary" type="submit">提交报修</button>
        <button class="btn ghost" type="button" @click="showCreate = false">取消</button>
      </div>
    </form>

    <div class="stat-row">
      <article v-for="item in boardCards" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <section class="panel-card">
      <header class="panel-head">
        <h3>当月重复故障（按设备归类）</h3>
        <button class="link" type="button" @click="filters.recurring = filters.recurring ? '' : 'true'; reload()">
          {{ filters.recurring ? '显示全部故障' : '只看重复故障' }}
        </button>
      </header>
      <table class="data-table compact">
        <thead>
          <tr>
            <th>设备编号</th><th>设备名称</th><th>故障名称</th><th>责任班组</th><th>责任人</th><th>次数</th><th>最近单号</th><th>最近状态</th><th>最近结论</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in recurringRows" :key="`${item['设备编号']}-${item['故障名称']}`">
            <td>{{ item['设备编号'] }}</td>
            <td>{{ item['设备名称'] }}</td>
            <td>{{ item['故障名称'] }}</td>
            <td>{{ item['责任班组'] }}</td>
            <td>{{ item['责任人'] }}</td>
            <td>{{ item['月内次数'] }}</td>
            <td>{{ item['最近单号'] }}</td>
            <td>{{ item['最近状态'] }}</td>
            <td>{{ item['最近处置结论'] }}</td>
          </tr>
          <tr v-if="!recurringRows.length">
            <td colspan="9" class="empty-state">当月暂无同设备同故障重复记录</td>
          </tr>
        </tbody>
      </table>
    </section>

    <form class="filter-bar" @submit.prevent="searchRows">
      <label class="filter-item">
        <span>关键词</span>
        <input v-model="filters.keyword" placeholder="单号 / 故障 / 现象" />
      </label>
      <label class="filter-item">
        <span>设备编号</span>
        <input v-model="filters.device" placeholder="按设备归类" />
      </label>
      <label class="filter-item">
        <span>状态</span>
        <select v-model="filters.status">
          <option value="">全部</option>
          <option v-for="status in statuses" :key="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <template v-for="row in rows" :key="String(row.id)">
          <tr :class="{ recurring: row['月内重复'] }">
            <td>{{ row['故障单号'] }}<em v-if="row['月内重复']" class="repeat-badge">月内重复 {{ row['月内重复次数'] }} 次</em></td>
            <td>{{ row['设备编号'] }}</td>
            <td>{{ row['设备名称'] }}</td>
            <td>{{ row['故障名称'] }}</td>
            <td class="pre-cell">{{ row['故障现象'] }}</td>
            <td><span :class="['status-pill', statusClass(row.status)]">{{ row.status }}</span></td>
            <td>{{ row['责任人'] }} / {{ row['责任班组'] }}</td>
            <td>{{ row['报修时间'] }}</td>
            <td>{{ row['受理时间'] || '—' }}</td>
            <td>{{ row['复核时间'] || '—' }}</td>
            <td class="pre-cell">{{ row['处置结论'] || '—' }}</td>
            <td class="row-actions">
              <button v-for="action in availableActions(row)" :key="action.code" class="link" type="button" @click="openAction(action, row)">
                {{ action.label }}
              </button>
              <button class="link" type="button" @click="selectedId = selectedId === row.id ? 0 : row.id">
                {{ selectedId === row.id ? '收起轨迹' : '流水轨迹' }}
              </button>
            </td>
          </tr>
          <tr v-if="selectedId === row.id">
            <td colspan="12" class="timeline-cell">
              <div class="timeline-grid">
                <div>
                  <h4>已保存处置记录（追加不覆盖）</h4>
                  <p class="pre-cell saved-record">{{ row['处置记录'] || '尚未填写' }}</p>
                  <h4>重复报修并入记录</h4>
                  <p v-if="!repeatReports(row).length" class="muted">无</p>
                  <ul>
                    <li v-for="(item, index) in repeatReports(row)" :key="index">{{ item['时间'] }} {{ item['报修人'] }}/{{ item['班组'] }}：{{ item['说明'] }}</li>
                  </ul>
                </div>
                <div>
                  <h4>操作流水</h4>
                  <ol class="timeline">
                    <li v-for="log in logs(row)" :key="`${log.at}-${log.step}`">
                      <strong>{{ log.action }}</strong>
                      <span>{{ log.at }} · {{ log.operator }} / {{ log.team }}</span>
                      <small v-if="log.note">{{ log.note }}</small>
                    </li>
                  </ol>
                </div>
              </div>
            </td>
          </tr>
        </template>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无故障单，可先报送一条故障</td>
        </tr>
      </tbody>
    </table>

    <div v-if="actionDialog" class="modal-mask" @click.self="actionDialog = null">
      <form class="modal-card" @submit.prevent="submitAction">
        <h3>{{ actionDialog.label }}</h3>
        <p class="muted">故障单：{{ actionDialog.row['故障单号'] }} · 当前：{{ actionDialog.row.status }}</p>

        <template v-if="actionDialog.code === 'save_record'">
          <label>
            <span>本次处置记录 *</span>
            <textarea v-model="actionDialog.values['处置记录']" rows="4" required placeholder="断线后再次提交会追加，不会顶掉原记录"></textarea>
          </label>
          <label>
            <span>处置人</span>
            <input v-model="actionDialog.values['处置人']" :placeholder="session.operator" />
          </label>
        </template>

        <template v-if="actionDialog.code === 'review'">
          <label class="check-line">
            <input v-model="reviewPassed" type="checkbox" />
            <span>复核通过并关闭；不勾选则退回处理中补充处置</span>
          </label>
          <label>
            <span>复核意见</span>
            <textarea v-model="actionDialog.values['复核意见']" rows="3"></textarea>
          </label>
          <label v-if="reviewPassed">
            <span>处置结论 *</span>
            <textarea v-model="actionDialog.values['处置结论']" rows="3" required placeholder="收口后同步到设备台账"></textarea>
          </label>
        </template>

        <template v-if="actionDialog.code === 'update_conclusion'">
          <label>
            <span>新的处置结论 *</span>
            <textarea v-model="actionDialog.values['处置结论']" rows="4" required></textarea>
          </label>
        </template>

        <div class="form-actions">
          <button class="btn primary" type="submit">确认提交</button>
          <button class="btn ghost" type="button" @click="actionDialog = null">取消</button>
        </div>
      </form>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条故障单；看板与明细使用同一接口实时同步</span>
      <span v-if="message" :class="errorMessage ? 'error-text' : 'success-text'">{{ message }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type Row = {
  id: number
  [key: string]: string | number | boolean | null | RepeatReport[] | LogEntry[]
}
type BoardCard = { label: string; value: number }
type RecurringRow = {
  设备编号: string
  设备名称: string
  故障名称: string
  责任班组: string
  责任人: string
  月内次数: number
  最近单号: string
  最近状态: string
  最近时间: string
  最近处置结论: string
  故障单号: string[]
}
type RepeatReport = { 报修人: string; 班组: string; 时间: string; 说明: string }
type LogEntry = { step: string; action: string; operator: string; team: string; at: string; note?: string }

type ActionDialog = {
  code: string
  label: string
  row: Row
  values: Record<string, string>
}

const ENDPOINT = '/api/fault'
const session = useSessionStore()
const columns = ['故障单号', '设备编号', '设备名称', '故障名称', '故障现象', '状态', '责任人/班组', '报修时间', '受理时间', '复核时间', '处置结论']
const statuses = ['待受理', '处理中', '待复核', '已关闭']

const rows = ref<Row[]>([])
const total = ref(0)
const boardCards = ref<BoardCard[]>([])
const recurringRows = ref<RecurringRow[]>([])
const showCreate = ref(false)
const selectedId = ref(0)
const message = ref('')
const errorMessage = ref(false)
const reviewPassed = ref(true)
const filters = reactive({ keyword: '', status: '', device: '', recurring: '' })
const form = reactive({ deviceCode: '', deviceName: '', faultName: '', level: '一般', symptom: '' })
const actionDialog = ref<ActionDialog | null>(null)

const actionsByStatus: Record<string, { code: string; label: string }[]> = {
  待受理: [{ code: 'accept', label: '受理' }],
  处理中: [
    { code: 'save_record', label: '保存处置记录' },
    { code: 'submit_review', label: '提交复核' },
  ],
  待复核: [{ code: 'review', label: '复核' }],
  已关闭: [{ code: 'update_conclusion', label: '修改结论' }],
}

function text(value: string | number | boolean | null | RepeatReport[] | LogEntry[] | undefined): string {
  return String(value ?? '')
}

function repeatReports(row: Row): RepeatReport[] {
  const value = row['重复报修']
  return Array.isArray(value) ? (value as RepeatReport[]) : []
}

function logs(row: Row): LogEntry[] {
  const value = row['操作日志']
  return Array.isArray(value) ? (value as LogEntry[]) : []
}

function availableActions(row: Row) {
  const list = actionsByStatus[text(row.status)] ?? []
  if (text(row.status) === '已关闭') {
    return text(row['责任班组']) === session.team && text(row['责任人']) === session.operator ? list : []
  }
  return text(row['责任班组']) === session.team ? list : []
}

function statusClass(status: string | number | boolean | null | RepeatReport[] | LogEntry[] | undefined) {
  return {
    待受理: 'status-pending',
    处理中: 'status-processing',
    待复核: 'status-reviewing',
    已关闭: 'status-closed',
  }[text(status)] ?? ''
}

function searchRows() {
  void reload()
}

function resetFilters() {
  filters.keyword = ''
  filters.status = ''
  filters.device = ''
  filters.recurring = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function createRequestKey(): string {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID()
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function headers(): HeadersInit {
  return {
    'X-Operator-Name': session.operator,
    'X-Operator-Team': session.team,
    'X-Request-Key': createRequestKey(),
  }
}

async function submitFault() {
  const values = {
    设备编号: form.deviceCode,
    设备名称: form.deviceName,
    故障名称: form.faultName,
    故障级别: form.level,
    故障现象: form.symptom,
  }
  const response = await request(ENDPOINT, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify({ values }),
  })
  const payload = await response.json()
  await finishRequest(response.ok, payload.message)
  if (response.ok) {
    showCreate.value = false
    Object.assign(form, { deviceCode: '', deviceName: '', faultName: '', level: '一般', symptom: '' })
  }
}

function openAction(action: { code: string; label: string }, row: Row) {
  actionDialog.value = {
    code: action.code,
    label: action.label,
    row,
    values: action.code === 'review' ? { 复核意见: '', 处置结论: '' } : { 处置记录: '', 处置人: '', 处置结论: '' },
  }
  reviewPassed.value = true
}

async function submitAction() {
  if (!actionDialog.value) return
  const dialog = actionDialog.value
  const values: Record<string, string | boolean> = { action: dialog.code, ...dialog.values }
  if (dialog.code === 'review') values.passed = reviewPassed.value
  const response = await request(`${ENDPOINT}/${dialog.row.id}/actions`, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify({ values }),
  })
  const payload = await response.json()
  const ok = await finishRequest(response.ok, payload.detail || payload.message)
  if (ok) actionDialog.value = null
}

async function finishRequest(ok: boolean, textMessage: string): Promise<boolean> {
  errorMessage.value = !ok
  message.value = textMessage
  if (ok) {
    await Promise.all([reload(true), loadBoard()])
    window.setTimeout(() => {
      if (!errorMessage.value) message.value = ''
    }, 3000)
  }
  return ok
}

async function loadBoard() {
  const response = await request(`${ENDPOINT}/board`)
  if (!response.ok) return
  const payload = await response.json()
  boardCards.value = payload.cards ?? []
  recurringRows.value = payload.recurring ?? []
}

async function reload(silent = false) {
  if (!silent) message.value = ''
  const query = new URLSearchParams()
  if (filters.keyword) query.set('keyword', filters.keyword)
  if (filters.status) query.set('status', filters.status)
  if (filters.device) query.set('device', filters.device)
  if (filters.recurring) query.set('recurring', 'true')
  const response = await request(`${ENDPOINT}?${query.toString()}`)
  if (!response.ok) {
    errorMessage.value = true
    message.value = '故障列表读取失败'
    return
  }
  const payload = await response.json()
  rows.value = (payload.items ?? []) as Row[]
  total.value = payload.total ?? rows.value.length
}

onMounted(() => Promise.all([reload(), loadBoard()]))
</script>
