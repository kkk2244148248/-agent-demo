<template>
  <div>
    <div class="topbar">
      <div>
        <h1>厂商名录</h1>
        <p>国内合作厂档案可增删改查；记下厂端偏好与备忘（喜欢什么单、忌讳什么），对接更顺。</p>
      </div>
      <button class="btn" @click="startCreate">新增厂商</button>
    </div>

    <div v-if="error" class="card" style="margin-bottom:12px;color:var(--danger)">{{ error }}</div>

    <div class="card" style="margin-bottom:14px">
      <h3>{{ form.id ? `编辑：${form.name || form.id}` : '新增厂商' }}</h3>
      <div class="split">
        <div class="field"><label>厂商编号</label><input v-model="form.id" placeholder="留空自动生成，如 V-YH01" /></div>
        <div class="field"><label>厂名 *</label><input v-model="form.name" /></div>
        <div class="field"><label>地区</label><input v-model="form.region" placeholder="浙江义乌" /></div>
        <div class="field"><label>联系人</label><input v-model="form.contact" /></div>
        <div class="field"><label>电话/微信</label><input v-model="form.phone" /></div>
        <div class="field"><label>邮箱</label><input v-model="form.email" /></div>
        <div class="field"><label>品类（逗号分隔）</label><input v-model="form.categories" placeholder="保温杯, 玻璃杯" /></div>
        <div class="field"><label>可做颜色</label><input v-model="form.colors" placeholder="哑光黑、珍珠白、定制色" /></div>
        <div class="field"><label>常用材质</label><input v-model="form.materials" placeholder="304不锈钢、食品级内胆" /></div>
        <div class="field"><label>表面工艺</label><input v-model="form.finishes" placeholder="哑光喷塑、亮光、电泳" /></div>
        <div class="field"><label>LOGO 工艺</label><input v-model="form.logo_processes" placeholder="丝印、激光、烫金" /></div>
        <div class="field"><label>潘通/定制色</label><input v-model="form.custom_color" placeholder="可接潘通，定制色 MOQ…" /></div>
        <div class="field"><label>打样周期</label><input v-model="form.sample_lead_days" placeholder="3-5 天" /></div>
        <div class="field"><label>大货交期</label><input v-model="form.bulk_lead_days" placeholder="15-25 天" /></div>
        <div class="field"><label>付款条件</label><input v-model="form.payment_terms" placeholder="月结 / 定金30%" /></div>
        <div class="field"><label>认证</label><input v-model="form.certifications" placeholder="BSCI, FDA, CE" /></div>
        <div class="field"><label>质量评分(1-5)</label><input v-model.number="form.quality_score" type="number" min="1" max="5" /></div>
        <div class="field"><label>产能备注</label><input v-model="form.capacity_note" /></div>
        <div class="field"><label>MOQ 说明</label><input v-model="form.moq_note" /></div>
        <div class="field"><label>参考价说明</label><input v-model="form.price_note" /></div>
        <div class="field">
          <label>状态</label>
          <select v-model="form.active">
            <option :value="true">合作中</option>
            <option :value="false">已停用</option>
          </select>
        </div>
      </div>
      <div class="field">
        <label>擅长 / 能力</label>
        <textarea v-model="form.strengths" style="min-height:72px" placeholder="产线、LOGO工艺、交期特点…"></textarea>
      </div>
      <div class="memo-grid">
        <div class="field">
          <label>偏好 / 喜欢什么单</label>
          <textarea v-model="form.preferences" placeholder="例如：喜欢稳定回头单；要先给清印刷文件；电池类必须先谈认证"></textarea>
        </div>
        <div class="field">
          <label>内部备忘</label>
          <textarea v-model="form.memo" placeholder="例如：旺季交期拉长；色差要试印；联系人只加微信"></textarea>
        </div>
      </div>
      <div class="field">
        <label>业务备注</label>
        <textarea v-model="form.notes" style="min-height:72px"></textarea>
      </div>
      <div class="row-actions">
        <button class="btn" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存' }}</button>
        <button class="btn ghost" type="button" @click="resetForm">清空表单</button>
      </div>
    </div>

    <div v-if="related" class="card" style="margin-bottom:14px">
      <h3>关联业务 · {{ form.name || form.id }}</h3>
      <div class="muted" style="margin-bottom:8px">
        样品 {{ related.counts?.samples || 0 }} ·
        报价 {{ related.counts?.quotations || 0 }} ·
        订单 {{ related.counts?.orders || 0 }}
      </div>
      <div class="split">
        <div>
          <div class="muted">样品</div>
          <div v-for="s in related.samples || []" :key="s.id">{{ s.id }} · {{ s.product }} · {{ s.status }}</div>
        </div>
        <div>
          <div class="muted">报价</div>
          <div v-for="q in related.quotations || []" :key="q.id">{{ q.id }} · {{ q.status }}</div>
        </div>
        <div>
          <div class="muted">订单</div>
          <div v-for="o in related.orders || []" :key="o.id">{{ o.id }} · {{ o.status }}</div>
        </div>
      </div>
    </div>

    <div class="row-actions" style="margin-bottom:12px">
      <input v-model="keyword" class="search-input" placeholder="搜索厂名 / 品类 / 备忘…" />
      <label class="check"><input type="checkbox" v-model="onlyActive" /> 只看合作中</label>
      <button class="btn ghost sm" @click="load">刷新</button>
    </div>

    <div class="grid vendor-grid">
      <div class="card vendor-card" v-for="v in filtered" :key="v.id">
        <div class="vendor-head">
          <div>
            <h3>{{ v.name }}</h3>
            <div class="muted">{{ v.id }} · {{ v.region || '地区未填' }}</div>
          </div>
          <span class="pill" :class="v.active ? 'sent' : 'rejected'">{{ v.active ? '合作中' : '已停用' }}</span>
        </div>
        <div class="muted" style="margin:8px 0">{{ Array.isArray(v.categories) ? (v.categories.join(' / ') || '未填品类') : (v.categories || '未填品类') }}</div>
        <div v-if="v.strengths" class="line">{{ v.strengths }}</div>
        <div v-if="v.moq_note || v.price_note" class="muted line">
          <span v-if="v.moq_note">MOQ：{{ v.moq_note }}</span>
          <span v-if="v.price_note"> · {{ v.price_note }}</span>
        </div>
        <div v-if="v.colors || v.materials || v.finishes || v.logo_processes" class="line spec">
          <div v-if="v.colors"><span class="tag-label">颜色</span>{{ v.colors }}</div>
          <div v-if="v.materials"><span class="tag-label">材质</span>{{ v.materials }}</div>
          <div v-if="v.finishes"><span class="tag-label">表面</span>{{ v.finishes }}</div>
          <div v-if="v.logo_processes"><span class="tag-label">LOGO</span>{{ v.logo_processes }}</div>
          <div v-if="v.custom_color"><span class="tag-label">定制色</span>{{ v.custom_color }}</div>
          <div v-if="v.sample_lead_days"><span class="tag-label">打样</span>{{ v.sample_lead_days }}</div>
          <div v-if="v.bulk_lead_days"><span class="tag-label">大货</span>{{ v.bulk_lead_days }}</div>
          <div v-if="v.certifications"><span class="tag-label">认证</span>{{ v.certifications }}</div>
          <div v-if="v.quality_score"><span class="tag-label">评分</span>{{ v.quality_score }}/5</div>
        </div>
        <div v-if="v.preferences" class="pref"><span class="tag-label">喜欢</span>{{ v.preferences }}</div>
        <div v-if="v.memo" class="pref muted"><span class="tag-label">备忘</span>{{ v.memo }}</div>
        <div class="muted" style="margin-top:8px">联系人：{{ v.contact || '-' }} {{ v.phone || '' }}</div>
        <div class="row-actions" style="margin-top:12px">
          <button class="btn ghost sm" @click="edit(v)">编辑</button>
          <button class="btn danger sm" @click="remove(v)">删除</button>
        </div>
      </div>
    </div>
    <div v-if="!filtered.length" class="empty card">暂无厂商，点右上角新增</div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api'

const route = useRoute()

const items = ref([])
const related = ref(null)
const error = ref('')
const saving = ref(false)
const keyword = ref('')
const onlyActive = ref(false)
const form = reactive(emptyForm())

function emptyForm() {
  return {
    id: '',
    name: '',
    region: '',
    contact: '',
    phone: '',
    email: '',
    categories: '',
    colors: '',
    materials: '',
    finishes: '',
    logo_processes: '',
    custom_color: '',
    sample_lead_days: '',
    bulk_lead_days: '',
    payment_terms: '',
    certifications: '',
    quality_score: 3,
    capacity_note: '',
    strengths: '',
    moq_note: '',
    price_note: '',
    preferences: '',
    memo: '',
    notes: '',
    active: true,
  }
}

function resetForm() {
  Object.assign(form, emptyForm())
  related.value = null
}

function startCreate() {
  resetForm()
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

async function edit(v) {
  Object.assign(form, emptyForm(), {
    id: v.id || '',
    name: v.name || '',
    region: v.region || '',
    contact: v.contact || '',
    phone: v.phone || '',
    email: v.email || '',
    categories: Array.isArray(v.categories) ? v.categories.join(', ') : (v.categories || ''),
    colors: v.colors || '',
    materials: v.materials || '',
    finishes: v.finishes || '',
    logo_processes: v.logo_processes || '',
    custom_color: v.custom_color || '',
    sample_lead_days: v.sample_lead_days || '',
    bulk_lead_days: v.bulk_lead_days || '',
    payment_terms: v.payment_terms || '',
    certifications: v.certifications || '',
    quality_score: v.quality_score || 3,
    capacity_note: v.capacity_note || '',
    strengths: v.strengths || '',
    moq_note: v.moq_note || '',
    price_note: v.price_note || '',
    preferences: v.preferences || '',
    memo: v.memo || '',
    notes: v.notes || '',
    active: v.active !== false,
  })
  try {
    related.value = await api.vendorRelated(v.id)
  } catch (_) {
    related.value = null
  }
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

const filtered = computed(() => {
  let list = items.value
  if (onlyActive.value) list = list.filter((v) => v.active !== false)
  const q = keyword.value.trim().toLowerCase()
  if (!q) return list
  return list.filter((v) => {
    const cats = Array.isArray(v.categories) ? v.categories : []
    const blob = [
      v.id, v.name, v.region, v.contact, v.strengths, v.colors, v.materials, v.finishes, v.logo_processes, v.preferences, v.memo, v.notes,
      ...cats,
    ].join(' ').toLowerCase()
    return blob.includes(q)
  })
})

async function openFromQuery() {
  const id = (route.query.id || '').toString().trim()
  if (!id || !items.value.length) return
  const hit = items.value.find((v) => v.id === id)
  if (hit) await edit(hit)
}

async function load() {
  error.value = ''
  try {
    const list = await api.vendors()
    items.value = Array.isArray(list) ? list : []
    await openFromQuery()
  } catch (e) {
    items.value = []
    error.value = e.message || String(e)
  }
}

watch(() => route.query.id, () => {
  openFromQuery()
})

async function save() {
  if (!form.name.trim()) {
    error.value = '请填写厂名'
    return
  }
  saving.value = true
  error.value = ''
  try {
    const payload = { ...form }
    if (!payload.id) delete payload.id
    await api.saveVendor(payload)
    resetForm()
    await load()
  } catch (e) {
    error.value = e.message || String(e)
  } finally {
    saving.value = false
  }
}

async function remove(v) {
  if (!confirm(`确定删除厂商「${v.name}」？`)) return
  try {
    await api.deleteVendor(v.id)
    if (form.id === v.id) resetForm()
    await load()
  } catch (e) {
    error.value = e.message || String(e)
  }
}

onMounted(load)
</script>

<style scoped>
.vendor-grid {
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
}
.vendor-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: flex-start;
}
.vendor-head h3 { margin: 0 0 4px; font-size: 18px; }
.line { margin: 6px 0; font-size: 14px; line-height: 1.45; }
.spec { display: flex; flex-direction: column; gap: 4px; }
.pref { margin-top: 8px; font-size: 14px; line-height: 1.45; }
.tag-label {
  display: inline-block;
  margin-right: 6px;
  padding: 1px 6px;
  border-radius: 6px;
  background: var(--brand-soft, #d9efe9);
  color: var(--brand, #0b5f52);
  font-size: 12px;
}
.memo-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin: 10px 0;
}
@media (max-width: 900px) {
  .memo-grid { grid-template-columns: 1fr; }
}
.search-input {
  flex: 1;
  min-width: 180px;
  padding: 8px 12px;
  border: 1px solid var(--line, #d3ddd7);
  border-radius: 10px;
}
.check {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--muted);
  white-space: nowrap;
}
</style>
