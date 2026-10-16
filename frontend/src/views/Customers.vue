<template>
  <div>
    <div class="topbar">
      <div>
        <h1>海外客户</h1>
        <p>维护客户档案，记下偏好与备忘（喜欢什么风格、忌讳什么），跟进时不用再翻聊天记录。</p>
      </div>
      <div class="row-actions">
        <router-link class="btn ghost" to="/customers/pool">客户公海 / 认领</router-link>
        <button class="btn" @click="startCreate">新增客户</button>
      </div>
    </div>

    <div v-if="error" class="card" style="margin-bottom:12px;color:var(--danger)">{{ error }}</div>

    <div class="card" style="margin-bottom:14px">
      <h3>{{ form.id ? `编辑：${form.name || form.id}` : '新增客户' }}</h3>
      <div class="split">
        <div class="field"><label>客户名称 *</label><input v-model="form.name" placeholder="公司名" /></div>
        <div class="field"><label>国家/地区</label><input v-model="form.country" placeholder="Sweden" /></div>
        <div class="field"><label>联系人</label><input v-model="form.contact" /></div>
        <div class="field"><label>邮箱</label><input v-model="form.email" /></div>
        <div class="field"><label>电话/WhatsApp</label><input v-model="form.phone" /></div>
        <div class="field">
          <label>渠道</label>
          <select v-model="form.channel">
            <option value="email">邮件</option>
            <option value="whatsapp">WhatsApp</option>
            <option value="电话">电话</option>
            <option value="其他">其他</option>
          </select>
        </div>
        <div class="field">
          <label>优先级</label>
          <select v-model="form.priority">
            <option value="high">高</option>
            <option value="medium">中</option>
            <option value="low">低</option>
          </select>
        </div>
        <div class="field"><label>标签（逗号分隔）</label><input v-model="form.tags" placeholder="零售礼品, 活动" /></div>
        <div class="field"><label>最近联系</label><input v-model="form.last_contact" placeholder="2026-09-05" /></div>
        <div class="field"><label>公司地址</label><input v-model="form.company_address" /></div>
        <div class="field"><label>官网</label><input v-model="form.website" /></div>
        <div class="field"><label>时区</label><input v-model="form.timezone" placeholder="CET / EST" /></div>
        <div class="field"><label>付款条件</label><input v-model="form.payment_terms" placeholder="T/T 30% deposit" /></div>
        <div class="field"><label>偏好贸易术语</label><input v-model="form.preferred_incoterms" placeholder="FOB / CIF" /></div>
        <div class="field"><label>偏好颜色</label><input v-model="form.preferred_colors" /></div>
        <div class="field"><label>偏好材质</label><input v-model="form.preferred_materials" /></div>
      </div>

      <div class="memo-grid">
        <div class="field">
          <label>偏好 / 喜欢什么</label>
          <textarea v-model="form.preferences" placeholder="例如：喜欢简约哑光、偏蓝黑科技风；不喜欢花哨印刷"></textarea>
        </div>
        <div class="field">
          <label>内部备忘</label>
          <textarea v-model="form.memo" placeholder="例如：Q4 下单集中；对方只回邮件；要注意认证"></textarea>
        </div>
      </div>
      <div class="field">
        <label>业务备注</label>
        <textarea v-model="form.notes" style="min-height:80px" placeholder="合作背景、主推品类等"></textarea>
      </div>

      <div class="row-actions">
        <button class="btn" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存' }}</button>
        <button class="btn ghost" type="button" @click="resetForm">清空表单</button>
      </div>
    </div>

    <div v-if="related" class="card" style="margin-bottom:14px">
      <h3>关联业务 · {{ form.name || form.id }}</h3>
      <div class="muted" style="margin-bottom:8px">
        询盘 {{ related.counts?.inquiries || 0 }} ·
        样品 {{ related.counts?.samples || 0 }} ·
        报价 {{ related.counts?.quotations || 0 }} ·
        订单 {{ related.counts?.orders || 0 }}
      </div>
      <div class="split">
        <div>
          <div class="muted">最近询盘</div>
          <div v-for="i in related.inquiries || []" :key="i.id">
            <router-link :to="`/inbox/${i.id}`">{{ i.id }}</router-link> {{ i.subject }}
          </div>
        </div>
        <div>
          <div class="muted">最近报价</div>
          <div v-for="q in related.quotations || []" :key="q.id">{{ q.id }} · {{ q.status }} · {{ q.currency }} {{ q.total }}</div>
        </div>
        <div>
          <div class="muted">最近订单</div>
          <div v-for="o in related.orders || []" :key="o.id">{{ o.id }} · {{ o.product }} · {{ o.status }}</div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="row-actions" style="margin-bottom:10px">
        <input v-model="keyword" class="search-input" placeholder="搜索客户 / 国家 / 偏好…" />
        <button class="btn ghost sm" @click="load">刷新</button>
      </div>
      <div class="table-wrap">
      <table class="table">
        <thead>
          <tr>
            <th>客户</th>
            <th>国家</th>
            <th>联系人</th>
            <th>归属</th>
            <th>优先级</th>
            <th>偏好 / 备忘</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="c in filtered" :key="c.id">
            <td>
              <strong>{{ c.name }}</strong>
              <div class="muted">{{ Array.isArray(c.tags) ? c.tags.join(' / ') : (c.tags || '') }}</div>
            </td>
            <td>{{ c.country || '-' }}</td>
            <td>
              {{ c.contact || '-' }}
              <div class="muted">{{ c.email || c.phone || '' }}</div>
            </td>
            <td>
              <span v-if="c.owner" class="tag brand">{{ c.owner }}</span>
              <span v-else class="pill pending">公海</span>
              <div class="muted" v-if="c.owner && c.recycle_deadline">跟到 {{ c.recycle_deadline }}</div>
            </td>
            <td><span class="pill" :class="c.priority">{{ zhStatus(c.priority) }}</span></td>
            <td class="memo-cell">
              <div v-if="c.preferences"><span class="tag-label">喜欢</span>{{ c.preferences }}</div>
              <div v-if="c.memo" class="muted"><span class="tag-label">备忘</span>{{ c.memo }}</div>
              <div v-if="!c.preferences && !c.memo" class="muted">{{ c.notes || '暂无' }}</div>
            </td>
            <td>
              <div class="row-actions">
                <button class="btn ghost sm" @click="edit(c)">编辑</button>
                <button v-if="!c.owner" class="btn sm" @click="claim(c)">认领</button>
                <button v-else-if="c.owner === me.name" class="btn ghost sm" @click="release(c)">放回公海</button>
                <button class="btn danger sm" @click="remove(c)">删除</button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
      </div>
      <div v-if="!filtered.length" class="empty">暂无客户，点右上角新增</div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api, getUser } from '../api'
import { zhStatus } from '../i18n'

const me = getUser() || {}
const items = ref([])
const related = ref(null)
const error = ref('')
const saving = ref(false)
const keyword = ref('')
const form = reactive(emptyForm())

function emptyForm() {
  return {
    id: '',
    name: '',
    country: '',
    contact: '',
    email: '',
    phone: '',
    channel: 'email',
    tags: '',
    priority: 'medium',
    last_contact: '',
    company_address: '',
    website: '',
    timezone: '',
    payment_terms: '',
    preferred_incoterms: '',
    preferred_colors: '',
    preferred_materials: '',
    preferences: '',
    memo: '',
    notes: '',
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

async function edit(c) {
  Object.assign(form, emptyForm(), {
    id: c.id || '',
    name: c.name || '',
    country: c.country || '',
    contact: c.contact || '',
    email: c.email || '',
    phone: c.phone || '',
    channel: c.channel || 'email',
    tags: Array.isArray(c.tags) ? c.tags.join(', ') : (c.tags || ''),
    priority: c.priority || 'medium',
    last_contact: c.last_contact || '',
    company_address: c.company_address || '',
    website: c.website || '',
    timezone: c.timezone || '',
    payment_terms: c.payment_terms || '',
    preferred_incoterms: c.preferred_incoterms || '',
    preferred_colors: c.preferred_colors || '',
    preferred_materials: c.preferred_materials || '',
    preferences: c.preferences || '',
    memo: c.memo || '',
    notes: c.notes || '',
  })
  try {
    related.value = await api.customerRelated(c.id)
  } catch (_) {
    related.value = null
  }
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

const filtered = computed(() => {
  const q = keyword.value.trim().toLowerCase()
  if (!q) return items.value
  return items.value.filter((c) => {
    const tags = Array.isArray(c.tags) ? c.tags : []
    const blob = [
      c.name, c.country, c.contact, c.email, c.preferences, c.memo, c.notes,
      ...tags,
    ].join(' ').toLowerCase()
    return blob.includes(q)
  })
})

async function load() {
  error.value = ''
  try {
    const list = await api.customers()
    items.value = Array.isArray(list) ? list : []
  } catch (e) {
    items.value = []
    error.value = e.message || String(e)
  }
}

async function save() {
  if (!form.name.trim()) {
    error.value = '请填写客户名称'
    return
  }
  saving.value = true
  error.value = ''
  try {
    await api.saveCustomer({ ...form })
    resetForm()
    await load()
  } catch (e) {
    error.value = e.message || String(e)
  } finally {
    saving.value = false
  }
}

async function claim(c) {
  try {
    await api.claimCustomer(c.id)
    await load()
  } catch (e) {
    error.value = e.message || String(e)
  }
}

async function release(c) {
  if (!confirm(`把「${c.name}」放回公海？其他人可以认领。`)) return
  try {
    await api.releaseCustomer(c.id)
    await load()
  } catch (e) {
    error.value = e.message || String(e)
  }
}

async function remove(c) {
  if (!confirm(`确定删除客户「${c.name}」？`)) return
  try {
    await api.deleteCustomer(c.id)
    if (form.id === c.id) resetForm()
    await load()
  } catch (e) {
    error.value = e.message || String(e)
  }
}

onMounted(load)
</script>

<style scoped>
.memo-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-bottom: 10px;
}
@media (max-width: 900px) {
  .memo-grid { grid-template-columns: 1fr; }
}
.memo-cell {
  max-width: 320px;
  font-size: 14px;
  line-height: 1.45;
}
.tag-label {
  display: inline-block;
  margin-right: 6px;
  padding: 1px 6px;
  border-radius: 6px;
  background: var(--brand-soft, #d9efe9);
  color: var(--brand, #0b5f52);
  font-size: 12px;
}
.search-input {
  flex: 1;
  min-width: 180px;
  padding: 8px 12px;
  border: 1px solid var(--line, #d3ddd7);
  border-radius: 10px;
}
</style>
