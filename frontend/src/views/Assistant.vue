<template>
  <div class="desk">
    <aside class="desk-side">
      <h1>海贸对话助手</h1>
      <p class="lead">
        你说话 → <b>总控 Agent</b> 识别意图并选 Skill → 交给对应 <b>子 Agent</b> → 子 Agent 再选工具执行。
      </p>

      <div class="side-block">
        <div class="side-label">试试这样说</div>
        <button type="button" class="chip" v-for="ex in examples" :key="ex" @click="useExample(ex)">{{ ex }}</button>
      </div>

      <div class="side-block" v-if="agents.length">
        <div class="side-label">可调度的子 Agent</div>
        <div class="agent-mini" v-for="a in agents" :key="a.id">
          <strong>{{ a.title }}</strong>
          <div class="muted">{{ a.description }}</div>
        </div>
      </div>

      <div class="side-block">
        <div class="side-label">上传 PDF / 图片（表格识别）</div>
        <input
          ref="fileInput"
          type="file"
          accept=".pdf,image/*"
          class="file-input"
          @change="onFile"
        />
        <label class="check"><input type="checkbox" v-model="forceVision" /> 强制视觉模型（扫图更准）</label>
        <div v-if="attached" class="attach-box">
          已附：{{ attached.filename }}
          <button type="button" class="btn ghost sm" @click="clearAttach">移除</button>
        </div>
        <div v-if="uploading" class="muted">上传/识别中…</div>
      </div>

      <div class="side-block">
        <div class="side-label">可选关联询盘（增强上下文）</div>
        <select v-model="inquiryId">
          <option value="">不关联</option>
          <option v-for="i in inquiries" :key="i.id" :value="i.id">
            {{ i.id }} · {{ i.customer_name }} · {{ i.product_name || i.subject }}
          </option>
        </select>
      </div>
    </aside>
    <section class="desk-main">
      <div ref="listEl" class="msg-list">
        <div v-if="!messages.length" class="welcome">
          <h2>今天要处理什么？</h2>
          <p>可直接说「添加厂商…」自动入库，或「打开厂商名录」跳转；也可上传 PDF 识别表格。</p>
        </div>

        <div v-for="(m, idx) in messages" :key="idx" class="msg" :class="m.role">
          <div class="msg-bubble">
            <div class="msg-text">{{ m.text }}</div>

            <div v-if="m.vendors?.length" class="vendor-cards">
              <div v-for="v in m.vendors" :key="v.vendor_id || v.vendor_name" class="vendor-card">
                <div class="vendor-card-head">
                  <div>
                    <strong>{{ v.vendor_name }}</strong>
                    <div class="muted">{{ v.vendor_id }} · {{ v.region || '地区未填' }}</div>
                  </div>
                  <router-link class="btn sm primary" :to="`/vendors?id=${encodeURIComponent(v.vendor_id)}`">
                    查看档案
                  </router-link>
                </div>
                <div v-if="v.fit_reason" class="vendor-line">匹配：{{ v.fit_reason }}</div>
                <div v-if="(v.categories || []).length" class="muted vendor-line">
                  品类：{{ Array.isArray(v.categories) ? v.categories.join(' / ') : v.categories }}
                </div>
                <div v-if="v.strengths" class="vendor-line">{{ v.strengths }}</div>
                <div v-if="v.moq_note || v.price_note" class="muted vendor-line">
                  <span v-if="v.moq_note">MOQ：{{ v.moq_note }}</span>
                  <span v-if="v.price_note"> · {{ v.price_note }}</span>
                </div>
                <div v-if="v.logo_processes || v.materials || v.sample_lead_days" class="muted vendor-line">
                  <span v-if="v.logo_processes">LOGO：{{ v.logo_processes }}</span>
                  <span v-if="v.materials"> · 材质：{{ v.materials }}</span>
                  <span v-if="v.sample_lead_days"> · 打样：{{ v.sample_lead_days }}</span>
                </div>
                <div v-if="v.contact || v.phone" class="muted vendor-line">
                  联系人：{{ v.contact || '-' }} {{ v.phone || '' }}
                </div>
                <div class="action-row">
                  <router-link class="btn ghost sm" :to="`/vendors?id=${encodeURIComponent(v.vendor_id)}`">
                    打开完整信息
                  </router-link>
                  <button class="btn ghost sm" type="button" @click="askAboutVendor(v)">
                    询这家厂
                  </button>
                </div>
              </div>
            </div>

            <div v-if="m.actions?.length" class="action-row">
              <router-link
                v-for="(a, ai) in m.actions.filter(x => x.type === 'link')"
                :key="'l' + ai + (a.path || '')"
                class="btn sm action-btn"
                :to="a.path"
              >{{ a.label || a.path }}</router-link>
              <button
                v-for="(a, ai) in m.actions.filter(x => x.type === 'chat')"
                :key="'c' + ai + (a.message || '')"
                class="btn ghost sm"
                type="button"
                @click="useActionChat(a.message)"
              >{{ a.label || '继续' }}</button>
              <span
                v-for="(a, ai) in m.actions.filter(x => x.type === 'created')"
                :key="'cr' + ai"
                class="created-tag"
              >已创建 {{ a.entity }} {{ a.id }}</span>
            </div>
            <div v-if="m.supervisor" class="trace-box">
              <div>总控：Skill <b>{{ m.supervisor.skill_title || m.supervisor.skill }}</b>
                → {{ m.supervisor.agent_title || m.supervisor.agent }}</div>
              <div class="muted">{{ m.supervisor.reason }}</div>
              <div v-if="m.agentPlan">
                子 Agent 工具：{{ (m.agentPlan.tools || []).join(' → ') || '知识库' }}
                <span class="muted"> · {{ m.agentPlan.reason }}</span>
              </div>
            </div>
          </div>
        </div>

        <div v-if="loading" class="msg assistant">
          <div class="msg-bubble">总控正在识别意图并调度…</div>
        </div>
      </div>

      <form class="composer" @submit.prevent="send">
        <textarea
          v-model="draft"
          rows="3"
          placeholder="输入目标或问题，Enter 发送（Shift+Enter 换行）"
          :disabled="loading"
          @keydown.enter.exact.prevent="send"
        />
        <div class="composer-actions">
          <span class="muted tip">多层调度：总控 → Skill → 子 Agent → 工具</span>
          <button class="btn primary" type="submit" :disabled="loading || !draft.trim()">
            {{ loading ? '调度中…' : '发送' }}
          </button>
        </div>
        <div v-if="error" class="err">{{ error }}</div>
      </form>
    </section>
  </div>
</template>

<script setup>
import { nextTick, onMounted, ref, watch } from 'vue'
import { api } from '../api'

const draft = ref('')
const loading = ref(false)
const error = ref('')
const messages = ref([])
const agents = ref([])
const inquiries = ref([])
const inquiryId = ref('')
const listEl = ref(null)

const examples = [
  '添加厂商：义乌星海杯业，地区义乌，擅长保温杯激光LOGO',
  '打开厂商名录',
  '添加客户 Nordic Retail，国家瑞典',
  '只要找能做 500ml 保温杯激光 LOGO 的厂',
  '写个询厂微信',
  '识别这份 PDF/表格（先点下方上传）',
  '折叠伞 MOQ 一般多少',
]

const attached = ref(null) // { file_path, filename, summary }
const fileInput = ref(null)
const uploading = ref(false)
const forceVision = ref(false)

onMounted(async () => {
  try {
    const [ags, inqs] = await Promise.all([
      api.domainAgents(),
      api.inquiries(),
    ])
    agents.value = Array.isArray(ags) ? ags : []
    inquiries.value = Array.isArray(inqs) ? inqs : []
  } catch (e) {
    error.value = e.message || String(e)
  }
})

watch(messages, async () => {
  await nextTick()
  if (listEl.value) listEl.value.scrollTop = listEl.value.scrollHeight
}, { deep: true })

function useExample(text) {
  draft.value = text
}

function useActionChat(message) {
  if (!message) return
  draft.value = message
}

function askAboutVendor(v) {
  draft.value = `给 ${v.vendor_id || ''} ${v.vendor_name || ''} 写一段询厂微信`
}

async function onFile(ev) {
  const file = ev.target.files?.[0]
  if (!file) return
  uploading.value = true
  error.value = ''
  try {
    const res = await api.uploadDocument(file, {
      hint: draft.value || '识别文字与表格',
      force_vision: forceVision.value,
      parse_now: true,
    })
    attached.value = {
      file_path: res.file_path,
      filename: res.filename || file.name,
      summary: res.summary || res.document?.summary || '',
    }
    messages.value.push({
      role: 'assistant',
      text: `已上传 ${attached.value.filename}。\n${attached.value.summary || ''}\n可直接点发送，或输入「识别这份表格」。`,
    })
    if (!draft.value.trim()) draft.value = '请识别这份文档的文字和表格'
  } catch (e) {
    error.value = e.message || String(e)
  } finally {
    uploading.value = false
    if (fileInput.value) fileInput.value.value = ''
  }
}

function clearAttach() {
  attached.value = null
}

async function send() {
  const text = draft.value.trim()
  if ((!text && !attached.value) || loading.value) return
  const content = text || '请识别上传的文档'
  messages.value.push({
    role: 'user',
    text: attached.value ? `${content}\n（附件：${attached.value.filename}）` : content,
  })
  draft.value = ''
  loading.value = true
  error.value = ''
  try {
    const extra = {}
    if (inquiryId.value) extra.inquiry_id = inquiryId.value
    if (attached.value?.file_path) {
      extra.file_path = attached.value.file_path
      extra.force_vision = forceVision.value
    }
    const res = await api.assistantChat(content, extra)
    messages.value.push({
      role: 'assistant',
      text: res.answer || '（无回答）',
      supervisor: res.supervisor,
      agentPlan: res.agent_plan,
      tools: res.invoked_tools || [],
      vendors: res.vendors || res.pipeline?.vendors || [],
      actions: res.actions || res.nav_links || [],
    })
  } catch (e) {
    error.value = e.message || String(e)
    messages.value.push({
      role: 'assistant',
      text: error.value,
    })
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.desk {
  display: grid;
  grid-template-columns: minmax(240px, 300px) 1fr;
  gap: 16px;
  min-height: calc(100vh - 64px);
}
.desk-side {
  background: #fff;
  border: 1px solid var(--line, #d3ddd7);
  border-radius: 16px;
  padding: 18px 16px;
  align-self: start;
  position: sticky;
  top: 12px;
}
.desk-side h1 {
  margin: 0;
  font-size: 22px;
}
.lead {
  margin: 10px 0 16px;
  color: var(--muted, #5d6b73);
  font-size: 14px;
  line-height: 1.55;
}
.side-block { margin-top: 16px; }
.side-label {
  font-size: 12px;
  font-weight: 700;
  color: var(--muted, #5d6b73);
  margin-bottom: 8px;
  letter-spacing: 0.04em;
}
.chip {
  display: block;
  width: 100%;
  text-align: left;
  margin-bottom: 8px;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid var(--line, #d3ddd7);
  background: #f7faf8;
  font: inherit;
  font-size: 13px;
  line-height: 1.4;
  cursor: pointer;
  color: inherit;
}
.chip:hover { border-color: var(--brand, #0b5f52); }
.agent-mini {
  padding: 8px 0;
  border-bottom: 1px solid var(--line, #d3ddd7);
  font-size: 13px;
}
.agent-mini:last-child { border-bottom: 0; }
.desk-side select {
  width: 100%;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid var(--line, #d3ddd7);
  font: inherit;
}
.file-input {
  width: 100%;
  font-size: 13px;
  margin-bottom: 8px;
}
.check {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--muted, #5d6b73);
  margin-bottom: 8px;
}
.attach-box {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 10px;
  background: #eef6f3;
  border-radius: 8px;
  font-size: 13px;
}
.desk-main {
  display: flex;
  flex-direction: column;
  min-height: calc(100vh - 64px);
  background: #fff;
  border: 1px solid var(--line, #d3ddd7);
  border-radius: 16px;
  overflow: hidden;
}
.msg-list {
  flex: 1;
  overflow: auto;
  padding: 22px 20px;
  background:
    radial-gradient(800px 280px at 10% 0%, #e8f5f1 0%, transparent 55%),
    #f4f7f5;
}
.welcome {
  max-width: 520px;
  margin: 12vh auto 0;
  text-align: center;
}
.welcome h2 { margin: 0 0 10px; font-size: 26px; }
.welcome p { margin: 0; color: var(--muted, #5d6b73); }
.msg {
  display: flex;
  margin-bottom: 14px;
}
.msg.user { justify-content: flex-end; }
.msg.assistant { justify-content: flex-start; }
.msg-bubble {
  max-width: min(720px, 92%);
  padding: 12px 14px;
  border-radius: 14px;
  background: #fff;
  border: 1px solid var(--line, #d3ddd7);
  box-shadow: 0 6px 18px rgba(21, 32, 40, 0.05);
}
.msg.user .msg-bubble {
  background: #d9efe9;
  border-color: #b7ddd3;
}
.msg-text {
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 15px;
  line-height: 1.55;
}
.trace-box {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--line, #d3ddd7);
  font-size: 13px;
  line-height: 1.5;
}
.action-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}
.action-btn {
  text-decoration: none;
}
.vendor-cards {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 12px;
}
.vendor-card {
  padding: 12px;
  border-radius: 12px;
  border: 1px solid #cfe3dd;
  background: #f7fbf9;
}
.vendor-card-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: flex-start;
}
.vendor-line {
  margin-top: 6px;
  font-size: 13px;
  line-height: 1.45;
}
.created-tag {
  display: inline-flex;
  align-items: center;
  padding: 6px 10px;
  border-radius: 8px;
  background: #e8f6ee;
  color: var(--ok, #1f7a45);
  font-size: 13px;
}
.composer {
  border-top: 1px solid var(--line, #d3ddd7);
  padding: 12px 14px 14px;
  background: #fff;
}
.composer textarea {
  width: 100%;
  resize: none;
  border: 1px solid var(--line, #d3ddd7);
  border-radius: 12px;
  padding: 12px 14px;
  font: inherit;
  font-size: 15px;
  outline: none;
}
.composer textarea:focus { border-color: #147a6a; }
.composer-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-top: 10px;
}
.tip { font-size: 12px; }
.err { margin-top: 8px; color: var(--danger, #b42318); font-size: 14px; }
.muted { color: var(--muted, #5d6b73); }

@media (max-width: 960px) {
  .desk { grid-template-columns: 1fr; }
  .desk-side { position: relative; top: 0; }
  .desk-main { min-height: 70vh; }
}
</style>
