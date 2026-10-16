<template>
  <div>
    <div class="topbar">
      <div>
        <h1>{{ inquiry?.id || '礼品需求详情' }}</h1>
        <p>{{ inquiry?.customer_name }} · {{ inquiry?.country }} · {{ inquiry?.received_at }}</p>
      </div>
      <div class="row-actions">
        <button class="btn ghost" @click="addFollowup">加跟进</button>
        <router-link class="btn ghost" to="/agents">Agent 工具台</router-link>
        <router-link class="btn ghost" to="/inbox">返回</router-link>
      </div>
    </div>

    <div v-if="error" class="card" style="margin-bottom:14px;color:var(--danger)">{{ error }}</div>

    <div class="card" style="margin-bottom:14px" v-if="inquiry">
      <h3>询盘规格（可编辑）</h3>
      <div class="split">
        <div class="field"><label>产品</label><input v-model="spec.product_name" /></div>
        <div class="field"><label>数量</label><input v-model="spec.qty" /></div>
        <div class="field"><label>目标价</label><input v-model="spec.target_price" /></div>
        <div class="field"><label>币种</label><input v-model="spec.currency" /></div>
        <div class="field"><label>贸易术语</label><input v-model="spec.incoterms" /></div>
        <div class="field"><label>目的地</label><input v-model="spec.destination" /></div>
        <div class="field"><label>交期</label><input v-model="spec.deadline" /></div>
        <div class="field"><label>颜色</label><input v-model="spec.color" /></div>
        <div class="field"><label>材质</label><input v-model="spec.material" /></div>
        <div class="field"><label>尺寸</label><input v-model="spec.size_spec" /></div>
        <div class="field">
          <label>优先级</label>
          <select v-model="spec.priority">
            <option value="high">高</option>
            <option value="medium">中</option>
            <option value="low">低</option>
          </select>
        </div>
      </div>
      <button class="btn sm" :disabled="savingSpec" @click="saveSpec">{{ savingSpec ? '保存中…' : '保存规格' }}</button>
    </div>

    <div class="card" style="margin-bottom:14px">
      <h3>按需调用 Agent</h3>
      <div class="field">
        <label>你的目标</label>
        <input v-model="userGoal" placeholder="例如：只要找能做保温杯的厂 / 写个询厂微信" />
      </div>
      <div class="row-actions" style="margin-bottom:12px">
        <button class="btn" :disabled="loading" @click="smartRun">智能调度</button>
        <button class="btn ghost" :disabled="loading" @click="previewRoute">先看看会调用谁</button>
        <button class="btn ghost" :disabled="loading || !selectedTools.length" @click="manualRun">只运行勾选</button>
        <button class="btn" :disabled="!canMakeQuote || makingQuote" @click="makeQuote">
          {{ makingQuote ? '生成中…' : '一键生成正式报价' }}
        </button>
      </div>
      <div class="tool-checks">
        <label v-for="t in toolList" :key="t.name" class="tool-check">
          <input type="checkbox" :value="t.name" v-model="selectedTools" />
          <span>{{ t.title }}</span>
        </label>
      </div>
      <div class="muted" style="margin-top:10px" v-if="routeInfo">
        <template v-if="routeInfo.skill_title || routeInfo.skill">
          识别 Skill：<strong>{{ routeInfo.skill_title || routeInfo.skill }}</strong>
          <span v-if="routeInfo.reason"> · {{ routeInfo.reason }}</span>
          <br />
        </template>
        工具链：{{ Array.isArray(routeInfo.tools) ? (routeInfo.tools.join(' → ') || '无') : '无' }}
      </div>
      <div class="trace" style="margin-top:10px" v-if="trace.length">
        <span v-for="(x, i) in trace" :key="i">{{ x }}</span>
      </div>
    </div>

    <div class="split" v-if="inquiry">
      <div class="card">
        <h3>海外需求来信</h3>
        <div class="field"><label>主题</label><input v-model="form.subject" /></div>
        <div class="field"><label>正文</label><textarea v-model="form.body" style="min-height:220px" /></div>
        <div class="row-actions" style="margin-top:12px">
          <button class="btn" :disabled="recommending || !form.body.trim()" @click="recommendReply">
            {{ recommending ? '生成中…' : '推荐回信' }}
          </button>
          <span class="muted">直接用 LLM 根据来信起草，不跑 Agent 工具链</span>
        </div>
      </div>

      <div class="card">
        <h3>已产出结果</h3>
        <div v-if="!hasAny" class="empty">还没有结果。可先「推荐回信」或跑「厂商匹配」。</div>

        <div class="agent-output" v-if="requirement?.category || requirement?.product_summary">
          <div class="ao-title">需求解析</div>
          <div>品类：{{ requirement.category }} · 数量约 {{ requirement.quantity }}</div>
          <div class="muted">{{ requirement.product_summary }}</div>
        </div>

        <div class="agent-output" v-if="(matchedVendors || []).length">
          <div class="ao-title">厂商匹配</div>
          <div v-for="v in matchedVendors" :key="v.vendor_id" style="margin-bottom:8px">
            <strong>{{ v.vendor_id }} · {{ v.vendor_name }}</strong>
            <div class="muted">{{ v.fit_reason }}</div>
          </div>
        </div>

        <div class="agent-output" v-if="(compareOptions || []).length">
          <div class="ao-title">比价建议</div>
          <table class="table">
            <thead><tr><th>厂商</th><th>￥参考</th><th>外币约</th><th>MOQ</th><th>建议</th></tr></thead>
            <tbody>
              <tr v-for="o in compareOptions" :key="o.vendor_id">
                <td>{{ o.vendor_name }}</td>
                <td>{{ o.ref_unit_price_cny }}</td>
                <td>{{ o.foreign_currency }} {{ o.ref_unit_price_foreign }}</td>
                <td>{{ o.moq }}</td>
                <td>{{ o.recommend_level }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="agent-output" v-if="draft">
          <div class="ao-title">推荐回信 / 海外回复草稿</div>
          <textarea v-model="draft" style="min-height:180px" />
        </div>

        <div class="agent-output" v-if="factoryBrief">
          <div class="ao-title">询厂话术</div>
          <textarea v-model="factoryBrief" style="min-height:100px" />
        </div>

        <div class="row-actions" style="margin-top:12px" v-if="draft">
          <button class="btn" :disabled="recommending" @click="recommendReply">
            {{ recommending ? '生成中…' : '重新生成推荐回信' }}
          </button>
          <button class="btn" @click="submitApproval">提交领导审批后再发海外</button>
        </div>
      </div>
    </div>

    <div class="card" style="margin-top:14px">
      <div class="row-actions" style="justify-content:space-between;margin-bottom:8px">
        <h3 style="margin:0">关联报价</h3>
        <router-link class="btn ghost sm" to="/quotations">全部报价</router-link>
      </div>
      <div class="table-wrap" v-if="quotes.length">
      <table class="table">
        <thead><tr><th>编号</th><th>厂商</th><th>金额</th><th>状态</th><th></th></tr></thead>
        <tbody>
          <tr v-for="q in quotes" :key="q.id">
            <td>{{ q.id }}</td>
            <td>{{ q.vendor_name || '-' }}</td>
            <td>{{ q.currency }} {{ q.total || '-' }}</td>
            <td><span class="pill">{{ q.status }}</span></td>
            <td>
              <button v-if="q.status === 'accepted' || q.status === 'sent' || q.status === 'draft'" class="btn ghost sm" @click="toOrder(q)">转订单</button>
            </td>
          </tr>
        </tbody>
      </table>
      </div>
      <div v-else class="empty">暂无报价。跑完比价后点「一键生成正式报价」。</div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'

const route = useRoute()
const router = useRouter()
const inquiry = ref(null)
const toolList = ref([])
const selectedTools = ref(['search_vendors'])
const userGoal = ref('只要找出能做的国内厂商')
const routeInfo = ref(null)
const loading = ref(false)
const savingSpec = ref(false)
const makingQuote = ref(false)
const recommending = ref(false)
const error = ref('')
const form = reactive({ subject: '', body: '' })
const spec = reactive({
  product_name: '', qty: '', target_price: '', currency: 'USD', incoterms: 'FOB',
  destination: '', deadline: '', color: '', material: '', size_spec: '', priority: 'medium',
})
const draft = ref('')
const factoryBrief = ref('')
const localPipe = ref(null)
const quotes = ref([])

const pipeline = computed(() => localPipe.value || inquiry.value?.pipeline || null)
const requirement = computed(() => pipeline.value?.requirement || {})
const matchedVendors = computed(() => pipeline.value?.vendor_match?.matched_vendors || [])
const compareOptions = computed(() => pipeline.value?.compare?.options || pipeline.value?.quote_draft?.options || [])
const trace = computed(() => pipeline.value?.agent_trace || [])
const hasAny = computed(() =>
  !!(requirement.value?.category || matchedVendors.value.length || compareOptions.value.length || draft.value || factoryBrief.value),
)
const canMakeQuote = computed(() => !!(compareOptions.value.length || matchedVendors.value.length || inquiry.value?.product_name))

function syncFromInquiry() {
  draft.value = inquiry.value?.pipeline?.reply_draft || ''
  factoryBrief.value = inquiry.value?.pipeline?.factory_brief || ''
  const i = inquiry.value || {}
  Object.assign(spec, {
    product_name: i.product_name || '',
    qty: i.qty || '',
    target_price: i.target_price || '',
    currency: i.currency || 'USD',
    incoterms: i.incoterms || 'FOB',
    destination: i.destination || '',
    deadline: i.deadline || '',
    color: i.color || '',
    material: i.material || '',
    size_spec: i.size_spec || '',
    priority: i.priority || 'medium',
  })
}

async function loadQuotes() {
  quotes.value = await api.quotations({ inquiry_id: route.params.id })
}

async function load() {
  inquiry.value = await api.inquiry(route.params.id)
  form.subject = inquiry.value.subject
  form.body = inquiry.value.body
  localPipe.value = inquiry.value.pipeline
  syncFromInquiry()
  if (inquiry.value?.pipeline?.route) {
    routeInfo.value = inquiry.value.pipeline.route
  }
  toolList.value = await api.agents()
  await loadQuotes()
}

function baseBody() {
  return {
    inquiry_id: route.params.id,
    subject: form.subject,
    body: form.body,
    customer_name: inquiry.value?.customer_name,
    country: inquiry.value?.country,
    pipeline: pipeline.value || {},
    requirement: requirement.value,
    vendor_match: pipeline.value?.vendor_match,
    compare: pipeline.value?.compare,
  }
}

async function saveSpec() {
  savingSpec.value = true
  error.value = ''
  try {
    await api.updateInquiry(route.params.id, { ...spec, subject: form.subject, body: form.body })
    await load()
  } catch (e) {
    error.value = e.message || String(e)
  } finally {
    savingSpec.value = false
  }
}

async function previewRoute() {
  error.value = ''
  try {
    routeInfo.value = await api.routeAgents({ user_goal: userGoal.value, subject: form.subject, body: form.body })
    selectedTools.value = routeInfo.value.tools || []
  } catch (e) {
    error.value = e.message || String(e)
  }
}

async function smartRun() {
  loading.value = true
  error.value = ''
  try {
    const res = await api.runAgents({ ...baseBody(), user_goal: userGoal.value })
    routeInfo.value = res.route
    if (Array.isArray(res.route?.tools)) selectedTools.value = res.route.tools
    await load()
    localPipe.value = inquiry.value.pipeline
    syncFromInquiry()
    if (!routeInfo.value && inquiry.value?.pipeline?.route) {
      routeInfo.value = inquiry.value.pipeline.route
    }
  } catch (e) {
    error.value = e.message || String(e)
  } finally {
    loading.value = false
  }
}

async function manualRun() {
  loading.value = true
  error.value = ''
  try {
    await api.runAgents({ ...baseBody(), tools: selectedTools.value })
    await load()
    localPipe.value = inquiry.value.pipeline
    syncFromInquiry()
  } catch (e) {
    error.value = e.message || String(e)
  } finally {
    loading.value = false
  }
}

async function makeQuote() {
  makingQuote.value = true
  error.value = ''
  try {
    await api.updateInquiry(route.params.id, { ...spec, subject: form.subject, body: form.body })
    const q = await api.quotationFromInquiry(route.params.id)
    await loadQuotes()
    alert(`已生成报价 ${q.id}`)
  } catch (e) {
    error.value = e.message || String(e)
  } finally {
    makingQuote.value = false
  }
}

async function toOrder(q) {
  try {
    const o = await api.orderFromQuotation(q.id)
    router.push('/orders')
    alert(`已生成订单 ${o.id}`)
  } catch (e) {
    error.value = e.message || String(e)
  }
}

async function addFollowup() {
  const reason = prompt('跟进原因', '确认样品/报价反馈')
  if (!reason) return
  try {
    const due = new Date()
    due.setDate(due.getDate() + 3)
    await api.saveFollowup({
      customer_name: inquiry.value?.customer_name || '',
      customer_id: inquiry.value?.customer_id || '',
      inquiry_id: route.params.id,
      reason,
      suggested_action: '邮件或 WhatsApp 跟进一次',
      due_date: due.toISOString().slice(0, 10),
      priority: inquiry.value?.priority || 'medium',
    })
    alert('已添加跟进')
  } catch (e) {
    error.value = e.message || String(e)
  }
}

async function recommendReply() {
  recommending.value = true
  error.value = ''
  try {
    await api.updateInquiry(route.params.id, { ...spec, subject: form.subject, body: form.body })
    const res = await api.recommendReply(route.params.id, {
      subject: form.subject,
      body: form.body,
      customer_name: inquiry.value?.customer_name,
      country: inquiry.value?.country,
      save: true,
    })
    draft.value = res.reply_draft || ''
    localPipe.value = {
      ...(pipeline.value || {}),
      reply_draft: draft.value,
    }
    await load()
    syncFromInquiry()
  } catch (e) {
    error.value = e.message || String(e)
  } finally {
    recommending.value = false
  }
}

async function submitApproval() {
  try {
    await api.submitApproval(route.params.id, draft.value)
    alert('已提交审批')
    await load()
  } catch (e) {
    error.value = e.message || String(e)
  }
}

onMounted(load)
</script>
