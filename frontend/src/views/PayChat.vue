<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showToast } from 'vant'
import { get, post } from '@/api'
import TopBar from '@/components/TopBar.vue'
import Sheet from '@/components/Sheet.vue'
import { yuan } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const cid = computed(() => route.params.cid)
const chat = ref(null)
const coupons = ref([])
const coupon = ref(null)
const disc = ref(0)
const method = ref('微信支付')
const showCoupon = ref(false)

const modeName = computed(() => ({ text: '图文问诊', voice: '语音问诊', video: '视频问诊' }[chat.value?.mode] || '图文问诊'))
const payable = computed(() => Math.max(0, Number(chat.value?.fee || 0) - disc.value))

const methods = [
  { key: '微信支付', label: '💚 微信支付' },
  { key: '支付宝', label: '💙 支付宝' },
  { key: '余额支付', label: '💰 余额支付' }
]

const load = async () => {
  const j = await get('/chat/' + cid.value)
  if (!j.ok) return
  chat.value = j.chat
  const cu = await get('/coupons/usable', { amount: j.chat.fee, kind: '问诊' })
  coupons.value = cu.coupons || []
}

onMounted(load)
// 同路由切换问诊单时组件实例复用，需重新拉取待支付信息
watch(cid, (v) => { if (v) { chat.value = null; coupons.value = []; load() } })

const setCoupon = (c) => {
  coupon.value = c ? c.id : null
  disc.value = c ? Number(c.amount) : 0
  showCoupon.value = false
}

const pay = async () => {
  const j = await post('/chat/' + cid.value + '/pay', { pay: method.value, coupon_id: coupon.value || 0 })
  if (j.ok) {
    showToast(j.msg || '支付成功')
    router.replace('/chat/' + cid.value)
  }
}
</script>

<template>
  <div>
    <TopBar title="确认支付" />
    <div v-if="!chat" class="loading">加载中…</div>
    <div v-else class="page" style="padding-bottom: 90px">
      <div v-if="chat.status !== '待支付'" class="warn">该问诊单当前状态为「{{ chat.status }}」，无需重复支付。</div>

      <div class="card">
        <div class="hd">
          <div class="avatar">{{ chat.icon }}</div>
          <div class="bd">
            <div class="b">{{ chat.doc }} {{ chat.title }}</div>
            <div class="muted">{{ chat.dept }} · {{ modeName }}</div>
          </div>
        </div>
        <div class="split"></div>
        <div class="kv"><span>症状描述</span><span style="max-width: 62%; text-align: right">{{ chat.symptom }}</span></div>
        <div class="kv"><span>问诊服务</span><b>{{ modeName }}</b></div>
      </div>

      <div class="card">
        <div class="between" style="padding: 4px 0" @click="showCoupon = true">
          <span>优惠券</span>
          <span style="color: #ff5a3c">
            {{ coupon ? '已选 ¥' + disc + ' 券 ›' : coupons.length ? coupons.length + ' 张可用 ›' : '暂无可用 ›' }}
          </span>
        </div>
        <div class="split"></div>
        <div class="kv"><span>服务费</span><span>{{ yuan(chat.fee) }}</span></div>
        <div class="kv"><span>优惠抵扣</span><span style="color: #ff5a3c">-{{ yuan(disc) }}</span></div>
        <div class="kv"><span>应付金额</span><span class="price" style="font-size: 17px">{{ yuan(payable) }}</span></div>
      </div>

      <div class="card">
        <div class="b" style="margin-bottom: 8px">支付方式</div>
        <div v-for="m in methods" :key="m.key" class="opt" :class="{ on: method === m.key }" @click="method = m.key">
          <div class="between">
            <span>{{ m.label }}</span>
            <span class="muted">模拟支付</span>
          </div>
        </div>
      </div>

      <div class="bottom-bar">
        <div>
          <div class="muted">应付</div>
          <div class="price" style="font-size: 18px">{{ yuan(payable) }}</div>
        </div>
        <button class="btn" @click="pay">立即支付</button>
      </div>

      <Sheet v-model="showCoupon" title="选择优惠券">
        <div v-for="c in coupons" :key="c.id" class="coupon" @click="setCoupon(c)">
          <div class="l"><b>¥{{ c.amount }}</b><span>满{{ c.threshold }}可用</span></div>
          <div class="r">
            <div class="b">{{ c.name }}</div>
            <div class="muted">限「{{ c.scope }}」，{{ c.expire }} 到期</div>
          </div>
        </div>
        <div v-if="!coupons.length" class="empty">暂无可用优惠券</div>
        <button class="btn btn-line" @click="setCoupon(null)">不使用优惠券</button>
      </Sheet>
    </div>
  </div>
</template>
