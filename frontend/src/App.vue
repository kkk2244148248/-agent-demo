<template>
  <div class="app-root">
    <div v-if="isLoginPage">
      <router-view />
    </div>
    <div v-else class="shell">
      <aside class="side">
        <div class="brand">
          <div class="name">
            <img src="/logo.svg" alt="" width="30" height="30" />
            海贸工作台
          </div>
          <div class="sub">{{ health?.company || 'HAIMAO DESK · 内部专用' }}</div>
        </div>

        <nav class="nav">
          <div class="nav-group">
            <div class="nav-group-title">跑单</div>
            <router-link to="/"><span class="ic">◉</span>今日跑单</router-link>
            <router-link to="/assistant"><span class="ic">✦</span>对话助手</router-link>
          </div>

          <div class="nav-group">
            <div class="nav-group-title">客户与需求</div>
            <router-link to="/inbox">
              <span class="ic">✉</span>需求收件箱
              <span v-if="n('pending_inquiries')" class="tag hot">{{ n('pending_inquiries') }}</span>
            </router-link>
            <router-link to="/customers/pool">
              <span class="ic">◇</span>客户公海
              <span v-if="n('pool_public')" class="tag">{{ n('pool_public') }}</span>
            </router-link>
            <router-link to="/customers"><span class="ic">▤</span>海外客户</router-link>
            <router-link to="/followups">
              <span class="ic">⏰</span>跟进待办
              <span v-if="n('overdue_followups')" class="tag hot">{{ n('overdue_followups') }}</span>
            </router-link>
          </div>

          <div class="nav-group">
            <div class="nav-group-title">报价与成交</div>
            <router-link to="/quotations">
              <span class="ic">＄</span>报价单
              <span v-if="n('below_floor_quotes')" class="tag hot">{{ n('below_floor_quotes') }}</span>
            </router-link>
            <router-link to="/samples"><span class="ic">◈</span>样品进度</router-link>
            <router-link to="/orders"><span class="ic">▣</span>订单</router-link>
          </div>

          <div class="nav-group">
            <div class="nav-group-title">生产与回款</div>
            <router-link to="/tracking">
              <span class="ic">⚑</span>生产跟单
              <span v-if="n('delay_red')" class="tag hot">{{ n('delay_red') }}</span>
            </router-link>
            <router-link to="/collections">
              <span class="ic">¥</span>收款账期
              <span v-if="n('overdue_collections')" class="tag hot">{{ n('overdue_collections') }}</span>
            </router-link>
          </div>

          <div class="nav-group">
            <div class="nav-group-title">管理与资料</div>
            <router-link to="/approvals">
              <span class="ic">✓</span>发送审批
              <span v-if="n('pending_approvals')" class="tag">{{ n('pending_approvals') }}</span>
            </router-link>
            <router-link to="/vendors"><span class="ic">⬢</span>厂商名录</router-link>
            <router-link to="/knowledge"><span class="ic">▦</span>知识库</router-link>
            <router-link to="/agents"><span class="ic">⚙</span>Skill / 工具</router-link>
            <router-link to="/audit"><span class="ic">≡</span>操作记录</router-link>
            <router-link v-if="user?.is_admin" to="/users"><span class="ic">☰</span>账号管理</router-link>
          </div>
        </nav>

        <div class="side-foot">
          <div class="user-box">
            <div class="avatar">{{ (user?.name || '?').slice(0, 1) }}</div>
            <div>
              <div class="user-name">{{ user?.name || '未登录' }}</div>
              <div class="user-role">{{ user?.role || '' }}</div>
            </div>
          </div>
          <button class="btn ghost logout-btn sm" @click="onLogout">退出登录</button>
        </div>
      </aside>

      <main class="main">
        <div v-if="bootError" class="card" style="margin-bottom:12px;color:var(--danger)">
          {{ bootError }}
          <div class="row-actions" style="margin-top:8px">
            <button class="btn sm" @click="bootstrap">重试连接</button>
          </div>
        </div>
        <div v-if="pageError" class="card" style="margin-bottom:12px;color:var(--danger)">
          页面出错：{{ pageError }}
          <button class="btn ghost sm" style="margin-left:8px" @click="pageError = ''">关闭</button>
        </div>
        <router-view />
      </main>
    </div>
    <FloatingChat v-if="!isLoginPage" />
  </div>
</template>

<script setup>
import { computed, onErrorCaptured, onMounted, provide, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, clearSession, getToken, getUser } from './api'
import FloatingChat from './components/FloatingChat.vue'

const route = useRoute()
const router = useRouter()
const user = ref(getUser())
const health = ref(null)
const bootError = ref('')
const pageError = ref('')
const nav = ref(null)
const isLoginPage = computed(() => route.path === '/login')

function n(key) {
  const v = nav.value?.[key]
  return typeof v === 'number' && v > 0 ? v : 0
}

async function refreshNav() {
  try {
    nav.value = await api.dashboard()
  } catch (_) {
    /* 角标失败不影响使用 */
  }
}
// 页面内可调用：router-view 之外更新角标
provide('refreshNav', refreshNav)

onErrorCaptured((err) => {
  pageError.value = err?.message || String(err)
  console.error('page crash', err)
  return false
})

watch(
  () => route.path,
  (path) => {
    user.value = getUser()
    pageError.value = ''
    refreshNav()
    if (path !== '/login' && getToken() && !user.value) {
      bootstrap()
    }
  },
)

async function bootstrap() {
  if (isLoginPage.value) return
  if (!getToken()) {
    router.replace({ path: '/login', query: { redirect: route.fullPath } })
    return
  }
  bootError.value = ''
  try {
    user.value = await api.me()
    health.value = await api.health()
    await refreshNav()
  } catch (e) {
    const msg = e?.message || String(e)
    // 仅未登录才踢回登录页；网络抖动不要整页清空
    if (msg.includes('未登录') || msg.includes('401')) {
      clearSession()
      router.replace({ path: '/login', query: { redirect: route.fullPath } })
      return
    }
    bootError.value = `后端连接异常：${msg}`
  }
}

async function onLogout() {
  try {
    await api.logout()
  } catch (_) {}
  clearSession()
  router.push('/login')
}

onMounted(bootstrap)
</script>
