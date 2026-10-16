<template>
  <div>
    <div class="topbar">
      <div>
        <h1>报价单</h1>
        <p>每份报价都记版本。低于底价会亮红线并强制老板特批 —— 防飞单、防业务员自己乱压价；客户改了 5 轮最后没成，也能翻出版本看清为什么。</p>
      </div>
      <div class="row-actions">
        <button class="btn ghost" @click="load">刷新</button>
        <button class="btn" @click="toggleForm">{{ showForm ? '收起表单' : '新建报价' }}</button>
      </div>
    </div>

    <div v-if="error" class="card mb-12" style="color:var(--danger)">{{ error }}</div>
    <div v-if="toast" class="card mb-12" style="color:var(--ok)">{{ toast }}</div>

    <div class="kpi-grid mb-16">
      <div class="kpi tone-brand">
        <div class="kpi-label">报价单总数</div>
        <div class="kpi-value">{{ items.length }}</div>
        <div class="kpi-sub">含历史版本</div>
      </div>
      <div class="kpi alert-bar">
        <div class="kpi-label">低于底价</div>
        <div class="kpi-value text-danger">{{ belowFloorCount }}</div>
        <div class="kpi-sub">需老板特批</div>
      </div>
      <div class="kpi">
        <div class="kpi-label">平均毛利率</div>
        <div class="kpi-value" :class="avgMargin >= 0.15 ? 'text-ok' : 'text-warn'">
          {{ (avgMargin * 100).toFixed(1) }}<small>%</small>
        </div>
        <div class="kpi-sub">按底价/成本估算</div>
      </div>
      <div class="kpi">
        <div class="kpi-label">待客户回复</div>
        <div class="kpi-value">{{ pendingCount }}</div>
        <div class="kpi-sub">draft / sent</div>
      </div>
    </div>

    <div v-if="showForm" class="card mb-16">
      <h3>{{ form.id ? `编辑 ${form.id}` : '新建报价' }}</h3>
      <div class="split three">
        <div class="field"><label>关联询盘</label><input v-model="form.inquiry_id" placeholder="INQ-001" /></div>
        <div class="field"><label>客户</label><input v-model="form.customer_name" /></div>
        <div class="field"><label>厂商</label><input v-model="form.vendor_name" /></div>
        <div class="field"><label>厂商编号</label><input v-model="form.vendor_id" /></div>
        <div class="field"><label>币种</label><input v-model="form.currency" /></div>
        <div class="field"><label>贸易术语</label><input v-model="form.incoterms" /></div>
        <div class="field"><label>有效期至</label><input v-model="form.valid_until" placeholder="2026-09-20" /></div>
        <div class="field">
          <label>状态</label>
          <select v-model="form.status">
            <option value="draft">草稿</option>
            <option value="sent">已发客户</option>
            <option value="accepted">客户已接受</option>
            <option value="rejected">未成交</option>
          </select>
        </div>
        <div class="field">
          <label>成本价（每单位）</label>
          <input v-model="form.cost_price" placeholder="7.2" />
        </div>
      </div>

      <div class="section-label">明细行</div>
      <div v-for="(l, i) in form.lines" :key="i" class="line-row">
        <div class="field"><label>产品</label><input v-model="l.product" /></div>
        <div class="field"><label>颜色</label><input v-model="l.color" /></div>
        <div class="field"><label>材质</label><input v-model="l.material" /></div>
        <div class="field"><label>数量</label><input v-model="l.qty" /></div>
        <div class="field"><label>单价</label><input v-model="l.unit_price" /></div>
        <div class="field"><label>MOQ</label><input v-model="l.moq" /></div>
        <div class="field"><label>交期(天)</label><input v-model="l.lead_days" /></div>
        <div class="field"><label>行备注</label><input v-model="l.notes" /></div>
        <div class="field">
          <label>&nbsp;</label>
          <button class="btn ghost sm" @click="removeLine(i)" :disabled="form.lines.length <= 1">删行</button>
        </div>
      </div>
      <button class="btn ghost sm mb-16" @click="addLine">+ 加一行</button>

      <div class="section-label">内部管控</div>
      <div class="split">
        <div class="field">
          <label>底价（最低可报单价 · 内部可见）</label>
          <input v-model="form.floor_price" placeholder="低于此价需老板特批" />
        </div>
        <div class="field">
          <label>客户目标价</label>
          <input v-model="form.target_price" placeholder="客户希望的价" />
        </div>
      </div>
      <div v-if="formFloorWarning" class="warn-strip">
        ⚠ 有明细行低于底价，保存后将标记为「需老板特批」，报价无法直接发出。
      </div>
      <div class="field"><label>整单备注</label><textarea v-model="form.notes" style="min-height:70px" /></div>
      <div class="row-actions">
        <button class="btn" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存报价' }}</button>
        <button class="btn ghost" @click="reset">清空</button>
      </div>
    </div>

    <div class="card flush">
      <div class="table-wrap">
        <table class="table" v-if="items.length">
          <thead>
            <tr>
              <th>编号 / 版本</th><th>客户</th><th>厂商</th><th>金额</th>
              <th>毛利率</th><th>底价</th><th>状态</th><th>操作</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="q in items" :key="q.id">
              <tr :class="{ 'row-danger': q.below_floor && !q.boss_approved }">
                <td>
                  <strong class="mono">{{ q.id }}</strong>
                  <span class="pill info" style="margin-left:6px">v{{ q.version || 1 }}</span>
                  <div class="muted">
                    {{ q.inquiry_id ? '' : '' }}
                    <router-link v-if="q.inquiry_id" :to="`/inbox/${q.inquiry_id}`">{{ q.inquiry_id }}</router-link>
                  </div>
                </td>
                <td>{{ q.customer_name || '-' }}</td>
                <td>{{ q.vendor_name || '-' }}</td>
                <td class="num">{{ q.currency }} {{ q.total || '-' }}</td>
                <td>
                  <span class="strong" :class="marginClass(q)">{{ (margin(q) * 100).toFixed(1) }}%</span>
                </td>
                <td>
                  <span v-if="q.floor_price" class="num">{{ q.floor_price }}</span>
                  <span v-else class="muted">未设</span>
                  <div v-if="q.below_floor && q.boss_approved" class="pill paid mt-8">已特批</div>
                  <div v-else-if="q.below_floor" class="pill overdue mt-8">低于底价</div>
                </td>
                <td>
                  <span class="pill" :class="statusPill(q.status)">{{ statusText(q.status) }}</span>
                  <div v-if="q.lost_reason" class="muted">丢单：{{ q.lost_reason }}</div>
                </td>
                <td>
                  <div class="row-actions">
                    <button class="btn ghost sm" @click="toggleVersions(q)">{{ expanded === q.id ? '收起' : '版本' }}</button>
                    <button class="btn ghost sm" @click="edit(q)">编辑</button>
                    <button class="btn ghost sm" @click="revise(q)">改版</button>
                    <button class="btn ghost sm" @click="markLost(q)">记丢单</button>
                    <button
                      v-if="q.below_floor && !q.boss_approved"
                      class="btn gold sm"
                      @click="approveFloor(q)"
                    >特批</button>
                    <button class="btn sm" @click="toOrder(q)">转订单</button>
                    <button class="btn danger sm" @click="remove(q)">删除</button>
                  </div>
                </td>
              </tr>
              <tr v-if="expanded === q.id">
                <td colspan="8" style="background:var(--surface-2)">
                  <div class="muted mb-12">版本演进（旧版在前，最新在右）</div>
                  <div class="ver-list" v-if="versionData[q.id]">
                    <div
                      v-for="v in versionData[q.id].versions"
                      :key="v.version"
                      class="ver-card"
                      :class="{ current: v.is_current }"
                    >
                      <div class="vhead">
                        <span class="vno">v{{ v.version }}</span>
                        <span class="pill" :class="statusPill(v.status)">{{ statusText(v.status) }}</span>
                      </div>
                      <div class="vtotal">{{ q.currency }} {{ v.total || '-' }}</div>
                      <div class="vmeta" v-if="v.lines && v.lines.length">
                        {{ v.lines[0].product || '—' }} · {{ v.lines[0].qty || '-' }} × {{ v.lines[0].unit_price || '-' }}
                      </div>
                      <div class="vmeta">有效期 {{ v.valid_until || '-' }}</div>
                      <div class="vmeta">{{ (v.at || '').slice(0, 16) }} · {{ v.by || '—' }}</div>
                      <div class="vmeta" v-if="v.note">{{ v.note }}</div>
                    </div>
                  </div>
                  <div v-else class="muted">加载中…</div>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
      <div v-if="!items.length" class="empty">暂无报价单，点右上角新建</div>
    </div>
  </div>
</template>

<script setup>
import { computed, inject, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, getUser } from '../api'

const router = useRouter()
const refreshNav = inject('refreshNav', () => {})
const me = getUser() || {}
const items = ref([])
const error = ref('')
const toast = ref('')
const saving = ref(false)
const showForm = ref(false)
const expanded = ref('')
const versionData = reactive({})
const form = reactive(emptyForm())

function emptyLine() {
  return {
    product: '', color: '', material: '', qty: '', unit_price: '',
    moq: '', lead_days: '', notes: '', cost_price: '', floor_price: '',
  }
}
function emptyForm() {
  return {
    id: '', inquiry_id: '', customer_name: '', vendor_id: '', vendor_name: '',
    currency: 'USD', incoterms: 'FOB', valid_until: '', status: 'draft', notes: '',
    floor_price: '', cost_price: '', target_price: '', lines: [emptyLine()],
  }
}
function reset() {
  Object.assign(form, emptyForm())
}
function addLine() {
  form.lines.push(emptyLine())
}
function removeLine(i) {
  if (form.lines.length > 1) form.lines.splice(i, 1)
}
function toggleForm() {
  showForm.value = !showForm.value
}

const belowFloorCount = computed(() => items.value.filter((q) => q.below_floor && !q.boss_approved).length)
const pendingCount = computed(() => items.value.filter((q) => ['draft', 'sent'].includes(q.status)).length)
const avgMargin = computed(() => {
  const list = items.value.filter((q) => q.floor_price || q.cost_price)
  if (!list.length) return 0
  return list.reduce((a, q) => a + margin(q), 0) / list.length
})

function unitCost(q) {
  if (q.cost_price) return Number(q.cost_price)
  if (q.floor_price) return Number(q.floor_price)
  return 0
}
function margin(q) {
  const line = (q.lines || [])[0] || {}
  const price = Number(line.unit_price || 0)
  const cost = Number(line.cost_price || 0) || unitCost(q)
  if (!price || !cost) return 0
  return (price - cost) / price
}
function marginClass(q) {
  const m = margin(q)
  if (!m) return 'muted'
  return m < 0.1 ? 'text-danger' : m < 0.2 ? 'text-warn' : 'text-ok'
}
function statusPill(s) {
  return { draft: 'pending', sent: 'info', accepted: 'paid', rejected: 'overdue' }[s] || 'pending'
}
function statusText(s) {
  return { draft: '草稿', sent: '已发客户', accepted: '客户已接受', rejected: '未成交' }[s] || s
}

const formFloorWarning = computed(() => {
  const floor = Number(form.floor_price || 0)
  if (!floor) return false
  return form.lines.some((l) => {
    const p = Number(l.unit_price || 0)
    const f = Number(l.floor_price || 0) || floor
    return p > 0 && p < f
  })
})

async function load() {
  error.value = ''
  try {
    const list = await api.quotations()
    items.value = Array.isArray(list) ? list : []
  } catch (e) {
    items.value = []
    error.value = e.message || String(e)
  }
  refreshNav()
}

function flash(msg) {
  toast.value = msg
  setTimeout(() => (toast.value = ''), 2800)
}

function edit(q) {
  Object.assign(form, {
    id: q.id, inquiry_id: q.inquiry_id || '', customer_name: q.customer_name || '',
    vendor_id: q.vendor_id || '', vendor_name: q.vendor_name || '',
    currency: q.currency || 'USD', incoterms: q.incoterms || 'FOB',
    valid_until: q.valid_until || '', status: q.status || 'draft', notes: q.notes || '',
    floor_price: q.floor_price || '', cost_price: q.cost_price || '', target_price: q.target_price || '',
    lines: (q.lines || []).length
      ? q.lines.map((l) => ({ ...emptyLine(), ...l }))
      : [emptyLine()],
  })
  showForm.value = true
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

async function save() {
  saving.value = true
  error.value = ''
  try {
    const payload = { ...form, lines: form.lines.map((l) => ({ ...l })) }
    if (!payload.id) delete payload.id
    await api.saveQuotation(payload)
    reset()
    showForm.value = false
    await load()
    flash('报价已保存')
  } catch (e) {
    error.value = e.message || String(e)
  } finally {
    saving.value = false
  }
}

async function toggleVersions(q) {
  if (expanded.value === q.id) {
    expanded.value = ''
    return
  }
  expanded.value = q.id
  if (!versionData[q.id]) {
    try {
      versionData[q.id] = await api.quotationVersions(q.id)
    } catch (e) {
      error.value = e.message || String(e)
    }
  }
}

async function revise(q) {
  const price = prompt(`「${q.id}」改版：输入新的单价（当前 ${(q.lines?.[0] || {}).unit_price || '-'}）`, (q.lines?.[0] || {}).unit_price || '')
  if (price === null) return
  const note = prompt('改版原因（客户会看到记录，便于复盘）', '') || ''
  const lines = (q.lines || []).map((l) => ({ ...l, unit_price: price }))
  try {
    await api.quotationNewVersion(q.id, { lines, note })
    delete versionData[q.id]
    await load()
    if (expanded.value === q.id) toggleVersions(items.value.find((x) => x.id === q.id))
    flash(`「${q.id}」已生成新版本`)
  } catch (e) {
    error.value = e.message || String(e)
  }
}

async function markLost(q) {
  const reason = prompt('丢单原因（价格 / 交期 / 质量 / 客户取消 / 其他）', '价格')
  if (reason === null) return
  try {
    await api.quotationLost(q.id, reason)
    await load()
    flash(`已记录「${q.id}」丢单原因`)
  } catch (e) {
    error.value = e.message || String(e)
  }
}

async function approveFloor(q) {
  if (!(me.is_admin || me.can_approve)) {
    error.value = '低于底价需老板/管理员特批，请联系上级'
    return
  }
  if (!confirm(`确认特批 ${q.id} 低于底价的报价？该操作会留痕。`)) return
  try {
    await api.quotationApproveBelowFloor(q.id)
    await load()
    flash(`${q.id} 已特批`)
  } catch (e) {
    error.value = e.message || String(e)
  }
}

async function setStatus(q, status) {
  await api.setQuotationStatus(q.id, status)
  await load()
}

async function toOrder(q) {
  try {
    const o = await api.orderFromQuotation(q.id)
    await router.push('/orders')
    alert(`已生成订单 ${o.id}`)
  } catch (e) {
    error.value = e.message || String(e)
  }
}

async function remove(q) {
  if (!confirm(`删除报价 ${q.id}？版本历史将一并删除。`)) return
  await api.deleteQuotation(q.id)
  await load()
}

onMounted(load)
</script>

<style scoped>
.line-row {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 10px;
  align-items: end;
  padding-bottom: 4px;
}
.line-row .field { margin-bottom: 6px; }
@media (max-width: 1200px) {
  .line-row { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
.row-danger td { background: #fdf5f4; }
.row-danger:hover td { background: #fbecea; }
.warn-strip {
  margin: 0 0 14px;
  padding: 10px 14px;
  border-radius: var(--radius-sm);
  background: var(--danger-soft);
  border: 1px solid #f3cdc8;
  color: var(--danger);
  font-size: 13.5px;
  font-weight: 600;
}
</style>
