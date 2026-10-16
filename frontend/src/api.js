const TOKEN_KEY = 'trade_desk_token'
const USER_KEY = 'trade_desk_user'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function getUser() {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) || 'null')
  } catch {
    return null
  }
}

export function setSession(token, user) {
  localStorage.setItem(TOKEN_KEY, token || '')
  localStorage.setItem(USER_KEY, JSON.stringify(user || null))
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

async function request(path, options = {}) {
  const headers = {
    ...(options.headers || {}),
  }
  if (!(options.body instanceof FormData)) {
    headers['Content-Type'] = headers['Content-Type'] || 'application/json'
  }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`

  let res
  try {
    res = await fetch(path, { ...options, headers })
  } catch (err) {
    throw new Error(`网络请求失败：${err.message || err}`)
  }

  if (res.status === 401) {
    clearSession()
    // 避免硬跳转打断 Vue；交给路由守卫处理
    if (!path.includes('/auth/login') && !window.location.pathname.includes('/login')) {
      try {
        window.dispatchEvent(new CustomEvent('trade-desk:unauthorized'))
      } catch (_) {}
    }
    throw new Error('未登录或登录已失效，请重新登录')
  }

  if (!res.ok) {
    let detail = res.statusText
    try {
      const data = await res.json()
      detail = data.detail || JSON.stringify(data)
    } catch (_) {}
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  if (res.status === 204) return null
  return res.json()
}

export const api = {
  health: () => request('/api/health'),
  login: (username, password) =>
    request('/api/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) }),
  logout: () => request('/api/auth/logout', { method: 'POST', body: '{}' }),
  me: () => request('/api/auth/me'),
  users: () => request('/api/users'),
  createUser: (body) => request('/api/users', { method: 'POST', body: JSON.stringify(body) }),
  setUserActive: (id, active) =>
    request(`/api/users/${id}/active`, { method: 'POST', body: JSON.stringify({ active }) }),
  resetPassword: (id, new_password) =>
    request(`/api/users/${id}/password`, { method: 'POST', body: JSON.stringify({ new_password }) }),
  dashboard: () => request('/api/dashboard'),
  agents: () => request('/api/agents'),
  skills: () => request('/api/skills'),
  domainAgents: () => request('/api/assistant/agents'),
  assistantChat: (message, extra = {}) =>
    request('/api/assistant/chat', { method: 'POST', body: JSON.stringify({ message, ...extra }) }),
  uploadDocument: async (file, opts = {}) => {
    const fd = new FormData()
    fd.append('file', file)
    if (opts.hint) fd.append('hint', opts.hint)
    if (opts.force_vision) fd.append('force_vision', 'true')
    fd.append('parse_now', opts.parse_now === false ? 'false' : 'true')
    const token = getToken()
    const headers = {}
    if (token) headers.Authorization = `Bearer ${token}`
    const res = await fetch('/api/documents/upload', { method: 'POST', headers, body: fd })
    if (res.status === 401) {
      clearSession()
      throw new Error('未登录或登录已失效，请重新登录')
    }
    if (!res.ok) {
      let detail = res.statusText
      try {
        const data = await res.json()
        detail = data.detail || JSON.stringify(data)
      } catch (_) {}
      throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
    }
    return res.json()
  },
  parseDocument: (body) =>
    request('/api/documents/parse', { method: 'POST', body: JSON.stringify(body || {}) }),
  routeAgents: (body) => request('/api/agents/route', { method: 'POST', body: JSON.stringify(body || {}) }),
  runAgents: (body) => request('/api/agents/run', { method: 'POST', body: JSON.stringify(body || {}) }),
  runOneAgent: (name, body) =>
    request(`/api/agents/${name}`, { method: 'POST', body: JSON.stringify(body || {}) }),
  samples: (status) => request(status ? `/api/samples?status=${encodeURIComponent(status)}` : '/api/samples'),
  saveSample: (body) => request('/api/samples', { method: 'POST', body: JSON.stringify(body) }),
  employees: () => request('/api/employees'),
  inquiries: (status) => request(status ? `/api/inquiries?status=${encodeURIComponent(status)}` : '/api/inquiries'),
  inquiry: (id) => request(`/api/inquiries/${encodeURIComponent(id)}`),
  createInquiry: (body) => request('/api/inquiries', { method: 'POST', body: JSON.stringify(body) }),
  updateInquiry: (id, body) =>
    request(`/api/inquiries/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(body) }),
  processInquiry: (id, body) =>
    request(`/api/inquiries/${id}/process`, { method: 'POST', body: JSON.stringify(body || {}) }),
  recommendReply: (id, body = {}) =>
    request(`/api/inquiries/${encodeURIComponent(id)}/recommend-reply`, {
      method: 'POST',
      body: JSON.stringify(body || {}),
    }),
  submitApproval: (id, final_text) =>
    request(`/api/inquiries/${id}/submit-approval`, {
      method: 'POST',
      body: JSON.stringify({ approve: true, final_text }),
    }),
  approvals: (status = 'pending') => request(`/api/approvals?status=${encodeURIComponent(status)}`),
  decideApproval: (id, approve, final_text) =>
    request(`/api/approvals/${id}/decide`, {
      method: 'POST',
      body: JSON.stringify({ approve, final_text }),
    }),
  customers: () => request('/api/customers'),
  customersPool: () => request('/api/customers/pool'),
  claimCustomer: (id) => request(`/api/customers/${encodeURIComponent(id)}/claim`, { method: 'POST', body: '{}' }),
  releaseCustomer: (id) => request(`/api/customers/${encodeURIComponent(id)}/release`, { method: 'POST', body: '{}' }),
  transferCustomer: (id, to_employee) =>
    request(`/api/customers/${encodeURIComponent(id)}/transfer`, {
      method: 'POST',
      body: JSON.stringify({ to_employee }),
    }),
  touchCustomer: (id) => request(`/api/customers/${encodeURIComponent(id)}/touch`, { method: 'POST', body: '{}' }),
  recycleCustomers: (days) =>
    request('/api/customers/recycle', { method: 'POST', body: JSON.stringify({ days: days || null }) }),
  saveCustomer: (body) => request('/api/customers', { method: 'POST', body: JSON.stringify(body) }),
  deleteCustomer: (id) => request(`/api/customers/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  customerRelated: (id) => request(`/api/customers/${encodeURIComponent(id)}/related`),
  followups: () => request('/api/followups'),
  saveFollowup: (body) => request('/api/followups', { method: 'POST', body: JSON.stringify(body) }),
  deleteFollowup: (id) => request(`/api/followups/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  completeFollowup: (id) => request(`/api/followups/${id}/done`, { method: 'POST', body: '{}' }),
  quotations: (params = {}) => {
    const q = new URLSearchParams()
    if (params.inquiry_id) q.set('inquiry_id', params.inquiry_id)
    if (params.status) q.set('status', params.status)
    const s = q.toString()
    return request(s ? `/api/quotations?${s}` : '/api/quotations')
  },
  saveQuotation: (body) => request('/api/quotations', { method: 'POST', body: JSON.stringify(body) }),
  setQuotationStatus: (id, status) =>
    request(`/api/quotations/${encodeURIComponent(id)}/status`, {
      method: 'POST',
      body: JSON.stringify({ status }),
    }),
  deleteQuotation: (id) => request(`/api/quotations/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  quotationVersions: (id) => request(`/api/quotations/${encodeURIComponent(id)}/versions`),
  quotationNewVersion: (id, body = {}) =>
    request(`/api/quotations/${encodeURIComponent(id)}/new-version`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  quotationApproveBelowFloor: (id) =>
    request(`/api/quotations/${encodeURIComponent(id)}/approve-below-floor`, { method: 'POST', body: '{}' }),
  quotationLost: (id, reason) =>
    request(`/api/quotations/${encodeURIComponent(id)}/lost`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    }),
  collections: () => request('/api/collections'),
  tracking: () => request('/api/tracking'),
  recordPayment: (orderId, body) =>
    request(`/api/orders/${encodeURIComponent(orderId)}/record-payment`, {
      method: 'POST',
      body: JSON.stringify(body || {}),
    }),
  advanceMilestone: (orderId, body) =>
    request(`/api/orders/${encodeURIComponent(orderId)}/milestones/advance`, {
      method: 'POST',
      body: JSON.stringify(body || {}),
    }),
  updateOrderMeta: (orderId, body) =>
    request(`/api/orders/${encodeURIComponent(orderId)}/meta`, {
      method: 'POST',
      body: JSON.stringify(body || {}),
    }),
  quotationFromInquiry: (inquiryId, vendorIndex = 0) =>
    request(`/api/quotations/from-inquiry/${encodeURIComponent(inquiryId)}?vendor_index=${vendorIndex}`, {
      method: 'POST',
      body: '{}',
    }),
  orders: (status) => request(status ? `/api/orders?status=${encodeURIComponent(status)}` : '/api/orders'),
  saveOrder: (body) => request('/api/orders', { method: 'POST', body: JSON.stringify(body) }),
  deleteOrder: (id) => request(`/api/orders/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  orderFromQuotation: (id) =>
    request(`/api/orders/from-quotation/${encodeURIComponent(id)}`, { method: 'POST', body: '{}' }),
  orderFromSample: (id) =>
    request(`/api/orders/from-sample/${encodeURIComponent(id)}`, { method: 'POST', body: '{}' }),
  templates: () => request('/api/templates'),
  audit: () => request('/api/audit'),
  knowledgeDocs: () => request('/api/knowledge/docs'),
  knowledgeSearch: (query, top_k = 4) =>
    request('/api/knowledge/search', { method: 'POST', body: JSON.stringify({ query, top_k }) }),
  rebuildKb: () => request('/api/knowledge/rebuild', { method: 'POST', body: '{}' }),
  products: () => request('/api/products'),
  vendors: (activeOnly = false) =>
    request(activeOnly ? '/api/vendors?active_only=true' : '/api/vendors'),
  saveVendor: (body) => request('/api/vendors', { method: 'POST', body: JSON.stringify(body) }),
  deleteVendor: (id) => request(`/api/vendors/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  vendorRelated: (id) => request(`/api/vendors/${encodeURIComponent(id)}/related`),
  chatAsk: (question, extra = {}) =>
    request('/api/chat/ask', { method: 'POST', body: JSON.stringify({ question, ...extra }) }),
  chatStatus: () => request('/api/chat/status'),
}
