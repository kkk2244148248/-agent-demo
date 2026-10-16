<template>
  <div>
    <div class="topbar">
      <div>
        <h1>知识库查询</h1>
        <p>查产品价格、交期、认证等公司口径，大家对外说法保持一致。</p>
      </div>
      <button class="btn ghost" @click="rebuild">重建资料索引</button>
    </div>

    <div v-if="error" class="card" style="margin-bottom:12px;color:var(--danger)">{{ error }}</div>

    <div class="card" style="margin-bottom:14px">
      <div class="field">
        <label>输入要查的内容</label>
        <input v-model="query" placeholder="例如：LH-PM-100 价格 起订量 交期 CE" @keyup.enter="search" />
      </div>
      <button class="btn" @click="search">开始查询</button>
      <div class="muted" style="margin-top:10px" v-if="backend">当前检索方式：{{ backend }}</div>
    </div>

    <div class="card" v-for="(h, i) in hits" :key="i" style="margin-bottom:10px">
      <div style="display:flex;justify-content:space-between">
        <strong>{{ h.source_name }}</strong>
        <span class="muted">相关度 {{ formatScore(h.score) }}</span>
      </div>
      <pre style="white-space:pre-wrap;margin:10px 0 0;font-family:inherit">{{ h.content }}</pre>
    </div>

    <div class="card" style="margin-top:14px">
      <h3>资料文件列表</h3>
      <div class="table-wrap">
      <table class="table">
        <thead><tr><th>路径</th><th>字数</th><th>预览</th></tr></thead>
        <tbody>
          <tr v-for="d in docs" :key="d.path">
            <td>{{ d.path }}</td>
            <td>{{ d.chars }}</td>
            <td class="muted">{{ d.preview }}</td>
          </tr>
        </tbody>
      </table>
      </div>
      <div v-if="!docs.length" class="empty">暂无资料文件</div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'

const query = ref('LH-PM-100 价格 起订量 交期')
const hits = ref([])
const backend = ref('')
const docs = ref([])
const error = ref('')

function formatScore(score) {
  const n = Number(score)
  return Number.isFinite(n) ? n.toFixed(3) : '-'
}

async function search() {
  error.value = ''
  try {
    const res = await api.knowledgeSearch(query.value, 5)
    hits.value = Array.isArray(res?.hits) ? res.hits : []
    backend.value = res?.backend || ''
  } catch (e) {
    hits.value = []
    error.value = e.message || String(e)
  }
}

async function rebuild() {
  try {
    await api.rebuildKb()
    alert('已开始重建，请稍后再查一次')
  } catch (e) {
    alert(e.message || String(e))
  }
}

onMounted(async () => {
  try {
    const list = await api.knowledgeDocs()
    docs.value = Array.isArray(list) ? list : []
  } catch (e) {
    docs.value = []
    error.value = e.message || String(e)
    return
  }
  await search()
})
</script>
