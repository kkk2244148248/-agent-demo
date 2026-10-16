<template>
  <div>
    <div class="topbar">
      <div>
        <h1>操作记录</h1>
        <p>谁登录了、谁处理了询盘、谁批准发送，都记在这里，方便事后查。</p>
      </div>
    </div>
    <div class="card">
      <div class="table-wrap">
      <table class="table">
        <thead>
          <tr><th>时间</th><th>员工</th><th>做了什么</th><th>对象</th><th>说明</th></tr>
        </thead>
        <tbody>
          <tr v-for="a in items" :key="a.id">
            <td>{{ a.time }}</td>
            <td>{{ a.employee }}</td>
            <td>{{ zhAction(a.action) }}</td>
            <td>{{ a.target }}</td>
            <td class="muted">{{ a.detail }}</td>
          </tr>
        </tbody>
      </table>
      </div>
      <div v-if="!items.length" class="empty">暂无记录</div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'
import { zhAction } from '../i18n'
const items = ref([])
onMounted(async () => {
  try {
    const list = await api.audit()
    items.value = Array.isArray(list) ? list : []
  } catch (_) {
    items.value = []
  }
})
</script>
