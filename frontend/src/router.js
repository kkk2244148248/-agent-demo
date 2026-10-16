import { createRouter, createWebHistory } from 'vue-router'
import { getToken } from './api'
import Dashboard from './views/Dashboard.vue'
import Inbox from './views/Inbox.vue'
import InquiryDetail from './views/InquiryDetail.vue'
import Approvals from './views/Approvals.vue'
import Customers from './views/Customers.vue'
import CustomerPool from './views/CustomerPool.vue'
import Tracking from './views/Tracking.vue'
import Collections from './views/Collections.vue'
import Followups from './views/Followups.vue'
import Knowledge from './views/Knowledge.vue'
import Products from './views/Products.vue'
import Quotations from './views/Quotations.vue'
import Orders from './views/Orders.vue'
import Audit from './views/Audit.vue'
import Agents from './views/Agents.vue'
import Assistant from './views/Assistant.vue'
import Samples from './views/Samples.vue'
import Login from './views/Login.vue'
import Users from './views/Users.vue'

const routes = [
  { path: '/login', name: 'login', component: Login, meta: { public: true } },
  { path: '/', name: 'dashboard', component: Dashboard },
  { path: '/assistant', name: 'assistant', component: Assistant },
  { path: '/agents', name: 'agents', component: Agents },
  { path: '/inbox', name: 'inbox', component: Inbox },
  { path: '/inbox/:id', name: 'inquiry', component: InquiryDetail },
  { path: '/approvals', name: 'approvals', component: Approvals },
  { path: '/followups', name: 'followups', component: Followups },
  { path: '/samples', name: 'samples', component: Samples },
  { path: '/quotations', name: 'quotations', component: Quotations },
  { path: '/orders', name: 'orders', component: Orders },
  { path: '/customers', name: 'customers', component: Customers },
  { path: '/customers/pool', name: 'customer-pool', component: CustomerPool },
  { path: '/tracking', name: 'tracking', component: Tracking },
  { path: '/collections', name: 'collections', component: Collections },
  { path: '/vendors', name: 'vendors', component: Products },
  { path: '/products', redirect: '/vendors' },
  { path: '/knowledge', name: 'knowledge', component: Knowledge },
  { path: '/audit', name: 'audit', component: Audit },
  { path: '/users', name: 'users', component: Users },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to) => {
  if (to.meta.public) return true
  if (!getToken()) return { path: '/login', query: { redirect: to.fullPath } }
  return true
})

export default router
