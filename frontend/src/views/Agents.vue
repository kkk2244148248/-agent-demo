<template>
  <div>
    <div class="topbar">
      <div>
        <h1>Agent 工具台（Skill + MCP）</h1>
        <p>
          点某个 Skill 试跑；或点下方单个 Agent。询盘详情里也可「智能调度」。
        </p>
      </div>
      <router-link class="btn ghost" to="/inbox">去收件箱选询盘</router-link>
    </div>

    <div class="card" style="margin-bottom:14px">
      <h3>快速试用：只找厂</h3>
      <div class="field">
        <label>你想找什么厂商？（可直接输入）</label>
        <input v-model="quickQuery" placeholder="例如：500ml 保温杯 激光LOGO 谁能做" />
      </div>
      <div class="row-actions">
        <button class="btn" :disabled="loading" @click="quickFind">只运行「厂商匹配」</button>
        <button class="btn ghost" :disabled="loading" @click="runSkillById('find_vendor', quickQuery)">按 Skill 找厂</button>
      </div>
      <div v-if="runError" style="color:var(--danger);margin-top:10px">{{ runError }}</div>
      <div v-if="lastRoute" class="muted" style="margin-top:10px">
        最近：Skill <strong>{{ lastRoute.skill_title || lastRoute.skill }}</strong>
        · {{ Array.isArray(lastRoute.tools) ? lastRoute.tools.join(' → ') : '' }}
        <span v-if="lastRoute.reason"> · {{ lastRoute.reason }}</span>
      </div>
      <div v-if="quickResult" style="margin-top:12px">
        <div class="muted">{{ quickResult.summary }}</div>
        <div v-for="v in quickResult.vendor_match?.matched_vendors || []" :key="v.vendor_id" style="margin-top:8px">
          <strong>{{ v.vendor_id }} · {{ v.vendor_name }}</strong>
          <div class="muted">{{ v.fit_reason }}</div>
        </div>
      </div>
      <div v-if="skillResultText" class="result-box">{{ skillResultText }}</div>
    </div>

    <div class="card" style="margin-bottom:14px">
      <h3>Skill 目录（点卡片运行）</h3>
      <p class="muted" style="margin:0 0 12px">智能调度会先选一个 Skill，再执行其 tools。下面可手动点开试。</p>
      <div class="skill-grid">
        <button
          type="button"
          class="skill-card"
          v-for="s in skills"
          :key="s.id"
          :disabled="loading || s.mode === 'kb'"
          @click="runSkillById(s.id, goalForSkill(s))"
        >
          <div class="skill-id">{{ s.id }}</div>
          <div class="skill-title">{{ s.title }}</div>
          <div class="muted skill-when">{{ s.when || s.description }}</div>
          <div class="skill-tools">
            <template v-if="s.mode === 'kb'">知识问答（请用右下角助手）</template>
            <template v-else>
              工具：{{ (s.tools || []).join(' → ') || '无' }}
              <span class="skill-cta">点击试跑 →</span>
            </template>
          </div>
        </button>
      </div>
      <div v-if="!skills.length" class="empty">
        {{ runError || '暂无 Skill（检查后端 /api/skills）' }}
      </div>
    </div>

    <div class="agent-flow" style="grid-template-columns: repeat(auto-fit,minmax(240px,1fr))">
      <button
        type="button"
        class="agent-card clickable"
        v-for="a in tools"
        :key="a.name"
        :disabled="loading"
        @click="runOne(a.name)"
      >
        <div class="agent-step">独立工具 · 点击运行</div>
        <div class="agent-name">{{ a.title }}</div>
        <div class="agent-job">{{ a.description }}</div>
        <div class="muted" style="margin-bottom:10px">何时用：{{ a.when_to_use }}</div>
        <div class="muted" style="font-size:12px">工具名：{{ a.name }}</div>
      </button>
    </div>

    <div class="card" style="margin-top:14px">
      <h3>调度方式说明</h3>
      <ul style="margin:0;padding-left:22px;line-height:1.9;font-size:16px">
        <li><b>Skill 智能调度</b>：在询盘详情输入目标，点「智能调度」</li>
        <li><b>点 Skill 卡片</b>：本页直接试跑对应工具链</li>
        <li><b>点 Agent 卡片</b>：只跑某一个工具</li>
        <li><b>悬浮助手</b>：右下角「助」，可说「谁能做折叠伞」</li>
      </ul>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'

const tools = ref([])
const skills = ref([])
const quickQuery = ref('500ml 保温杯 激光LOGO 谁能做')
const quickResult = ref(null)
const skillResultText = ref('')
const runError = ref('')
const loading = ref(false)
const lastRoute = ref(null)

onMounted(async () => {
  try {
    const [agentList, skillList] = await Promise.all([api.agents(), api.skills()])
    tools.value = Array.isArray(agentList) ? agentList : []
    skills.value = Array.isArray(skillList) ? skillList : []
  } catch (e) {
    tools.value = []
    skills.value = []
    runError.value = e.message || String(e)
  }
})

function goalForSkill(s) {
  const map = {
    find_vendor: quickQuery.value || '找能做保温杯的厂',
    full_rfq: '全套方案：解析、找厂、比价、回海外',
    ask_factory: '写个询厂微信',
    reply_overseas: '写一封回海外的邮件',
    compare_quotes: '做个比价方案',
    sample_track: '看看样品进度',
    cert_check: '查一下认证清单',
    parse_requirement: '帮我拆一下需求',
  }
  return map[s.id] || s.title
}

function summarizeRun(res) {
  lastRoute.value = res.route || null
  const traces = res.agent_trace || []
  const vendors = res.pipeline?.vendor_match?.matched_vendors || []
  const lines = []
  if (res.route?.skill_title || res.route?.skill) {
    lines.push(`Skill：${res.route.skill_title || res.route.skill}`)
  }
  if (traces.length) lines.push(...traces.map((t) => `· ${t}`))
  if (vendors.length) {
    lines.push('匹配厂商：')
    vendors.slice(0, 5).forEach((v) => {
      lines.push(`· ${v.vendor_id} ${v.vendor_name}`)
    })
  }
  if (res.pipeline?.reply_draft) lines.push(`海外草稿：${String(res.pipeline.reply_draft).slice(0, 200)}…`)
  if (res.pipeline?.factory_brief) lines.push(`询厂：${String(res.pipeline.factory_brief).slice(0, 200)}…`)
  if (res.summary) lines.push(res.summary)
  skillResultText.value = lines.join('\n') || '已执行'
  if (res.vendor_match) quickResult.value = res
  else if (res.pipeline?.vendor_match) quickResult.value = { summary: res.route?.reason, vendor_match: res.pipeline.vendor_match }
}

async function quickFind() {
  loading.value = true
  runError.value = ''
  quickResult.value = null
  skillResultText.value = ''
  try {
    const res = await api.runOneAgent('search_vendors', { query: quickQuery.value })
    quickResult.value = res
    skillResultText.value = res.summary || '完成'
  } catch (e) {
    runError.value = e.message || String(e)
  } finally {
    loading.value = false
  }
}

async function runSkillById(skillId, goal) {
  loading.value = true
  runError.value = ''
  skillResultText.value = ''
  try {
    // 先看路由，再按该 skill 的 tools 执行（避免 LLM 改选别的 skill）
    const skill = skills.value.find((s) => s.id === skillId)
    if (!skill || skill.mode === 'kb') {
      runError.value = '该 Skill 请用右下角助手问答'
      return
    }
    const toolsToRun = Array.isArray(skill.tools) ? skill.tools : []
    if (!toolsToRun.length) {
      runError.value = '该 Skill 没有可执行工具'
      return
    }
    const res = await api.runAgents({
      user_goal: goal || skill.title,
      tools: toolsToRun,
      query: quickQuery.value,
      subject: goal || skill.title,
      body: quickQuery.value,
    })
    // 补上 skill 展示信息（手动 tools 时后端标为 manual）
    res.route = {
      ...(res.route || {}),
      skill: skill.id,
      skill_title: skill.title,
      reason: `手动点选 Skill「${skill.title}」`,
      tools: toolsToRun,
    }
    summarizeRun(res)
  } catch (e) {
    runError.value = e.message || String(e)
  } finally {
    loading.value = false
  }
}

async function runOne(name) {
  loading.value = true
  runError.value = ''
  skillResultText.value = ''
  try {
    const res = await api.runOneAgent(name, {
      query: quickQuery.value,
      subject: quickQuery.value,
      body: quickQuery.value,
    })
    summarizeRun({
      ...res,
      route: { skill: 'manual', skill_title: '单工具', tools: [name], reason: `运行 ${name}` },
      agent_trace: res.summary ? [`${name} → ${res.summary}`] : [`${name} → 完成`],
      pipeline: res,
    })
    if (res.vendor_match) quickResult.value = res
  } catch (e) {
    runError.value = e.message || String(e)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.skill-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
}
.skill-card {
  border: 1px solid var(--line, #d3ddd7);
  border-radius: 12px;
  padding: 14px;
  background: #f7faf8;
  text-align: left;
  cursor: pointer;
  font: inherit;
  color: inherit;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.skill-card:hover:not(:disabled) {
  border-color: var(--brand, #0b5f52);
  box-shadow: 0 6px 18px rgba(11, 95, 82, 0.12);
}
.skill-card:disabled {
  opacity: 0.65;
  cursor: not-allowed;
}
.skill-id {
  font-size: 12px;
  color: var(--brand, #0b5f52);
  font-weight: 700;
  margin-bottom: 4px;
}
.skill-title {
  font-size: 16px;
  font-weight: 700;
  margin-bottom: 6px;
}
.skill-when {
  font-size: 13px;
  line-height: 1.45;
  margin-bottom: 8px;
}
.skill-tools {
  font-size: 13px;
  font-weight: 600;
  color: var(--ink, #152028);
  word-break: break-word;
}
.skill-cta {
  display: block;
  margin-top: 8px;
  color: var(--brand, #0b5f52);
  font-size: 13px;
}
.agent-card.clickable {
  cursor: pointer;
  text-align: left;
  font: inherit;
  color: inherit;
  width: 100%;
}
.agent-card.clickable:hover:not(:disabled) {
  border-color: var(--brand, #0b5f52);
}
.agent-card.clickable:disabled {
  opacity: 0.6;
  cursor: wait;
}
.result-box {
  margin-top: 12px;
  padding: 12px;
  background: #f4f7f5;
  border-radius: 10px;
  white-space: pre-wrap;
  font-size: 14px;
  line-height: 1.5;
}
</style>
