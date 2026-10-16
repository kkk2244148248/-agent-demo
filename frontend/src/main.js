import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import './styles.css'

const app = createApp(App)
app.config.errorHandler = (err, _instance, info) => {
  console.error('vue error', info, err)
}
app.use(router).mount('#app')

window.addEventListener('trade-desk:unauthorized', () => {
  if (!window.location.pathname.includes('/login')) {
    router.replace({ path: '/login', query: { redirect: window.location.pathname } })
  }
})
