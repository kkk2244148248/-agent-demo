<template>
  <div class="fab-wrap" v-if="!isLogin">
    <button
      v-if="!open"
      class="fab"
      type="button"
      title="海贸助手"
      @click="open = true"
    >
      助
    </button>

    <section v-else class="chat-panel" role="dialog" aria-label="海贸助手">
      <header class="chat-head">
        <div>
          <div class="chat-title">海贸助手</div>
          <div class="chat-sub">FAQ → Skill → RAG</div>
        </div>
        <button class="chat-x" type="button" @click="open = false" aria-label="关闭">×</button>
      </header>

      <div ref="listEl" class="chat-list">
        <div v-if="!messages.length" class="chat-hint">
          可问知识（MOQ/口径），或直接说业务目标（如「谁能做折叠伞」会按 Skill 调 Agent）
        </div>
        <div
          v-for="(m, i) in messages"
          :key="i"
          class="bubble"
          :class="m.role"
        >
          <div class="bubble-text">{{ m.text }}</div>
          <div v-if="m.vendors?.length" class="fab-vendors">
            <div v-for="v in m.vendors" :key="v.vendor_id" class="fab-vendor">
              <div><b>{{ v.vendor_name }}</b> <span class="bubble-meta">{{ v.vendor_id }}</span></div>
              <div class="bubble-meta" v-if="v.fit_reason">{{ v.fit_reason }}</div>
              <router-link class="fab-link" :to="`/vendors?id=${encodeURIComponent(v.vendor_id)}`">
                查看完整档案
              </router-link>
            </div>
          </div>
          <div v-if="m.actions?.length" class="fab-actions">
            <router-link
              v-for="(a, ai) in m.actions.filter(x => x.type === 'link')"
              :key="ai + (a.path || '')"
              class="fab-link"
              :to="a.path"
            >{{ a.label }}</router-link>
          </div>
          <div v-if="m.source" class="bubble-meta">来源：{{ sourceLabel(m.source) }}</div>
          <div v-if="m.skill" class="bubble-meta">Skill：{{ m.skillTitle || m.skill }}</div>
          <div v-if="m.tools?.length" class="bubble-meta">工具：{{ m.tools.join(' → ') }}</div>
        </div>
        <div v-if="loading" class="bubble assistant">
          <div class="bubble-text">思考中…</div>
        </div>
      </div>

      <form class="chat-form" @submit.prevent="send">
        <textarea
          v-model="draft"
          rows="2"
          placeholder="输入问题，Enter 发送"
          :disabled="loading"
          @keydown.enter.exact.prevent="send"
        />
        <button class="btn primary send" type="submit" :disabled="loading || !draft.trim()">
          发送
        </button>
      </form>
    </section>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api'

const route = useRoute()
const isLogin = computed(() => route.path === '/login')

const open = ref(false)
const draft = ref('')
const loading = ref(false)
const messages = ref([])
const listEl = ref(null)

function sourceLabel(src) {
  const map = {
    redis: 'Redis 缓存',
    mysql: 'MySQL FAQ',
    rag: 'RAG 知识库',
    skill: 'Skill 调度',
    empty: '-',
    error: '错误',
  }
  return map[src] || src
}

async function scrollBottom() {
  await nextTick()
  const el = listEl.value
  if (el) el.scrollTop = el.scrollHeight
}

watch(messages, () => scrollBottom(), { deep: true })

async function send() {
  const q = draft.value.trim()
  if (!q || loading.value) return
  messages.value.push({ role: 'user', text: q })
  draft.value = ''
  loading.value = true
  try {
    const extra = {}
    if (route.name === 'inquiry' && route.params.id) {
      extra.inquiry_id = route.params.id
    }
    const res = await api.chatAsk(q, extra)
    messages.value.push({
      role: 'assistant',
      text: res.answer || '（无回答）',
      source: res.source,
      skill: res.skill || res.meta?.skill,
      skillTitle: res.skill_title || res.meta?.skill_title,
      tools: res.invoked_tools || res.meta?.invoked_tools || [],
      vendors: res.vendors || [],
      actions: res.actions || res.nav_links || [],
    })
  } catch (err) {
    messages.value.push({
      role: 'assistant',
      text: err.message || String(err),
      source: 'error',
    })
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.fab-wrap {
  position: fixed;
  right: 22px;
  bottom: 22px;
  z-index: 1200;
}

.fab {
  width: 56px;
  height: 56px;
  border: 0;
  border-radius: 50%;
  background: linear-gradient(145deg, #147a6a, #0b5f52);
  color: #fff;
  font-size: 20px;
  font-weight: 700;
  box-shadow: 0 12px 28px rgba(11, 95, 82, 0.35);
}

.fab:hover { filter: brightness(1.05); }

.chat-panel {
  width: min(380px, calc(100vw - 28px));
  height: min(520px, calc(100vh - 48px));
  display: flex;
  flex-direction: column;
  background: #fff;
  border: 1px solid var(--line, #d3ddd7);
  border-radius: 16px;
  box-shadow: 0 18px 48px rgba(21, 32, 40, 0.18);
  overflow: hidden;
}

.chat-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 14px 12px;
  background: linear-gradient(180deg, #12352f, #0b2421);
  color: #e8f3ef;
}

.chat-title { font-size: 17px; font-weight: 700; }
.chat-sub { margin-top: 4px; font-size: 12px; color: #9fc4bb; }

.chat-x {
  border: 0;
  background: transparent;
  color: #cfe3dd;
  font-size: 26px;
  line-height: 1;
  padding: 0 4px;
}

.chat-list {
  flex: 1;
  overflow: auto;
  padding: 14px;
  background: #f4f7f5;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.chat-hint {
  color: var(--muted, #5d6b73);
  font-size: 14px;
  line-height: 1.5;
  padding: 8px;
}

.bubble {
  max-width: 92%;
  padding: 10px 12px;
  border-radius: 12px;
  background: #fff;
  border: 1px solid var(--line, #d3ddd7);
}

.bubble.user {
  align-self: flex-end;
  background: #d9efe9;
  border-color: #b7ddd3;
}

.bubble.assistant { align-self: flex-start; }

.bubble-text {
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 15px;
  line-height: 1.5;
}

.bubble-meta {
  margin-top: 6px;
  font-size: 12px;
  color: var(--muted, #5d6b73);
}
.fab-vendors { margin-top: 8px; display: flex; flex-direction: column; gap: 8px; }
.fab-vendor {
  padding: 8px;
  border-radius: 8px;
  background: #f7fbf9;
  border: 1px solid #cfe3dd;
  font-size: 13px;
}
.fab-actions { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.fab-link {
  display: inline-block;
  margin-top: 6px;
  font-size: 12px;
  color: var(--brand, #0b5f52);
  font-weight: 600;
  text-decoration: none;
}

.chat-form {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 8px;
  padding: 10px;
  border-top: 1px solid var(--line, #d3ddd7);
  background: #fff;
}

.chat-form textarea {
  resize: none;
  border: 1px solid var(--line, #d3ddd7);
  border-radius: 10px;
  padding: 8px 10px;
  outline: none;
}

.chat-form textarea:focus { border-color: #147a6a; }

.send {
  align-self: end;
  min-width: 72px;
  height: 40px;
}
</style>
