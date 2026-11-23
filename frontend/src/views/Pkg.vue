<script setup>
import { ref, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { get } from '@/api'
import { yuan } from '@/utils/format'
import TopBar from '@/components/TopBar.vue'

const route = useRoute()
const router = useRouter()
const pkg = ref(null)
const loading = ref(true)

const load = async () => {
  const j = await get('/pkgs/' + route.params.id)
  pkg.value = j && j.ok ? j.pkg : null
  loading.value = false
}

onMounted(load)
// 同路由不同套餐会复用组件实例，onMounted 不再触发，需监听参数变化重新拉取
watch(() => route.params.id, (v) => { if (v) load() })

const buy = () => {
  sessionStorage.setItem('svc', JSON.stringify({ id: pkg.value.id, name: pkg.value.name, price: pkg.value.price }))
  router.push('/confirm')
}
</script>

<template>
  <div>
    <TopBar title="服务详情" />
    <div v-if="loading" class="loading">加载中…</div>
    <div v-else-if="!pkg" class="empty">服务不存在</div>
    <div v-else class="page" style="padding-bottom: 96px">
      <div class="card">
        <div style="display: flex; gap: 12px; align-items: center">
          <div class="em" style="font-size: 40px">{{ pkg.icon }}</div>
          <div>
            <div class="b" style="font-size: 16px">{{ pkg.name }}</div>
            <div class="muted">{{ pkg.sub }}</div>
            <div class="price" style="font-size: 20px; margin-top: 4px">{{ yuan(pkg.price) }}</div>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="b" style="margin-bottom: 6px">服务包含</div>
        <div class="muted" style="line-height: 1.9; white-space: pre-wrap">{{ pkg.intro }}</div>
      </div>

      <div class="card">
        <div class="b" style="margin-bottom: 6px">服务周期与说明</div>
        <div class="kv"><span>服务周期</span><span>{{ pkg.days }} 天</span></div>
        <div class="muted" style="line-height: 1.8; margin-top: 6px; white-space: pre-wrap">{{ pkg.tips }}</div>
      </div>

      <div class="bottom-bar">
        <div>
          <div class="muted">服务费</div>
          <div class="price" style="font-size: 18px">{{ yuan(pkg.price) }}</div>
        </div>
        <button class="btn" @click="buy">立即购买</button>
      </div>
    </div>
  </div>
</template>
