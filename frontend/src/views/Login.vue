<template>
  <div class="auth">
    <!-- 左：品牌叙事 -->
    <aside class="auth-brand">
      <div class="auth-brand-inner">
        <div class="auth-logo">
          <img src="/logo.svg" alt="海贸工作台" />
          <div class="auth-logo-txt">
            <strong>海贸工作台</strong>
            <span>Haimao Desk</span>
          </div>
        </div>

        <h1 class="auth-headline">
          从询盘到收款，<br />一个人跑完全程。
        </h1>
        <p class="auth-lede">
          为外贸业务员准备的一站式跑单台。今日要跟谁、这单赚多少、工厂到哪一步、谁的钱还没到 —— 一屏看清。
        </p>

        <ul class="auth-points">
          <li>
            <span class="dot"></span>
            <div><strong>今日跑单</strong><em>该跟进、该催款、该推进的，一早排好</em></div>
          </li>
          <li>
            <span class="dot"></span>
            <div><strong>真实毛利</strong><em>含退税、汇率、港杂，不算错每一分钱</em></div>
          </li>
          <li>
            <span class="dot"></span>
            <div><strong>交期红绿灯</strong><em>六个节点盯到底，别到船期才发现来不及</em></div>
          </li>
          <li>
            <span class="dot"></span>
            <div><strong>客户公海</strong><em>私海不倒挂，客户不白丢</em></div>
          </li>
        </ul>

        <div class="auth-foot">内部员工系统 · 仅限公司成员访问</div>
      </div>
      <div class="auth-glow" aria-hidden="true"></div>
    </aside>

    <!-- 右：登录表单 -->
    <main class="auth-panel">
      <div class="auth-form">
        <div class="auth-form-head">
          <h2>登录</h2>
          <p>使用公司分配的账号进入工作台</p>
        </div>

        <form @submit.prevent="onLogin">
          <div class="field">
            <label for="u">账号</label>
            <input
              id="u"
              v-model="username"
              placeholder="请输入账号"
              autocomplete="username"
              spellcheck="false"
            />
          </div>

          <div class="field">
            <label for="p">密码</label>
            <input
              id="p"
              v-model="password"
              type="password"
              placeholder="请输入密码"
              autocomplete="current-password"
            />
          </div>

          <button class="btn block auth-submit" type="submit" :disabled="loading">
            <span v-if="!loading">进入工作台</span>
            <span v-else class="auth-loading"><i></i>正在验证</span>
          </button>
        </form>

        <div v-if="error" class="auth-error">
          <span>!</span>{{ error }}
        </div>

        <!-- 试用账号：折叠式，不喧宾夺主 -->
        <div class="auth-demo">
          <button type="button" class="auth-demo-toggle" @click="showDemo = !showDemo">
            <span>{{ showDemo ? '收起' : '查看' }}试用账号</span>
            <svg viewBox="0 0 16 16" :class="['chev', { open: showDemo }]" aria-hidden="true">
              <path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </button>
          <div v-if="showDemo" class="auth-demo-body">
            <div class="demo-row" v-for="d in demos" :key="d.user">
              <button type="button" class="demo-fill" @click="fill(d.user)">
                <span class="demo-role">{{ d.role }}</span>
                <code>{{ d.user }}</code>
              </button>
              <span class="demo-pw">密码 123456</span>
            </div>
            <p class="demo-note">点账号即可自动填入。人员离职请在「账号管理」中停用，不要删除。</p>
          </div>
        </div>
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, setSession } from '../api'

const router = useRouter()
const username = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')
const showDemo = ref(false)

const demos = [
  { role: '业务员', user: 'liht' },
  { role: '经理', user: 'chenxw' },
  { role: '老板', user: 'zhoum' },
]

function fill(u) {
  username.value = u
  password.value = '123456'
  error.value = ''
}

async function onLogin() {
  error.value = ''
  if (!username.value.trim() || !password.value) {
    error.value = '请填写账号和密码'
    return
  }
  loading.value = true
  try {
    const res = await api.login(username.value.trim(), password.value)
    setSession(res.token, res.user)
    router.replace('/')
  } catch (e) {
    error.value = e.message || String(e)
  } finally {
    loading.value = false
  }
}
</script>
