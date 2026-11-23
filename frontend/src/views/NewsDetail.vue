<script setup>
import { ref, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { get } from '@/api'
import TopBar from '@/components/TopBar.vue'

const route = useRoute()
const router = useRouter()
const news = ref(null)
const fail = ref(false)

const load = async () => {
  const j = await get('/news/' + route.params.id)
  if (!j.ok) { fail.value = true; news.value = null } else { fail.value = false; news.value = j.news }
}

onMounted(load)
// 同路由不同文章复用组件实例，需监听参数变化重新拉取
watch(() => route.params.id, (v) => { if (v) load() })
</script>

<template>
  <div>
    <TopBar title="资讯" />
    <div v-if="fail" class="empty">文章不存在</div>
    <div v-else-if="!news" class="loading">加载中…</div>
    <div v-else class="page">
      <div class="card">
        <div style="font-size: 19px; font-weight: 700; line-height: 1.5">{{ news.title }}</div>
        <div class="muted" style="margin: 6px 0 12px">{{ news.cat }} · {{ (news.created || '').slice(0, 16) }}</div>
        <div style="line-height: 2; color: #374151; font-size: 14px; white-space: pre-wrap">{{ news.body }}</div>
      </div>
      <button class="btn" @click="router.push('/ask')">有问题？在线问医生</button>
    </div>
  </div>
</template>
