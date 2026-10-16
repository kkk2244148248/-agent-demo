<template>
  <div>
    <div class="topbar">
      <div>
        <h1>需求收件箱</h1>
        <p>海外礼品需求入口：可新建询盘，再点开做找厂 / 比价 / 报价。</p>
      </div>
      <button class="btn" @click="showForm = !showForm">{{ showForm ? '收起表单' : '新建询盘' }}</button>
    </div>

    <div class="filter-bar row-actions" style="margin-bottom:14px">
      <button class="btn ghost sm" :class="{ active: !filter }" @click="setFilter('')">全部</button>
      <button class="btn ghost sm" :class="{ active: filter === 'pending' }" @click="setFilter('pending')">待处理</button>
      <button class="btn ghost sm" :class="{ active: filter === 'awaiting_approval' }" @click="setFilter('awaiting_approval')">等待审批</button>
      <button class="btn ghost sm" :class="{ active: filter === 'processed' }" @click="setFilter('processed')">已出草稿</button>
      <button class="btn ghost sm" :class="{ active: filter === 'sent' }" @click="setFilter('sent')">已发送</button>
    </div>

    <div v-if="error" class="card" style="margin-bottom:12px;color:var(--danger)">{{ error }}</div>

    <div v-if="showForm" class="card" style="margin-bottom:14px">
      <h3>新建询盘</h3>
      <div class="split">
        <div class="field"><label>客户名称 *</label><input v-model="form.customer_name" /></div>
        <div class="field"><label>国家</label><input v-model="form.country" /></div>
        <div class="field"><label>邮箱</label><input v-model="form.from_email" /></div>
        <div class="field"><label>主题 *</label><input v-model="form.subject" /></div>
        <div class="field"><label>产品</label><input v-model="form.product_name" placeholder="500ml 保温杯" /></div>
        <div class="field"><label>数量</label><input v-model="form.qty" placeholder="3000" /></div>
        <div class="field"><label>目标价</label><input v-model="form.target_price" placeholder="3.5-4.5" /></div>
        <div class="field"><label>币种</label><input v-model="form.currency" /></div>
        <div class="field"><label>贸易术语</label><input v-model="form.incoterms" placeholder="FOB Ningbo" /></div>
        <div class="field"><label>目的港/地</label><input v-model="form.destination" /></div>
        <div class="field"><label>交期要求</label><input v-model="form.deadline" /></div>
        <div class="field"><label>颜色</label><input v-model="form.color" /></div>
        <div class="field"><label>材质</label><input v-model="form.material" /></div>
        <div class="field"><label>尺寸</label><input v-model="form.size_spec" /></div>
        <div class="field">
          <label>优先级</label>
          <select v-model="form.priority">
            <option value="high">高</option>
            <option value="medium">中</option>
            <option value="low">低</option>
          </select>
        </div>
      </div>
      <div class="field"><label>需求正文</label><textarea v-model="form.body" style="min-height:100px" /></div>
      <button class="btn" :disabled="saving" @click="create">{{ saving ? '保存中…' : '创建并打开' }}</button>
    </div>

    <div v-if="loading" class="card empty">正在加载…</div>
    <div class="card" v-else>
      <div class="table-wrap">
      <table class="table" v-if="items.length">
        <thead>
          <tr>
            <th>编号</th><th>客户</th><th>产品</th><th>数量</th><th>主题</th><th>时间</th><th>状态</th><th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in items" :key="item.id">
            <td>{{ item.id }}</td>
            <td>{{ item.customer_name }}<div class="muted">{{ item.country }}</div></td>
            <td>{{ item.product_name || '-' }}</td>
            <td>{{ item.qty || '-' }}</td>
            <td>{{ item.subject }}</td>
            <td class="muted">{{ item.received_at }}</td>
            <td><span class="pill" :class="item.status">{{ zhStatus(item.status) }}</span></td>
            <td><router-link class="btn sm" :to="`/inbox/${item.id}`">打开</router-link></td>
          </tr>
        </tbody>
      </table>
      </div>
      <div v-if="!items.length" class="empty">当前没有询盘（筛选：{{ filterLabel }}）</div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import { zhStatus } from '../i18n'

const router = useRouter()
const items = ref([])
const filter = ref('')
const loading = ref(false)
const saving = ref(false)
const showForm = ref(false)
const error = ref('')
const form = reactive({
  customer_name: '',
  country: '',
  from_email: '',
  subject: '',
  body: '',
  product_name: '',
  qty: '',
  target_price: '',
  currency: 'USD',
  incoterms: 'FOB',
  destination: '',
  deadline: '',
  color: '',
  material: '',
  size_spec: '',
  priority: 'medium',
  source_channel: 'email',
})

const filterLabel = computed(() => zhStatus(filter.value) || '全部')

async function load() {
  loading.value = true
  error.value = ''
  try {
    const list = await api.inquiries(filter.value || undefined)
    items.value = Array.isArray(list) ? list : []
  } catch (e) {
    items.value = []
    error.value = e.message || String(e)
  } finally {
    loading.value = false
  }
}

function setFilter(value) {
  filter.value = value
  load()
}

async function create() {
  if (!form.customer_name.trim() || !form.subject.trim()) {
    error.value = '请填写客户名称和主题'
    return
  }
  saving.value = true
  error.value = ''
  try {
    const item = await api.createInquiry({ ...form })
    showForm.value = false
    await router.push(`/inbox/${item.id}`)
  } catch (e) {
    error.value = e.message || String(e)
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.filter-bar .btn.ghost.active {
  background: var(--brand-soft, #d9efe9);
  border-color: #b7ddd3;
  color: var(--brand, #0b5f52);
}
</style>
