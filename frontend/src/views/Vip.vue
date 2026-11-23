<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { showToast } from 'vant'
import { get, post } from '@/api'
import { useUserStore } from '@/stores/user'
import { yuan } from '@/utils/format'
import TopBar from '@/components/TopBar.vue'

const router = useRouter()
const store = useUserStore()
const vip = ref(null)
const loading = ref(true)

const load = async () => {
  const j = await get('/vip')
  vip.value = j
  loading.value = false
}

const buy = async (m) => {
  const j = await post('/vip/buy', { months: m.months })
  if (j.ok) {
    showToast(j.msg)
    store.fetchMe()
    load()
  }
}

onMounted(load)
</script>

<template>
  <div>
    <TopBar title="会员中心" />
    <div v-if="loading" class="loading">加载中…</div>
    <div v-else class="page" style="padding-bottom: 130px">
      <div class="vip-card">
        <div class="between">
          <div>
            <h3 style="margin: 0">
              {{ vip.vip ? '👑 会员有效期至 ' + (vip.vip_until || '').slice(0, 10) : '💎 开通百灵会员' }}
            </h3>
            <p style="margin: 6px 0 0; color: rgba(255, 255, 255, 0.92)">
              {{ vip.vip ? '每月 3 次图文问诊免费 · 图文/视频问诊 9 折 · 商城包邮' : '每月 3 次图文问诊免费 · 图文/视频问诊 9 折 · 商城包邮' }}
            </p>
          </div>
          <span class="emoji" style="font-size: 34px">👑</span>
        </div>
      </div>

      <div class="card">
        <div class="b" style="margin-bottom: 6px">会员权益</div>
        <div v-for="b in vip.benefits" :key="b.name" class="item">
          <div class="em">{{ b.icon }}</div>
          <div class="bd">
            <div class="tt">{{ b.name }}</div>
            <div class="muted">{{ b.desc }}</div>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="b" style="margin-bottom: 6px">开通方案</div>
        <div v-for="p in vip.plans" :key="p.months" class="between plan">
          <div>
            <div class="b">{{ p.name }}</div>
            <div class="muted">{{ p.note }}</div>
          </div>
          <div style="text-align: right">
            <div class="price" style="font-size: 16px">{{ yuan(p.price) }}</div>
            <button v-if="!vip.vip || p.months > 0" class="btn btn-sm btn-line" @click="buy(p)">立即开通</button>
            <button v-else class="btn btn-sm btn-gray" disabled>已是会员</button>
          </div>
        </div>
      </div>

      <div class="muted" style="text-align: center; padding: 8px 0">
        会员服务由百灵医生提供 · 模拟支付立即到账
      </div>
    </div>
  </div>
</template>

<style scoped>
.plan {
  padding: 10px 0;
  border-bottom: 1px solid var(--line);
}
.plan:last-child {
  border-bottom: none;
}
</style>
