<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { get } from '@/api'
import { yuan } from '@/utils/format'
import TopBar from '@/components/TopBar.vue'

const router = useRouter()
const pkgs = ref([])
const loading = ref(true)

onMounted(async () => {
  const j = await get('/pkgs')
  pkgs.value = j.pkgs || []
  loading.value = false
})
</script>

<template>
  <div>
    <TopBar title="特色门诊" />
    <div v-if="loading" class="loading">加载中…</div>
    <div v-else class="page">
      <div v-for="p in pkgs" :key="p.id" class="card" @click="router.push('/pkg/' + p.id)">
        <div style="display: flex; gap: 12px">
          <div class="em" style="font-size: 34px">{{ p.icon }}</div>
          <div style="flex: 1">
            <div class="b" style="font-size: 15px">{{ p.name }}</div>
            <div class="muted">{{ p.sub }}</div>
            <div class="between" style="margin-top: 6px">
              <span class="price">{{ yuan(p.price) }}</span>
              <span class="muted">{{ p.days }} 天服务 ›</span>
            </div>
          </div>
        </div>
      </div>
      <div v-if="!pkgs.length" class="empty">暂无服务套餐</div>
    </div>
  </div>
</template>
