<template>
  <div>
    <div class="topbar">
      <div>
        <h1>今日跑单</h1>
        <p>{{ todayText }} · 先看这四件事：有没有客户要回、有没有人忘了跟进、有没有单要炸、有没有钱没到账。</p>
      </div>
      <div class="badge-row">
        <span class="badge" :class="health?.llm?.mock ? 'warn' : 'ok'">
          {{ health?.llm?.mock ? '演示模式' : '智能助手已连接' }}
        </span>
        <span class="badge" :class="health?.kb?.ready ? 'ok' : 'warn'">
          资料库{{ health?.kb?.ready ? '已就绪' : '加载中' }}
        </span>
      </div>
    </div>

    <div v-if="error" class="card mb-12" style="color:var(--danger)">{{ error }}</div>

    <!-- 四个必看 -->
    <div class="kpi-grid mb-16">
      <router-link class="kpi" :class="n('pending_inquiries') ? 'alert-bar' : ''" to="/inbox">
        <div class="kpi-label">待处理询盘</div>
        <div class="kpi-value">{{ n('pending_inquiries') }}</div>
        <div class="kpi-sub">
          <span v-if="n('pending_inquiries')" class="up">新客户等着回</span>
          <span v-else>暂无新询盘</span>
        </div>
      </router-link>

      <router-link class="kpi" :class="n('overdue_followups') ? 'warn-bar' : ''" to="/followups">
        <div class="kpi-label">逾期跟进</div>
        <div class="kpi-value" :class="n('overdue_followups') ? 'text-warn' : ''">{{ n('overdue_followups') }}</div>
        <div class="kpi-sub">客户晾太久会跑</div>
      </router-link>

      <router-link class="kpi" :class="n('delay_red') ? 'alert-bar' : 'ok-bar'" to="/tracking">
        <div class="kpi-label">交期红灯</div>
        <div class="kpi-value" :class="n('delay_red') ? 'text-danger' : 'text-ok'">{{ n('delay_red') }}</div>
        <div class="kpi-sub">
          <span v-if="n('delay_amber')">另有 {{ n('delay_amber') }} 单黄灯</span>
          <span v-else>在产订单按计划</span>
        </div>
      </router-link>

      <router-link class="kpi" :class="n('overdue_collections') ? 'warn-bar' : 'ok-bar'" to="/collections">
        <div class="kpi-label">逾期应收</div>
        <div class="kpi-value" :class="n('overdue_collections') ? 'text-warn' : 'text-ok'">
          ${{ money(data?.overdue_amount) }}
        </div>
        <div class="kpi-sub">{{ n('overdue_collections') }} 张订单逾期</div>
      </router-link>
    </div>

    <!-- 次级指标 -->
    <div class="grid stats mb-16">
      <router-link class="card stat" to="/customers/pool">
        <div class="label">公海待认领</div>
        <div class="value">{{ n('pool_public') }}</div>
        <div class="muted">先到先得</div>
      </router-link>
      <router-link class="card stat" to="/quotations">
        <div class="label">低于底价待特批</div>
        <div class="value" :class="n('below_floor_quotes') ? 'text-danger' : ''">{{ n('below_floor_quotes') }}</div>
        <div class="muted">防飞单、防乱价</div>
      </router-link>
      <router-link class="card stat" to="/samples">
        <div class="label">进行中样品</div>
        <div class="value">{{ n('open_samples') }}</div>
        <div class="muted">打样进度</div>
      </router-link>
      <router-link class="card stat" to="/quotations">
        <div class="label">草稿 / 已发报价</div>
        <div class="value">{{ n('draft_quotations') }}</div>
        <div class="muted">等客户回复</div>
      </router-link>
      <router-link class="card stat" to="/orders">
        <div class="label">进行中订单</div>
        <div class="value">{{ n('active_orders') }}</div>
        <div class="muted">在产 / 待出货</div>
      </router-link>
      <router-link class="card stat" to="/approvals">
        <div class="label">等待审批</div>
        <div class="value">{{ n('pending_approvals') }}</div>
        <div class="muted">待经理放行</div>
      </router-link>
    </div>

    <div v-if="(data?.below_floor_items || []).length" class="card mb-16" style="border-left:3px solid var(--danger)">
      <h3>⚠ 低于底价，需要老板特批<span class="hint">（防止低价飞单）</span></h3>
      <div class="table-wrap">
        <table class="table">
          <thead><tr><th>报价</th><th>客户</th><th>报价金额</th><th>底价</th><th></th></tr></thead>
          <tbody>
            <tr v-for="q in data.below_floor_items" :key="q.id">
              <td class="mono">{{ q.id }}</td>
              <td>{{ q.customer_name || '-' }}</td>
              <td class="num">{{ q.currency }} {{ q.total }}</td>
              <td class="num text-danger">{{ q.floor_price }}</td>
              <td><router-link class="btn ghost sm" to="/quotations">去处理</router-link></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="grid two">
      <div class="card">
        <h3>今日待办</h3>
        <div v-for="t in data?.todos || []" :key="t.type + t.id" class="list-item">
          <div class="title">
            <span class="tag brand">{{ todoTag(t.type) }}</span>
            {{ t.title }}
          </div>
          <div class="muted">{{ t.detail }}</div>
          <router-link class="btn ghost sm mt-8" :to="t.link">去处理</router-link>
        </div>
        <div v-if="!(data?.todos || []).length" class="empty">今天没有待办，可以去公海捞几个新客户</div>
      </div>

      <div class="card">
        <h3>优先询盘</h3>
        <div class="table-wrap" v-if="data?.hot_inquiries?.length">
          <table class="table">
            <thead><tr><th>客户</th><th>主题</th><th>状态</th><th></th></tr></thead>
            <tbody>
              <tr v-for="item in data.hot_inquiries" :key="item.id">
                <td>{{ item.customer_name }}</td>
                <td>{{ item.subject }}</td>
                <td><span class="pill" :class="item.status">{{ zhStatus(item.status) }}</span></td>
                <td><router-link class="btn ghost sm" :to="`/inbox/${item.id}`">打开</router-link></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="empty">暂时没有待处理询盘</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, inject, onMounted, ref } from 'vue'
import { api } from '../api'
import { zhStatus } from '../i18n'

const refreshNav = inject('refreshNav', () => {})
const data = ref(null)
const health = ref(null)
const error = ref('')

const todayText = computed(() =>
  new Date().toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' }),
)

function n(key) {
  const v = data.value?.[key]
  return typeof v === 'number' ? v : 0
}
function money(v) {
  const num = Number(v || 0)
  return num ? num.toLocaleString('en-US', { maximumFractionDigits: 0 }) : '0'
}
function todoTag(type) {
  return { followup: '跟进', inquiry: '询盘', sample: '样品' }[type] || '待办'
}

onMounted(async () => {
  try {
    data.value = await api.dashboard()
    health.value = await api.health()
    refreshNav()
  } catch (e) {
    error.value = e.message || String(e)
  }
})
</script>

<style scoped>
a.card.stat { color: inherit; text-decoration: none; }
</style>
