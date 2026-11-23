<script setup>
import { useRouter } from 'vue-router'
const props = defineProps({ current: { type: String, default: '' } })
const router = useRouter()
const tabs = [
  { key: 'home', name: '首页', icon: '🏠', path: '/home' },
  { key: 'ask', name: '问诊', icon: '🩺', path: '/ask' },
  { key: 'shop', name: '商城', icon: '🛒', path: '/shop' },
  { key: 'msgs', name: '消息', icon: '💬', path: '/msgs' },
  { key: 'me', name: '我的', icon: '👤', path: '/me' }
]
const go = (t) => {
  if (t.key !== props.current) router.push(t.path)
}
</script>

<template>
  <div class="tabbar">
    <div v-for="t in tabs" :key="t.key" class="tb" :class="{ on: current === t.key }" @click="go(t)">
      <span class="em">{{ t.icon }}</span>{{ t.name }}
    </div>
  </div>
</template>
