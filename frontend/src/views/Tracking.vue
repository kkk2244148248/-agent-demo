<template>
  <div>
    <div class="topbar">
      <div>
        <h1>生产跟单</h1>
        <p>在产订单的交期红绿灯。节点按「定金到账 → 排产下单 → 中期进度 → 尾期验货 → 报关出货 → 到港签收」推进，计划日落后于今天即亮红。</p>
      </div>
      <button class="btn ghost" @click="load">刷新</button>
    </div>

    <div v-if="error" class="card mb-12" style="color:var(--danger)">{{ error }}</div>
    <div v-if="toast" class="card mb-12" style="color:var(--ok)">{{ toast }}</div>

    <div class="kpi-grid mb-16">
      <div class="kpi tone-brand">
        <div class="kpi-label">在产订单</div>
        <div class="kpi-value">{{ summary.in_production ?? '-' }}</div>
        <div class="kpi-sub">未签收/未取消</div>
      </div>
      <div class="kpi alert-bar">
        <div class="kpi-label">交期红灯</div>
        <div class="kpi-value text-danger">{{ summary.red ?? 0 }}</div>
        <div class="kpi-sub">必须今天介入</div>
      </div>
      <div class="kpi warn-bar">
        <div class="kpi-label">交期黄灯</div>
        <div class="kpi-value text-warn">{{ summary.amber ?? 0 }}</div>
        <div class="kpi-sub">有节点已延期</div>
      </div>
      <div class="kpi ok-bar">
        <div class="kpi-label">正常进行</div>
        <div class="kpi-value text-ok">{{ summary.green ?? 0 }}</div>
        <div class="kpi-sub">按计划推进</div>
      </div>
    </div>

    <div class="track-grid">
      <div v-for="o in rows" :key="o.id" class="card order-card" :class="`edge-${o.light}`">
        <div class="flex between center gap-10 mb-12">
          <div>
            <div class="flex center gap-10">
              <span class="light" :class="o.light">{{ lightText(o.light) }}</span>
              <strong class="mono">{{ o.id }}</strong>
              <span class="pill" :class="statusClass(o.status)">{{ o.status }}</span>
            </div>
            <div class="oc-title">{{ o.product }}</div>
            <div class="muted">
              {{ o.customer_name || '-' }} · 工厂 {{ o.vendor_name || '未定' }} · 数量 {{ o.qty || '-' }}
            </div>
          </div>
          <div class="oc-right">
            <div class="muted">风险分</div>
            <div class="risk" :class="o.light">{{ o.delay_risk }}</div>
          </div>
        </div>

        <div class="tl">
          <div
            v-for="m in o.milestones"
            :key="m.key"
            class="tl-node"
            :class="nodeClass(m)"
          >
            <div class="tl-dot" @click="advance(o, m)" :title="`点击标记完成：${m.name}`">
              {{ m.status === 'done' ? '✓' : '·' }}
            </div>
            <div class="tl-name">{{ m.name }}</div>
            <div class="tl-date">{{ m.actual_date || m.planned_date || '—' }}</div>
          </div>
        </div>

        <div class="oc-foot">
          <div class="flex center gap-14 wrap">
            <label class="oc-field">
              <span>客户到货日</span>
              <input type="date" :value="o.delivery_date" @change="saveDelivery(o, $event)" />
            </label>
            <label class="oc-field">
              <span>预计开船 ETD</span>
              <input type="date" :value="o.etd" @change="saveEtd(o, $event)" />
            </label>
            <div class="muted" v-if="o.delayed_nodes">
              已延期节点 <strong class="text-danger">{{ o.delayed_nodes }}</strong> 个
            </div>
          </div>
          <div class="bar thin mt-8" :class="o.light === 'red' ? 'danger' : o.light === 'amber' ? 'warn' : ''">
            <i :style="{ width: `${Math.round((o.milestone_progress || 0) * 100)}%` }"></i>
          </div>
          <div class="muted mt-8">
            已完成 {{ Math.round((o.milestone_progress || 0) * 6) }}/6 节点 · 当前：{{ o.current_milestone || '未开始' }}
          </div>
        </div>
      </div>
    </div>

    <div v-if="!rows.length" class="card empty">没有在产订单</div>
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

const rows = computed(() => data.value.rows || [])
const summary = computed(() => data.value.summary || {})

function lightText(l) {
  return l === 'red' ? '交期告急' : l === 'amber' ? '需关注' : '正常'
}
function statusClass(s) {
  if (s === '已签收') return 'done'
  if (s === '已出货') return 'info'
  if (s === '生产中') return 'processed'
  return 'pending'
}
function nodeClass(m) {
  if (m.status === 'done') return 'done'
  const today = new Date().toISOString().slice(0, 10)
  if (m.planned_date && m.planned_date < today) return 'overdue'
  if (m.planned_date) return 'doing'
  return ''
}

async function load() {
  error.value = ''
  try {
    data.value = await api.tracking()
  } catch (e) {
    error.value = e.message || String(e)
  }
}

function flash(msg) {
  toast.value = msg
  setTimeout(() => (toast.value = ''), 2600)
}

async function advance(order, m) {
  if (m.status === 'done') return
  if (busy.value) return
  if (!confirm(`确认「${order.id}」的「${m.name}」已完成？之前的节点将一并标记完成。`)) return
  busy.value = true
  try {
    const idx = order.milestones.findIndex((x) => x.key === m.key)
    for (let i = 0; i <= idx; i++) {
      const node = order.milestones[i]
      if (node.status !== 'done') {
        // eslint-disable-next-line no-await-in-loop
        await api.advanceMilestone(order.id, { key: node.key, status: 'done' })
      }
    }
    flash(`「${order.id}」已推进至「${m.name}」`)
    await load()
    refreshNav()
  } catch (e) {
    error.value = e.message || String(e)
  } finally {
    busy.value = false
  }
}

async function saveDelivery(order, ev) {
  const v = ev.target.value
  try {
    await api.updateOrderMeta(order.id, { delivery_date: v })
    flash(`已更新「${order.id}」客户到货日`)
    await load()
  } catch (e) {
    error.value = e.message || String(e)
  }
}

async function saveEtd(order, ev) {
  const v = ev.target.value
  try {
    await api.updateOrderMeta(order.id, { etd: v })
    flash(`已更新「${order.id}」ETD`)
    await load()
  } catch (e) {
    error.value = e.message || String(e)
  }
}

onMounted(load)
</script>

<style scoped>
.track-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}
@media (max-width: 1240px) {
  .track-grid { grid-template-columns: 1fr; }
}
.order-card {
  position: relative;
  border-left: 3px solid var(--line-strong);
  transition: transform .18s ease, box-shadow .18s ease;
}
.order-card:hover { transform: translateY(-2px); box-shadow: var(--shadow); }
.order-card.edge-red { border-left-color: var(--danger); }
.order-card.edge-amber { border-left-color: var(--warn); }
.order-card.edge-green { border-left-color: var(--ok); }

.oc-title { font-size: 16px; font-weight: 650; margin: 6px 0 3px; }
.oc-right { text-align: right; flex-shrink: 0; }
.risk { font-size: 22px; font-weight: 700; letter-spacing: -0.03em; }
.risk.red { color: var(--danger); }
.risk.amber { color: var(--warn); }
.risk.green { color: var(--ok); }

.oc-foot { margin-top: 16px; padding-top: 14px; border-top: 1px dashed var(--line); }
.oc-field { display: flex; align-items: center; gap: 7px; font-size: 12.5px; color: var(--muted); }
.oc-field input {
  border: 1px solid var(--line-strong);
  border-radius: 8px;
  padding: 5px 8px;
  font-size: 13px;
  background: #fff;
  color: var(--ink);
}
.oc-field input:focus { outline: none; border-color: var(--brand-2); box-shadow: 0 0 0 3px rgba(18,121,106,.12); }
.tl-dot { cursor: pointer; transition: transform .14s ease; }
.tl-dot:hover { transform: scale(1.16); }
</style>
