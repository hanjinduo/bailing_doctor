<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showConfirmDialog, showToast } from 'vant'
import { get, post, del } from '@/api'
import { yuan } from '@/utils/format'
import TopBar from '@/components/TopBar.vue'
import Sheet from '@/components/Sheet.vue'

const PAYS = ['💚 微信支付', '💙 支付宝', '💰 余额支付']
const route = useRoute()
const router = useRouter()
const tabs = ['全部', '待支付', '待发货', '已发货', '已完成', '已退款']
const tab = ref(route.query.status || '全部')
const orders = ref([])
const loading = ref(false)
const paying = ref(null)
const PAGE = 20
const hasMore = ref(false)
const loadingMore = ref(false)

const color = (s) => (s === '待支付' ? 'r' : s === '待发货' ? 'w' : s === '已完成' ? 'g' : '')

// 仅业务终态订单可删（与后端 ORDER_DELETABLE 保持一致）
const DEL_STATES = ['已取消', '已关闭', '已退款', '已完成']
const canDel = (s) => DEL_STATES.includes(s)

const remove = async (o) => {
  try {
    await showConfirmDialog({
      title: '删除订单',
      message: '删除后该订单将从订单列表中移除且不可恢复，确定删除？',
      confirmButtonText: '删除'
    })
  } catch (e) {
    return // 用户取消
  }
  try {
    const j = await del('/order/' + o.id)
    if (j.ok) {
      showToast(j.msg || '订单已删除')
      orders.value = orders.value.filter((x) => x.id !== o.id)
    }
  } catch (e) {
    /* 失败提示已由 axios 拦截器按后端 msg 弹出 */
  }
}

const params = (offset) => {
  const p = { limit: PAGE, offset }
  if (tab.value !== '全部') p.status = tab.value
  return p
}

const load = async () => {
  loading.value = true
  const j = await get('/orders', params(0))
  orders.value = j.orders || []
  hasMore.value = !!j.has_more
  loading.value = false
}

const loadMore = async () => {
  if (loadingMore.value || !hasMore.value) return
  loadingMore.value = true
  const j = await get('/orders', params(orders.value.length))
  orders.value = orders.value.concat(j.orders || [])
  hasMore.value = !!j.has_more
  loadingMore.value = false
}

const switchTab = (t) => {
  tab.value = t
  router.replace({ path: '/orders', query: t === '全部' ? {} : { status: t } })
  load()
}

const pay = async (o, method) => {
  const j = await post('/order/' + o.id + '/pay', { pay: method })
  paying.value = null
  if (j.ok) {
    showToast(j.msg)
    load()
  }
}

const cancel = async (o) => {
  await showConfirmDialog({ title: '取消订单', message: '确认取消该订单？优惠券将退回。' })
  const j = await post('/order/' + o.id + '/cancel')
  if (j.ok) {
    showToast(j.msg)
    load()
  }
}

const act = async (o, action, tip) => {
  await showConfirmDialog({ title: '提示', message: tip })
  const j = await post('/order/' + o.id + '/' + action)
  if (j.ok) {
    showToast(j.msg)
    load()
  }
}

onMounted(load)
</script>

<template>
  <div>
    <TopBar title="商城订单" right="去逛逛" @right="router.push('/shop')" />
    <div class="page">
      <div class="seg">
        <div v-for="t in tabs" :key="t" :class="{ on: tab === t }" @click="switchTab(t)">{{ t }}</div>
      </div>

      <div v-if="loading" class="loading">加载中…</div>
      <template v-else>
        <div v-for="o in orders" :key="o.id" class="card">
          <div class="between" @click="router.push('/order/' + o.id)">
            <span class="muted">{{ o.order_no || ('#' + o.id) }} · {{ (o.created || '').slice(0, 16) }}</span>
            <span class="tag" :class="color(o.status)">{{ o.status_text || o.status }}</span>
          </div>
          <div v-for="(i, k) in o.items" :key="k" class="item" @click="router.push('/order/' + o.id)">
            <div class="em">{{ i.icon }}</div>
            <div class="bd">
              <div class="tt">{{ i.name }} × {{ i.qty }}</div>
              <div class="ds">{{ i.spec }}</div>
            </div>
            <div class="price">{{ yuan(i.amount) }}</div>
          </div>
          <div class="muted" style="margin-top: 4px">收货：{{ o.addr || '（虚拟服务，无需地址）' }}</div>
          <div v-if="o.discount" class="muted">
            优惠券：{{ o.coupon_name || '' }} -{{ yuan(o.discount) }} · 运费 {{ yuan(o.ship_fee) }}
          </div>
          <div class="between" style="margin-top: 8px">
            <span @click="router.push('/order/' + o.id)">
              实付 <span class="price" style="font-size: 17px">{{ yuan(o.amount) }}</span>
              <span class="muted" style="margin-left: 4px">详情 ›</span>
            </span>
            <span @click.stop>
              <template v-if="o.status === '待支付'">
                <button class="btn btn-sm btn-gray" @click="cancel(o)">取消订单</button>
                <button class="btn btn-sm" @click="paying = o">去支付</button>
              </template>
              <template v-else-if="o.status === '待发货'">
                <button class="btn btn-sm btn-red" @click="act(o, 'refund', '确认申请退款？将模拟原路退回。')">申请退款</button>
                <button class="btn btn-sm btn-line" @click="act(o, 'ship', '模拟商家发货，确认继续？')">提醒发货</button>
              </template>
              <template v-else-if="o.status === '已发货'">
                <button class="btn btn-sm btn-red" @click="act(o, 'refund', '确认申请退款？将模拟原路退回。')">申请退款</button>
                <button class="btn btn-sm" @click="act(o, 'finish', '确认已收到商品？')">确认收货</button>
              </template>
              <button v-else-if="o.status === '已完成'" class="btn btn-sm btn-line" @click="router.push('/shop')">
                再次购买
              </button>
              <button v-if="canDel(o.status)" class="btn btn-sm btn-gray" @click="remove(o)">删除订单</button>
            </span>
          </div>
        </div>
        <div v-if="!orders.length" class="empty">暂无订单</div>
        <div v-if="orders.length" class="more">
          <button v-if="hasMore" class="btn btn-line" :disabled="loadingMore" @click="loadMore">
            {{ loadingMore ? '加载中…' : '加载更多' }}
          </button>
          <div v-else class="muted">没有更多了</div>
        </div>
      </template>
    </div>

    <Sheet :model-value="!!paying" title="选择支付方式" @update:model-value="paying = null">
      <div v-for="m in PAYS" :key="m" class="opt" @click="pay(paying, m)">
        <div class="between">
          <span>{{ m }}</span>
          <span class="muted">模拟支付</span>
        </div>
      </div>
      <div class="between" style="padding: 6px 2px">
        <span class="muted">应付</span>
        <span class="price" style="font-size: 18px">{{ paying ? yuan(paying.amount) : '' }}</span>
      </div>
    </Sheet>
  </div>
</template>

<style scoped>
.more {
  text-align: center;
  padding: 10px 0;
}
.seg {
  overflow-x: auto;
  scrollbar-width: none;
}
.seg::-webkit-scrollbar {
  display: none;
}
.seg div {
  flex: 0 0 auto;
  min-width: 52px;
  padding: 8px 6px;
  white-space: nowrap;
}
</style>
