<template>
  <div>
    <div class="topbar">
      <div>
        <h1>跟进待办</h1>
        <p>可自建跟进；逾期标红。样品反馈、报价确认别漏。</p>
      </div>
      <button class="btn" @click="startCreate">新建跟进</button>
    </div>

    <div v-if="error" class="card" style="margin-bottom:12px;color:var(--danger)">{{ error }}</div>

    <div class="card" style="margin-bottom:14px">
      <h3>{{ form.id ? `编辑 ${form.id}` : '新建跟进' }}</h3>
      <div class="split">
        <div class="field"><label>客户</label><input v-model="form.customer_name" /></div>
        <div class="field"><label>关联询盘</label><input v-model="form.inquiry_id" placeholder="INQ-001" /></div>
        <div class="field"><label>截止日期</label><input v-model="form.due_date" placeholder="2026-09-10" /></div>
        <div class="field">
          <label>优先级</label>
          <select v-model="form.priority">
            <option value="high">高</option>
            <option value="medium">中</option>
            <option value="low">低</option>
          </select>
        </div>
      </div>
      <div class="field"><label>原因</label><input v-model="form.reason" /></div>
      <div class="field"><label>建议做法</label><input v-model="form.suggested_action" /></div>
      <div class="row-actions">
        <button class="btn" @click="save">保存</button>
        <button class="btn ghost" @click="reset">清空</button>
      </div>
    </div>

    <div
      class="card follow-card"
      v-for="item in items"
      :key="item.id"
      :class="{ overdue: isOverdue(item) }"
    >
      <div class="follow-body">
        <div class="follow-main">
          <div class="follow-title">
            <strong>{{ item.customer_name || '未填客户' }}</strong>
            <span class="muted">截止 {{ item.due_date || '-' }}</span>
            <span v-if="isOverdue(item)" class="pill rejected">逾期</span>
          </div>
          <div class="follow-line">原因：{{ item.reason }}</div>
          <div class="muted follow-line" v-if="item.suggested_action">建议：{{ item.suggested_action }}</div>
          <div class="muted follow-line" v-if="item.inquiry_id">
            询盘：
            <router-link :to="`/inbox/${item.inquiry_id}`">{{ item.inquiry_id }}</router-link>
          </div>
        </div>
        <div class="row-actions follow-actions">
          <span class="pill" :class="item.status || 'open'">{{ zhStatus(item.status || 'open') }}</span>
          <button class="btn ghost sm" @click="edit(item)">编辑</button>
          <button v-if="item.status !== 'done'" class="btn sm" @click="done(item.id)">完成</button>
          <button class="btn danger sm" @click="remove(item)">删除</button>
        </div>
      </div>
    </div>
    <div v-if="!items.length" class="empty card">暂无跟进</div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api } from '../api'
import { zhStatus } from '../i18n'

const items = ref([])
const error = ref('')
const today = new Date().toISOString().slice(0, 10)
const form = reactive(emptyForm())

function emptyForm() {
  return {
    id: '', customer_name: '', inquiry_id: '', due_date: today,
    reason: '', suggested_action: '', priority: 'medium', status: 'open',
  }
}
function reset() { Object.assign(form, emptyForm()) }
function startCreate() { reset(); window.scrollTo({ top: 0, behavior: 'smooth' }) }
function isOverdue(item) {
  return item.status !== 'done' && item.due_date && item.due_date < today
}

async function load() {
  try {
    const list = await api.followups()
    items.value = Array.isArray(list) ? list : []
  } catch (e) {
    items.value = []
    error.value = e.message || String(e)
  }
}

function edit(item) {
  Object.assign(form, emptyForm(), item)
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

async function save() {
  error.value = ''
  try {
    const payload = { ...form }
    if (!payload.id) delete payload.id
    await api.saveFollowup(payload)
    reset()
    await load()
  } catch (e) {
    error.value = e.message || String(e)
  }
}

async function done(id) {
  error.value = ''
  try {
    await api.completeFollowup(id)
    await load()
  } catch (e) {
    error.value = e.message || String(e)
  }
}

async function remove(item) {
  if (!confirm('删除该跟进？')) return
  error.value = ''
  try {
    await api.deleteFollowup(item.id)
    await load()
  } catch (e) {
    error.value = e.message || String(e)
  }
}

onMounted(load)
</script>

<style scoped>
.follow-card { margin-bottom: 12px; }
.follow-body {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  flex-wrap: wrap;
}
.follow-main { flex: 1 1 260px; min-width: 0; }
.follow-title {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
  margin-bottom: 8px;
}
.follow-line { margin-top: 6px; line-height: 1.45; word-break: break-word; }
.follow-actions { flex: 0 1 auto; }
.overdue {
  border-color: #e8b4b0;
  background: #fff8f7;
}
</style>
