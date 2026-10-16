<template>
  <div>
    <div class="topbar">
      <div>
        <h1>收款账期</h1>
        <p>钱没到账就不算成交。这里按订单盯着定金与尾款到期日，逾期自动揪出来，催款有据可依。</p>
      </div>
      <button class="btn ghost" @click="load">刷新</button>
    </div>

    <div v-if="error" class="card mb-12" style="color:var(--danger)">{{ error }}</div>
    <div v-if="toast" class="card mb-12" style="color:var(--ok)">{{ toast }}</div>

    <div class="kpi-grid mb-16">
      <div class="kpi tone-brand">
        <div class="kpi-label">应收总额（未收）</div>
        <div class="kpi-value">${{ fmt(summary.total_due) }}</div>
        <div class="kpi-sub">{{ summary.order_count ?? 0 }} 张生效订单</div>
      </div>
      <div class="kpi alert-bar">
        <div class="kpi-label">已逾期金额</div>
        <div class="kpi-value text-danger">${{ fmt(summary.total_overdue) }}</div>
        <div class="kpi-sub">必须立刻催</div>
      </div>
      <div class="kpi warn-bar">
        <div class="kpi-label">逾期订单数</div>
        <div class="kpi-value text-warn">{{ summary.overdue_orders ?? 0 }}</div>
        <div class="kpi-sub">含任一期逾期</div>
      </div>
      <div class="kpi ok-bar">
        <div class="kpi-label">已到账合计</div>
        <div class="kpi-value text-ok">${{ fmt(totalPaid) }}</div>
        <div class="kpi-sub">已确认收到</div>
      </div>
    </div>

    <div class="card flush">
      <div style="padding:16px 20px 12px" class="flex between center gap-10 wrap">
        <h3 style="margin:0">应收清单<span class="hint">（逾期在最前）</span></h3>
        <label class="flex center gap-6" style="font-size:13px;color:var(--muted)">
          <input type="checkbox" v-model="onlyOverdue" /> 只看逾期
        </label>
      </div>
      <div class="table-wrap">
        <table class="table" v-if="rowsFiltered.length">
          <thead>
            <tr>
              <th>订单 / 客户</th>
              <th>合同额</th>
              <th>已收</th>
              <th>未收</th>
              <th>下一到期</th>
              <th>收款进度</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="r in rowsFiltered" :key="r.id">
              <tr :class="{ 'row-overdue': r.is_overdue }">
                <td>
                  <strong class="mono">{{ r.id }}</strong>
                  <span v-if="r.is_overdue" class="pill overdue" style="margin-left:6px">逾期 {{ r.overdue_count }} 期</span>
                  <div>{{ r.customer_name || '-' }}</div>
                  <div class="muted">{{ r.product || '' }}</div>
                </td>
                <td class="num">${{ fmt(r.total_amount) }}</td>
                <td class="num text-ok">${{ fmt(r.paid_amount) }}</td>
                <td class="num" :class="r.is_overdue ? 'text-danger' : ''">${{ fmt(r.due_amount) }}</td>
                <td>
                  <div v-if="r.next_due_date" :class="isPast(r.next_due_date) ? 'text-danger strong' : ''">
                    {{ r.next_due_date }}
                  </div>
                  <div v-else class="muted">—</div>
                </td>
                <td style="min-width:150px">
                  <div class="bar thin" :class="progressClass(r)">
                    <i :style="{ width: progress(r) }"></i>
                  </div>
                  <div class="muted mt-8">{{ progress(r) }} 已收</div>
                </td>
                <td>
                  <div class="row-actions">
                    <button class="btn ghost sm" @click="toggle(r.id)">
                      {{ expanded === r.id ? '收起' : '收款明细' }}
                    </button>
                  </div>
                </td>
              </tr>
              <tr v-if="expanded === r.id">
                <td colspan="7" style="background:var(--surface-2);padding:14px 12px">
                  <div class="pay-grid">
                    <div v-for="p in r.payments" :key="p.id" class="pay-card" :class="payClass(p)">
                      <div class="flex between center">
                        <strong>{{ p.name }}</strong>
                        <span class="pill" :class="p.status === 'paid' ? 'paid' : (isPast(p.due_date) ? 'overdue' : 'pending')">
                          {{ p.status === 'paid' ? '已收' : (isPast(p.due_date) ? '逾期' : '待收') }}
                        </span>
                      </div>
                      <div class="pay-amt">${{ fmt(p.amount) }}</div>
                      <div class="muted">
                        占比 {{ Math.round((p.ratio || 0) * 100) }}%
                        <template v-if="p.due_date"> · 到期 {{ p.due_date }}</template>
                      </div>
                      <div class="muted" v-if="p.paid_at">实收 ${{ fmt(p.paid_amount) }} · {{ p.paid_at.slice(0, 16) }}</div>
                      <div class="muted" v-if="p.method">方式 {{ p.method }}</div>
                      <button
                        v-if="p.status !== 'paid'"
                        class="btn sm mt-8"
                        :disabled="busy"
                        @click="record(r, p)"
                      >登记收款</button>
                    </div>
                  </div>
                  <div class="muted mt-12" v-if="r.etd">预计开船 ETD {{ r.etd }}</div>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
      <div v-if="!rowsFiltered.length" class="empty">没有应收订单</div>
    </div>
  </div>
</template>

<script setup>
import { computed, inject, onMounted, ref } from 'vue'
import { api } from '../api'

const refreshNav = inject('refreshNav', () => {})
const data = ref({ rows: [], summary: {} })
const error = ref('')
const toast = ref('')
const busy = ref(false)
const expanded = ref('')
const onlyOverdue = ref(false)

const summary = computed(() => data.value.summary || {})
const rows = computed(() => data.value.rows || [])
const rowsFiltered = computed(() => (onlyOverdue.value ? rows.value.filter((r) => r.is_overdue) : rows.value))
const totalPaid = computed(() =>
  rows.value.reduce((acc, r) => acc + Number(r.paid_amount || 0), 0).toFixed(2),
)

function fmt(v) {
  const n = Number(v || 0)
  if (!n) return '0'
  return n.toLocaleString('en-US', { maximumFractionDigits: 2 })
}
function isPast(d) {
  if (!d) return false
  return d < new Date().toISOString().slice(0, 10)
}
function progress(r) {
  const t = Number(r.total_amount || 0)
  const p = Number(r.paid_amount || 0)
  if (!t) return '0%'
  return `${Math.round((p / t) * 100)}%`
}
function progressClass(r) {
  const pct = parseInt(progress(r), 10)
  if (r.is_overdue) return 'danger'
  if (pct >= 100) return ''
  if (pct > 0) return 'warn'
  return 'danger'
}
function payClass(p) {
  if (p.status === 'paid') return 'paid'
  if (isPast(p.due_date)) return 'overdue'
  return ''
}
function toggle(id) {
  expanded.value = expanded.value === id ? '' : id
}

async function load() {
  error.value = ''
  try {
    data.value = await api.collections()
  } catch (e) {
    error.value = e.message || String(e)
  }
}

function flash(msg) {
  toast.value = msg
  setTimeout(() => (toast.value = ''), 2600)
}

async function record(row, p) {
  const input = prompt(`登记「${row.id} · ${p.name}」实收金额（${row.currency}）`, p.amount)
  if (input === null) return
  const amount = Number(input)
  if (!amount || amount <= 0) {
    error.value = '请输入有效金额'
    return
  }
  busy.value = true
  error.value = ''
  try {
    await api.recordPayment(row.id, { payment_id: p.id, amount: String(amount), method: 'T/T' })
    flash(`已登记 ${p.name} $${fmt(amount)}`)
    await load()
    refreshNav()
  } catch (e) {
    error.value = e.message || String(e)
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.row-overdue td { background: #fdf5f4; }
.row-overdue:hover td { background: #fbecea; }
.pay-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; }
.pay-card {
  background: #fff;
  border: 1px solid var(--line);
  border-left: 3px solid var(--line-strong);
  border-radius: var(--radius-sm);
  padding: 12px 14px;
}
.pay-card.paid { border-left-color: var(--ok); }
.pay-card.overdue { border-left-color: var(--danger); }
.pay-amt { font-size: 20px; font-weight: 700; letter-spacing: -0.02em; margin: 6px 0 2px; }
</style>
