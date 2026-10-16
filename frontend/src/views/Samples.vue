<template>
  <div>
    <div class="topbar">
      <div>
        <h1>样品进度</h1>
        <p>打样规格拆细：色号、尺寸、表面、LOGO 工艺/位置、打样数量与运单——减少「打错样」。</p>
      </div>
      <button class="btn ghost" @click="refresh">刷新</button>
    </div>

    <div class="card" style="margin-bottom:14px">
      <h3>{{ form.id ? `编辑样品 ${form.id}` : '登记 / 更新样品' }}</h3>

      <div class="section-label">基本信息</div>
      <div class="split">
        <div class="field"><label>客户</label><input v-model="form.customer_name" /></div>
        <div class="field"><label>关联需求编号</label><input v-model="form.inquiry_id" placeholder="INQ-001" /></div>
        <div class="field"><label>厂商</label><input v-model="form.vendor_name" placeholder="义乌星海..." /></div>
        <div class="field"><label>产品</label><input v-model="form.product" placeholder="500ml 保温杯" /></div>
        <div class="field">
          <label>状态</label>
          <select v-model="form.status">
            <option>待打样</option>
            <option>打样中</option>
            <option>已寄出</option>
            <option>海外已确认</option>
            <option>已确认</option>
            <option>已取消</option>
          </select>
        </div>
        <div class="field"><label>预计完成</label><input v-model="form.eta" placeholder="2026-09-12" /></div>
      </div>

      <div class="section-label">规格明细</div>
      <div class="split">
        <div class="field"><label>颜色名称</label><input v-model="form.color" placeholder="哑光黑" /></div>
        <div class="field"><label>色号 / Pantone</label><input v-model="form.color_code" placeholder="Pantone 19-4007 TCX" /></div>
        <div class="field"><label>材质</label><input v-model="form.material" placeholder="304不锈钢 + 喷塑外壳" /></div>
        <div class="field"><label>尺寸 / 容量</label><input v-model="form.size_spec" placeholder="500ml / 高22cm" /></div>
        <div class="field">
          <label>表面工艺</label>
          <select v-model="form.finish">
            <option value="">未指定</option>
            <option>哑光喷塑</option>
            <option>亮光</option>
            <option>细砂触感</option>
            <option>电泳</option>
            <option>拉丝</option>
            <option>过胶/覆膜</option>
            <option>其他</option>
          </select>
        </div>
        <div class="field">
          <label>LOGO 工艺</label>
          <select v-model="form.logo_process">
            <option value="">未指定</option>
            <option>丝印</option>
            <option>激光雕刻</option>
            <option>烫金</option>
            <option>刺绣</option>
            <option>热转印</option>
            <option>UV打印</option>
            <option>镭雕</option>
            <option>其他</option>
          </select>
        </div>
        <div class="field"><label>LOGO 位置</label><input v-model="form.logo_position" placeholder="杯身正面居中" /></div>
        <div class="field"><label>打样数量</label><input v-model="form.sample_qty" placeholder="2" /></div>
        <div class="field"><label>打样费</label><input v-model="form.sample_fee" placeholder="￥80（可扣大货）" /></div>
        <div class="field"><label>快递单号</label><input v-model="form.tracking_no" placeholder="寄出后填写" /></div>
      </div>

      <div class="field"><label>备注</label><textarea v-model="form.notes" style="min-height:72px" placeholder="LOGO文件、认证、忌讳色差等" /></div>
      <div class="row-actions">
        <button class="btn" @click="save">保存</button>
        <button class="btn ghost" type="button" @click="resetForm">清空</button>
      </div>
    </div>

    <div class="grid sample-grid">
      <div class="card sample-card" v-for="s in items" :key="s.id">
        <div class="sample-head">
          <div>
            <strong>{{ s.id }}</strong>
            <span class="pill" style="margin-left:8px">{{ s.status }}</span>
          </div>
          <div class="row-actions">
            <button class="btn ghost sm" @click="edit(s)">编辑</button>
            <button class="btn ghost sm" @click="addFollowup(s)">加跟进</button>
            <button
              v-if="s.status === '已确认' || s.status === '海外已确认'"
              class="btn sm"
              @click="toOrder(s)"
            >转订单</button>
          </div>
        </div>
        <div class="title">{{ s.product || '未填产品' }}</div>
        <div class="muted">{{ s.customer_name || '-' }} · {{ s.vendor_name || '-' }}</div>
        <div class="spec-box">
          <div><span class="k">颜色</span>{{ specColor(s) }}</div>
          <div><span class="k">材质</span>{{ s.material || '-' }}</div>
          <div><span class="k">尺寸</span>{{ s.size_spec || '-' }}</div>
          <div><span class="k">表面</span>{{ s.finish || '-' }}</div>
          <div><span class="k">LOGO</span>{{ logoLine(s) }}</div>
          <div><span class="k">数量/费</span>{{ qtyFee(s) }}</div>
          <div v-if="s.tracking_no"><span class="k">运单</span>{{ s.tracking_no }}</div>
          <div><span class="k">ETA</span>{{ s.eta || '-' }}</div>
        </div>
        <div v-if="s.notes" class="muted notes">{{ s.notes }}</div>
      </div>
    </div>
    <div v-if="!items.length" class="empty card">暂无样品记录</div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api } from '../api'

const items = ref([])
const form = reactive(emptyForm())

function emptyForm() {
  return {
    id: '',
    customer_name: '',
    inquiry_id: '',
    vendor_name: '',
    vendor_id: '',
    product: '',
    color: '',
    color_code: '',
    material: '',
    size_spec: '',
    finish: '',
    logo_process: '',
    logo_position: '',
    sample_qty: '',
    sample_fee: '',
    tracking_no: '',
    status: '待打样',
    eta: '',
    notes: '',
  }
}

function resetForm() {
  Object.assign(form, emptyForm())
}

function edit(s) {
  Object.assign(form, emptyForm(), {
    id: s.id || '',
    customer_name: s.customer_name || '',
    inquiry_id: s.inquiry_id || '',
    vendor_name: s.vendor_name || '',
    vendor_id: s.vendor_id || '',
    product: s.product || '',
    color: s.color || '',
    color_code: s.color_code || '',
    material: s.material || '',
    size_spec: s.size_spec || '',
    finish: s.finish || '',
    logo_process: s.logo_process || '',
    logo_position: s.logo_position || '',
    sample_qty: s.sample_qty || '',
    sample_fee: s.sample_fee || '',
    tracking_no: s.tracking_no || '',
    status: s.status || '待打样',
    eta: s.eta || '',
    notes: s.notes || '',
  })
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function specColor(s) {
  if (s.color && s.color_code) return `${s.color}（${s.color_code}）`
  return s.color || s.color_code || '-'
}

function logoLine(s) {
  const parts = [s.logo_process, s.logo_position].filter(Boolean)
  return parts.length ? parts.join(' · ') : '-'
}

function qtyFee(s) {
  const parts = []
  if (s.sample_qty) parts.push(`${s.sample_qty} 件`)
  if (s.sample_fee) parts.push(s.sample_fee)
  return parts.length ? parts.join(' / ') : '-'
}

async function refresh() {
  try {
    const list = await api.samples()
    items.value = Array.isArray(list) ? list : []
  } catch (e) {
    items.value = []
    console.error(e)
  }
}

async function save() {
  const payload = { ...form }
  if (!payload.id) delete payload.id
  await api.saveSample(payload)
  resetForm()
  await refresh()
}

async function addFollowup(s) {
  const reason = prompt('跟进原因', `跟进样品 ${s.product || s.id}`)
  if (!reason) return
  const due = new Date()
  due.setDate(due.getDate() + 3)
  await api.saveFollowup({
    customer_name: s.customer_name || '',
    inquiry_id: s.inquiry_id || '',
    reason,
    suggested_action: '确认样品状态 / 催寄样',
    due_date: due.toISOString().slice(0, 10),
    priority: 'medium',
  })
  alert('已添加跟进')
}

async function toOrder(s) {
  const o = await api.orderFromSample(s.id)
  alert(`已生成订单 ${o.id}`)
}

onMounted(refresh)
</script>

<style scoped>
.section-label {
  margin: 8px 0 10px;
  font-size: 13px;
  font-weight: 600;
  color: var(--brand, #0b5f52);
  letter-spacing: 0.04em;
}
.sample-grid {
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
}
.sample-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}
.title {
  margin-top: 10px;
  font-size: 17px;
  font-weight: 650;
}
.spec-box {
  margin-top: 12px;
  padding: 10px 12px;
  background: #f4f7f5;
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 14px;
  line-height: 1.4;
}
.spec-box .k {
  display: inline-block;
  min-width: 52px;
  margin-right: 8px;
  color: var(--muted, #5d6b73);
  font-size: 12px;
}
.notes { margin-top: 10px; font-size: 13px; }
</style>
