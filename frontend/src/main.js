import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './styles/app.css'
// Vant 按需引入（仅使用 Toast / Dialog 函数式组件 + 消息页左滑删除 SwipeCell）
import 'vant/es/toast/style'
import 'vant/es/dialog/style'
import 'vant/es/swipe-cell/style'

createApp(App).use(createPinia()).use(router).mount('#app')
