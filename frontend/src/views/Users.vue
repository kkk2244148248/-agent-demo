<template>
  <div>
    <div class="topbar">
      <div>
        <h1>账号管理</h1>
        <p>可添加新员工账号；离职就点「停用」，对方立刻进不来。</p>
      </div>
    </div>

    <div v-if="error" class="card" style="margin-bottom:12px;color:var(--danger)">{{ error }}</div>

    <div class="card" style="margin-bottom:14px">
      <h3>添加新账号</h3>
      <div class="split">
        <div class="field">
          <label>姓名（必填）</label>
          <input v-model="form.name" placeholder="例如：张三" />
        </div>
        <div class="field">
          <label>登录账号（英文/数字）</label>
          <input v-model="form.username" placeholder="例如：zhangsan" />
        </div>
        <div class="field">
          <label>初始密码</label>
          <input v-model="form.password" placeholder="至少4位" />
        </div>
        <div class="field">
          <label>岗位</label>
          <input v-model="form.role" placeholder="例如：外贸业务员" />
        </div>
      </div>
      <div class="row-actions" style="margin-bottom:10px">
        <label style="display:flex;align-items:center;gap:6px">
          <input type="checkbox" v-model="form.can_approve" />
          可以审批发送
        </label>
        <label style="display:flex;align-items:center;gap:6px">
          <input type="checkbox" v-model="form.is_admin" />
          管理员（可管账号）
        </label>
      </div>
      <button class="btn" :disabled="saving" @click="create">{{ saving ? '保存中…' : '添加账号' }}</button>
    </div>

    <div class="card">
      <h3>现有账号</h3>
      <table class="table">
        <thead>
          <tr>
            <th>姓名</th>
            <th>账号</th>
            <th>岗位</th>
            <th>权限</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="u in items" :key="u.id">
            <td>{{ u.name }}</td>
            <td>{{ u.username }}</td>
            <td>{{ u.role }}</td>
            <td>
              <span v-if="u.is_admin">管理员</span>
              <span v-else-if="u.can_approve">可审批</span>
              <span v-else>普通员工</span>
            </td>
            <td>
              <span class="pill" :class="u.active ? 'sent' : 'rejected'">
                {{ u.active ? '在职可用' : '已停用' }}
              </span>
            </td>
            <td class="row-actions">
              <button v-if="u.active" class="btn danger sm" @click="toggle(u, false)">停用（离职）</button>
              <button v-else class="btn sm" @click="toggle(u, true)">重新启用</button>
              <button class="btn ghost sm" @click="resetPwd(u)">重置密码</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api } from '../api'

const items = ref([])
const error = ref('')
const saving = ref(false)
const initialPassword = ref('')
const form = reactive({
  name: '',
  username: '',
  password: '',
  role: '外贸业务员',
  is_admin: false,
  can_approve: false,
})

function resetForm() {
  form.name = ''
  form.username = ''
  form.password = initialPassword.value
  form.role = '外贸业务员'
  form.is_admin = false
  form.can_approve = false
}

async function load() {
  error.value = ''
  try {
    items.value = await api.users()
  } catch (e) {
    error.value = e.message || String(e)
  }
}

async function create() {
  saving.value = true
  error.value = ''
  try {
    await api.createUser({ ...form })
    resetForm()
    await load()
    alert('账号已添加，请把账号密码告诉本人')
  } catch (e) {
    error.value = e.message || String(e)
  } finally {
    saving.value = false
  }
}

async function toggle(u, active) {
  const tip = active ? `确定重新启用「${u.name}」吗？` : `确定停用「${u.name}」吗？停用后他/她无法再登录。`
  if (!confirm(tip)) return
  try {
    await api.setUserActive(u.id, active)
    await load()
  } catch (e) {
    alert(e.message || String(e))
  }
}

async function resetPwd(u) {
  const pwd = prompt(`给「${u.name}」设置新密码（至少4位）`, '123456')
  if (!pwd) return
  try {
    await api.resetPassword(u.id, pwd)
    alert('密码已重置，请通知本人用新密码登录')
  } catch (e) {
    alert(e.message || String(e))
  }
}

onMounted(async () => {
  await load()
  // 初始密码由后端配置下发，避免前端硬编码
  try {
    const health = await api.health()
    initialPassword.value = health?.default_user_password || ''
    if (!form.password) form.password = initialPassword.value
  } catch (_) {
    /* 拿不到时留空，由管理员自行填写 */
  }
})
</script>
