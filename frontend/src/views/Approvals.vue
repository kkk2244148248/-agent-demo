<template>
  <div>
    <div class="topbar">
      <div>
        <h1>发送审批</h1>
        <p>业务员先出草稿，经理或老板确认后才算发送。防止智能助手乱承诺。</p>
      </div>
      <div class="row-actions">
        <button class="btn ghost sm" @click="status='pending'; load()">待审批</button>
        <button class="btn ghost sm" @click="status='approved'; load()">已通过</button>
        <button class="btn ghost sm" @click="status='rejected'; load()">已驳回</button>
      </div>
    </div>

    <div class="card" v-for="item in items" :key="item.id" style="margin-bottom:12px">
      <div class="approval-head">
        <div>
          <strong>{{ item.id }}</strong>
          <div class="muted" style="margin-top:4px">询盘 {{ item.inquiry_id }} · 提交人 {{ item.created_by }}</div>
        </div>
        <span class="pill" :class="item.status">{{ zhStatus(item.status) }}</span>
      </div>
      <div class="field" style="margin-top:12px">
        <label>准备发送的内容</label>
        <textarea v-model="edits[item.id]" :disabled="item.status!=='pending'" />
      </div>
      <div class="row-actions" v-if="item.status==='pending'">
        <button class="btn" @click="decide(item, true)">确认发送</button>
        <button class="btn danger" @click="decide(item, false)">驳回重写</button>
      </div>
      <div class="muted" v-else style="margin-top:8px">
        {{ item.reviewed_by }} 于 {{ item.reviewed_at }} 处理完成
      </div>
    </div>

    <div v-if="!items.length" class="card empty">当前没有审批单</div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api } from '../api'
import { zhStatus } from '../i18n'

const items = ref([])
const status = ref('pending')
const edits = reactive({})

async function load() {
  try {
    const list = await api.approvals(status.value)
    items.value = Array.isArray(list) ? list : []
    for (const item of items.value) {
      edits[item.id] = item.final_text || item.draft
    }
  } catch (e) {
    items.value = []
    alert(e.message || String(e))
  }
}

async function decide(item, approve) {
  try {
    await api.decideApproval(item.id, approve, edits[item.id] || item.draft)
    await load()
  } catch (e) {
    alert(e.message || String(e))
  }
}

onMounted(load)
</script>

<style scoped>
.approval-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  flex-wrap: wrap;
}
</style>
