<template>
  <div>
    <div class="topbar">
      <div>
        <h1>订单</h1>
        <p>轻量 PO：从已接受报价或确认样品生成。这里看合同额与回款，交期和节点明细在「生产跟单」，催款在「收款账期」。</p>
      </div>
      <div class="row-actions">
        <button class="btn ghost" @click="load">刷新</button>
        <button class="btn" @click="showForm = !showForm">{{ showForm ? '收起表单' : '新建订单' }}</button>
      </div>
    </div>

    <div v-if="error" class="card mb-12" style="color:var(--danger)">{{ error }}</div>
    <div v-if="toast" class="card mb-12" style="color:var(--ok)">{{ toast }}</div>

    <div class="kpi-grid mb-16">
      <div class="kpi tone-brand">
        <div class="kpi-label">订单总数</div>
        <div class="kpi-value">{{ items.length }}</div>
        <div class="kpi-sub">含已签收</div>
      </div>
      <div class="kpi accent">
        <div class="kpi-label">合同总额</div>
        <div class="kpi-value">${{ money(totalAmount) }}</div>
        <div class="kpi-sub">全部订单</div>
      </div>
      <div class="kpi ok-bar">
        <div class="kpi-label">已到账</div>
        <div class="kpi-value text-ok">${{ money(paidAmount) }}</div>
        <div class="kpi-sub">已确认收到</div>
      </div>
      <div class="kpi alert-bar">
        <div class="kpi-label">未收余额</div>
        <div class="kpi-value text-danger">${{ money(dueAmount) }}</div>
        <div class="kpi-sub">还需催款</div>
      </div>
    </div>

    <div v-if="showForm" class="card mb-16">
      <h3>{{ form.id ? `编辑 ${form.id}` : '新建订单' }}</h3>
      <div class="split three">
        <div class="field"><label>客户</label><input v-model="form.customer_name" /></div>
        <div class="field"><label>厂商</label><input v-model="form.vendor_name" /></div>
        <div class="field"><label>询盘号</label><input v-model="form.inquiry_id" /></div>
        <div class="field"><label>报价号</label><input v-model="form.quotation_id" /></div>
        <div class="field"><label>产品</label><input v-model="form.product" /></div>
        <div class="field"><label>颜色</label><input v-model="form.color" /></div>
        <div class="field"><label>材质</label><input v-model="form.material" /></div>
        <div class="field"><label>数量</label><input v-model="form.qty" /></div>
        <div class="field"><label>单价</label><input v-model="form.unit_price" /></div>
        <div class="field"><label>币种</label><input v-model="form.currency" /></div>
        <div class="field"><label>定金比例</label><input v-model="form.deposit" placeholder="30%" /></div>
        <div class="field"><label>定金到期</label><input v-model="form.deposit_due" placeholder="2026-10-20" /></div>
        <div class="field"><label>预计开船 ETD</label><input v-model="form.etd" placeholder="2026-11-05" /></div>
        <div class="field"><label>客户到货日</label><input v-model="form.delivery_date" placeholder="2026-11-20" /></div>
        <div class="field">
          <label>状态</label>
          <select v-model="form.status">
            <option>待定金</option>
            <option>生产中</option>
            <option>已出货</option>
            <option>已签收</option>
            <option>已取消</option>
          </select>
        </div>
        <div class="field"><label>运单号</label><input v-model="form.tracking_no" /></div>
      </div>
      <div class="field"><label>备注</label><textarea v-model="form.notes" style="min-height:70px" /></div>
      <div class="row-actions">
        <button class="btn" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存' }}</button>
        <button class="btn ghost" @click="reset">清空</button>
      </div>
    </div>

    <div class="card flush">
      <div class="table-wrap">
        <table class="table" v-if="items.length">
          <thead>
            <tr>
              <th>编号</th><th>客户 / 工厂</th><th>产品</th><th>数量 × 单价</th>
              <th>合同额</th><th>已收 / 未收</th><th>交期</th><th>进度</th><th>状态</th><th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="o in items" :key="o.id">
              <td>
                <strong class="mono">{{ o.id }}</strong>
                <div class="muted">{{ o.quotation_id || o.inquiry_id || '—' }}</div>
              </td>
              <td>
                {{ o.customer_name || '-' }}
                <div class="muted">{{ o.vendor_name || '未定工厂' }}</div>
              </td>
              <td>
                {{ o.product }}
                <div class="muted">{{ o.color || '-' }} / {{ o.material || '-' }}</div>
              </td>
              <td class="nowrap">{{ o.qty || '-' }} × {{ o.currency }} {{ o.unit_price || '-' }}</td>
              <td class="num">${{ money(o.total_amount) }}</td>
              <td class="num">
                <span class="text-ok">${{ money(o.paid_amount) }}</span>
                <div :class="Number(o.due_amount) > 0 ? 'text-danger' : 'muted'">欠 ${{ money(o.due_amount) }}</div>
              </td>
              <td>
                <div v-if="o.delivery_date">{{ o.delivery_date }}</div>
                <div v-else class="muted">未定</div>
                <div class="muted" v-if="o.etd">ETD {{ o.etd }}</div>
              </td>
              <td style="min-width:120px">
                <div class="bar thin" :class="riskClass(o)">
                  <i :style="{ width: `${Math.round((o.milestone_progress || 0) * 100)}%` }"></i>
                </div>
                <div class="muted mt-8">{{ o.current_milestone || '未开始' }}</div>
              </td>
              <td><span class="pill" :class="statusPill(o.status)">{{ o.status }}</span></td>
              <td>
                <div class="row-actions">
                  <button class="btn ghost sm" @click="edit(o)">编辑</button>
                  <router-link class="btn ghost sm" to="/tracking">跟单</router-link>
                  <router-link class="btn ghost sm" to="/collections">催款</router-link>
                  <button class="btn danger sm" @click="remove(o)">删除</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="!items.length" class="empty">暂无订单</div>
    </div>
  </div>
</template>

<script setup>
import { computed, inject, onMounted, reactive, ref } from 'vue'
import { api } from '../api'

const refreshNav = inject('refreshNav', () => {})
const items = ref([])
const error = ref('')
const toast = ref('')
const saving = ref(false)
const showForm = ref(false)
const form = reactive(emptyForm())

const totalAmount = computed(() => items.value.reduce((a, o) => a + Number(o.total_amount || 0), 0))
const paidAmount = computed(() => items.value.reduce((a, o) => a + Number(o.paid_amount || 0), 0))
const dueAmount = computed(() => items.value.reduce((a, o) => a + Number(o.due_amount || 0), 0))

function money(v) {
  const n = Number(v || 0)
  return n ? n.toLocaleString('en-US', { maximumFractionDigits: 0 }) : '0'
}
function riskClass(o) {
  const r = Number(o.delay_risk || 0)
  if (r >= 60) return 'danger'
  if (r >= 25) return 'warn'
  return ''
}
function statusPill(s) {
  if (s === '已签收') return 'done'
  if (s === '已出货') return 'info'
  if (s === '生产中') return 'processed'
  if (s === '已取消') return 'rejected'
  return 'pending'
}

function emptyForm() {
  return {
    id: '', inquiry_id: '', quotation_id: '', customer_name: '', vendor_name: '', vendor_id: '',
    product: '', color: '', material: '', qty: '', unit_price: '', currency: 'USD',
    deposit: '30%', status: '待定金', etd: '', tracking_no: '', notes: '',
    delivery_date: '', deposit_due: '',
  }
}
function reset() { Object.assign(form, emptyForm()) }

async function load() {
  try {
    const list = await api.orders()
    items.value = Array.isArray(list) ? list : []
  } catch (e) {
    items.value = []
    error.value = e.message || String(e)
  }
  refreshNav()
}

function flash(msg) {
  toast.value = msg
  setTimeout(() => (toast.value = ''), 2600)
}

function edit(o) {
  Object.assign(form, emptyForm(), {
    id: o.id, inquiry_id: o.inquiry_id || '', quotation_id: o.quotation_id || '',
    customer_name: o.customer_name || '', vendor_name: o.vendor_name || '', vendor_id: o.vendor_id || '',
    product: o.product || '', color: o.color || '', material: o.material || '',
    qty: o.qty || '', unit_price: o.unit_price || '', currency: o.currency || 'USD',
    deposit: o.deposit || '30%', status: o.status || '待定金', etd: o.etd || '',
    tracking_no: o.tracking_no || '', notes: o.notes || '',
    delivery_date: o.delivery_date || '', deposit_due: o.deposit_due || '',
  })
  showForm.value = true
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

async function save() {
  saving.value = true
  error.value = ''
  try {
    const payload = { ...form }
    if (!payload.id) delete payload.id
    await api.saveOrder(payload)
    reset()
    showForm.value = false
    await load()
    flash('订单已保存')
  } catch (e) {
    error.value = e.message || String(e)
  } finally {
    saving.value = false
  }
}

async function remove(o) {
  if (!confirm(`删除订单 ${o.id}？`)) return
  await api.deleteOrder(o.id)
  await load()
}

onMounted(load)
</script>
