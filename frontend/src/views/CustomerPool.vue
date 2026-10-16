<template>
  <div>
    <div class="topbar">
      <div>
        <h1>客户公海</h1>
        <p>海外客户是公司的资产。没人跟的客户放公海，谁都能认领；已认领的进私海，<strong>{{ recycleDays }} 天</strong>不跟进自动回收回公海，防止"人走了客户也走了"。</p>
      </div>
      <div class="row-actions">
        <button class="btn ghost" @click="load">刷新</button>
        <button class="btn gold" :disabled="busy" @click="runRecycle">执行回收扫描</button>
      </div>
    </div>

    <div v-if="error" class="card mb-12" style="color:var(--danger)">{{ error }}</div>
    <div v-if="toast" class="card mb-12" style="color:var(--ok)">{{ toast }}</div>

    <div class="kpi-grid mb-16">
      <div class="kpi tone-brand">
        <div class="kpi-label">客户总数</div>
        <div class="kpi-value">{{ summary.total ?? '-' }}</div>
        <div class="kpi-sub">全部在册海外客户</div>
      </div>
      <div class="kpi">
        <div class="kpi-label">私海（已归属）</div>
        <div class="kpi-value">{{ summary.private_count ?? '-' }}</div>
        <div class="kpi-sub">业务员在跟</div>
      </div>
      <div class="kpi accent">
        <div class="kpi-label">公海（可认领）</div>
        <div class="kpi-value">{{ summary.public_count ?? '-' }}</div>
        <div class="kpi-sub">先到先得</div>
      </div>
      <div class="kpi" :class="summary.need_attention ? 'alert-bar' : ''">
        <div class="kpi-label">即将被回收</div>
        <div class="kpi-value" :class="summary.need_attention ? 'text-danger' : ''">{{ summary.need_attention ?? 0 }}</div>
        <div class="kpi-sub">3 天内需跟进</div>
      </div>
    </div>

    <div class="grid two even">
      <!-- 私海 -->
      <div class="card flush">
        <div style="padding:16px 20px 12px" class="flex between center">
          <h3 style="margin:0">私海 · 谁在跟谁<span class="hint">（按回收倒计时排序）</span></h3>
          <input v-model="kwPrivate" class="search-input" style="max-width:190px" placeholder="搜索业务员 / 客户" />
        </div>
        <div class="table-wrap">
          <table class="table" v-if="privateFiltered.length">
            <thead>
              <tr><th>客户</th><th>归属</th><th>回收倒计时</th><th>操作</th></tr>
            </thead>
            <tbody>
              <tr v-for="c in privateFiltered" :key="c.id">
                <td>
                  <strong>{{ c.name }}</strong>
                  <div class="muted">{{ flag(c.country) }} {{ c.country || '-' }} · {{ c.contact || '无联系人' }}</div>
                  <div class="muted" v-if="c.memo">📌 {{ c.memo }}</div>
                </td>
                <td>
                  <span class="tag brand">{{ c.owner }}</span>
                  <div class="muted" v-if="c.claimed_at">认领于 {{ (c.claimed_at || '').slice(0, 10) }}</div>
                </td>
                <td style="min-width:150px">
                  <div class="light" :class="lightOf(c)">
                    {{ daysText(c) }}
                  </div>
                  <div class="bar thin mt-8" :class="daysBarClass(c)">
                    <i :style="{ width: barWidth(c) }"></i>
                  </div>
                  <div class="muted">应跟进至 {{ c.recycle_deadline || '-' }}</div>
                </td>
                <td>
                  <div class="row-actions">
                    <button class="btn ghost sm" @click="touch(c)" title="记一次跟进，重置倒计时">已跟进</button>
                    <button class="btn ghost sm" @click="release(c)">放回公海</button>
                    <button v-if="canManage" class="btn ghost sm" @click="openTransfer(c)">转移</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="!privateFiltered.length" class="empty">私海暂时没有客户</div>
      </div>

      <!-- 公海 -->
      <div class="card flush">
        <div style="padding:16px 20px 12px" class="flex between center">
          <h3 style="margin:0">公海 · 待认领<span class="hint">（先认领先归属）</span></h3>
          <input v-model="kwPublic" class="search-input" style="max-width:190px" placeholder="搜索客户 / 国家" />
        </div>
        <div class="table-wrap">
          <table class="table" v-if="publicFiltered.length">
            <thead>
              <tr><th>客户</th><th>来源 / 阶段</th><th>操作</th></tr>
            </thead>
            <tbody>
              <tr v-for="c in publicFiltered" :key="c.id">
                <td>
                  <strong>{{ c.name }}</strong>
                  <div class="muted">{{ flag(c.country) }} {{ c.country || '-' }} · {{ c.channel || 'email' }}</div>
                  <div class="muted" v-if="c.preferences">💡 {{ c.preferences }}</div>
                </td>
                <td>
                  <span class="tag">{{ c.stage || '新询盘' }}</span>
                  <div class="muted" v-if="c.intake_at">入池 {{ (c.intake_at || '').slice(0, 10) }}</div>
                </td>
                <td>
                  <button class="btn sm" :disabled="busy" @click="claim(c)">认领</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="!publicFiltered.length" class="empty">公海已清空，客户都有人跟了</div>
      </div>
    </div>

    <!-- 转移弹窗 -->
    <div v-if="transferTarget" class="overlay" @click.self="transferTarget = null">
      <div class="card dialog">
        <h3>转移客户归属 · {{ transferTarget.name }}</h3>
        <div class="field">
          <label>分配给业务员</label>
          <select v-model="transferTo">
            <option value="">请选择…</option>
            <option v-for="e in employees" :key="e.id || e.name" :value="e.name">{{ e.name }}（{{ e.role }}）</option>
          </select>
        </div>
        <div class="row-actions mt-12">
          <button class="btn" :disabled="!transferTo || busy" @click="doTransfer">确认转移</button>
          <button class="btn ghost" @click="transferTarget = null">取消</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, inject, onMounted, ref } from 'vue'
import { api, getUser } from '../api'

const refreshNav = inject('refreshNav', () => {})
const me = getUser() || {}
const canManage = computed(() => Boolean(me.can_approve || me.is_admin))
const recycleDays = 30

const data = ref({ private: [], public: [], summary: {} })
const employees = ref([])
const error = ref('')
const toast = ref('')
const busy = ref(false)
const kwPrivate = ref('')
const kwPublic = ref('')
const transferTarget = ref(null)
const transferTo = ref('')

const summary = computed(() => data.value.summary || {})
const privateList = computed(() => data.value.private || [])
const publicList = computed(() => data.value.public || [])

const privateFiltered = computed(() => filterBy(privateList.value, kwPrivate.value))
const publicFiltered = computed(() => filterBy(publicList.value, kwPublic.value))

function filterBy(list, kw) {
  const q = (kw || '').trim().toLowerCase()
  if (!q) return list
  return list.filter((c) =>
    [c.name, c.country, c.owner, c.contact, c.memo, c.preferences].join(' ').toLowerCase().includes(q),
  )
}

function flag(country) {
  const map = {
    Sweden: '🇸🇪', USA: '🇺🇸', Japan: '🇯🇵', UAE: '🇦🇪', Germany: '🇩🇪',
    'United States': '🇺🇸', Spain: '🇪🇸', France: '🇫🇷', Italy: '🇮🇹',
    Canada: '🇨🇦', Australia: '🇦🇺', UK: '🇬🇧', Netherlands: '🇳🇱',
  }
  return map[country] || '🌐'
}

function lightOf(c) {
  const d = c.days_left
  if (typeof d !== 'number') return 'green'
  if (d <= 0) return 'red'
  if (d <= 7) return 'amber'
  return 'green'
}
function daysText(c) {
  const d = c.days_left
  if (typeof d !== 'number') return '未设跟进'
  if (d < 0) return `已超期 ${Math.abs(d)} 天`
  if (d === 0) return '今天到期'
  return `还剩 ${d} 天`
}
function barWidth(c) {
  const d = c.days_left
  if (typeof d !== 'number') return '100%'
  const pct = Math.max(0, Math.min(100, (d / recycleDays) * 100))
  return `${pct}%`
}
function daysBarClass(c) {
  const l = lightOf(c)
  return l === 'red' ? 'danger' : l === 'amber' ? 'warn' : ''
}

async function load() {
  error.value = ''
  try {
    data.value = await api.customersPool()
  } catch (e) {
    error.value = e.message || String(e)
  }
}

function flash(msg) {
  toast.value = msg
  setTimeout(() => (toast.value = ''), 2600)
}

async function claim(c) {
  busy.value = true
  error.value = ''
  try {
    await api.claimCustomer(c.id)
    flash(`已认领「${c.name}」，进入你的私海`)
    await load()
    refreshNav()
  } catch (e) {
    error.value = e.message || String(e)
  } finally {
    busy.value = false
  }
}

async function release(c) {
  if (!confirm(`确定把「${c.name}」放回公海？其他人可以认领。`)) return
  busy.value = true
  try {
    await api.releaseCustomer(c.id)
    flash(`「${c.name}」已放回公海`)
    await load()
    refreshNav()
  } catch (e) {
    error.value = e.message || String(e)
  } finally {
    busy.value = false
  }
}

async function touch(c) {
  busy.value = true
  try {
    await api.touchCustomer(c.id)
    flash(`已记录对「${c.name}」的跟进，倒计时重置`)
    await load()
  } catch (e) {
    error.value = e.message || String(e)
  } finally {
    busy.value = false
  }
}

function openTransfer(c) {
  transferTarget.value = c
  transferTo.value = ''
}

async function doTransfer() {
  busy.value = true
  try {
    await api.transferCustomer(transferTarget.value.id, transferTo.value)
    flash(`「${transferTarget.value.name}」已转给 ${transferTo.value}`)
    transferTarget.value = null
    await load()
    refreshNav()
  } catch (e) {
    error.value = e.message || String(e)
  } finally {
    busy.value = false
  }
}

async function runRecycle() {
  if (!confirm('扫描所有私海客户，超过 30 天未跟进的将自动回到公海。继续？')) return
  busy.value = true
  try {
    const r = await api.recycleCustomers()
    flash(r.count ? `已回收 ${r.count} 个客户回公海` : '没有需要回收的客户')
    await load()
    refreshNav()
  } catch (e) {
    error.value = e.message || String(e)
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  await load()
  try {
    employees.value = await api.employees()
  } catch (_) {
    employees.value = []
  }
})
</script>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(10, 26, 23, 0.42);
  backdrop-filter: blur(2px);
  display: grid;
  place-items: center;
  z-index: 60;
  padding: 20px;
}
.dialog { width: min(440px, 100%); box-shadow: var(--shadow-lg); }
</style>
