<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showConfirmDialog, showToast } from 'vant'
import { get, post, del } from '@/api'
import { yuan } from '@/utils/format'
import TopBar from '@/components/TopBar.vue'
import Sheet from '@/components/Sheet.vue'

const PAYS = ['💚 微信支付', '💙 支付宝', '💰 余额支付']
const route = useRoute()
const router = useRouter()
const oid = computed(() => route.params.id)

const order = ref(null)
const loading = ref(true)
const err = ref('')
const paying = ref(false)

// 详情页必须同时响应「首次挂载」和「同路由参数切换」，否则组件复用会串单
const load = async () => {
  if (!oid.value) return
  loading.value = true
  err.value = ''
  try {
    const j = await get('/order/' + oid.value)
    if (j.ok) order.value = j.order
    else err.value = j.msg || '订单不存在'
  } catch (e) {
    err.value = '订单不存在或已删除'
  }
  loading.value = false
}
watch(oid, (v, old) => {
  if (v && v !== old) {
    order.value = null
    load()
  }
})
onMounted(load)

const timeline = computed(() => (order.value?.timeline || []).slice().reverse())
const goods = computed(() => {
  const o = order.value
  if (!o) return 0
  return Math.round((Number(o.amount) + Number(o.discount || 0) - Number(o.ship_fee || 0)) * 100) / 100
})

const copy = async (t) => {
  try {
    await navigator.clipboard.writeText(String(t))
    showToast('已复制：' + t)
  } catch (e) {
    showToast(String(t))
  }
}

const goProduct = (i) => {
  if (i.med_id) router.push('/product/' + i.med_id)
}

const after = (j) => {
  if (j && j.ok) {
    showToast(j.msg || '操作成功')
    load()
  }
}

const pay = async (method) => {
  const j = await post('/order/' + order.value.id + '/pay', { pay: method })
  paying.value = false
  after(j)
}

const cancel = async () => {
  try {
    await showConfirmDialog({ title: '取消订单', message: '取消后优惠券与库存将退回，确认取消？' })
  } catch (e) {
    return
  }
  after(await post('/order/' + order.value.id + '/cancel'))
}

const act = async (action, tip, title = '提示') => {
  try {
    await showConfirmDialog({ title, message: tip })
  } catch (e) {
    return
  }
  after(await post('/order/' + order.value.id + '/' + action))
}

const remove = async () => {
  try {
    await showConfirmDialog({
      title: '删除订单',
      message: '删除后该订单将从订单列表中移除且不可恢复，确定删除？',
      confirmButtonText: '删除'
    })
  } catch (e) {
    return
  }
  const j = await del('/order/' + order.value.id)
  if (j.ok) {
    showToast(j.msg || '订单已删除')
    router.back()
  }
}

// ---------- 商品评价（仅已完成订单可评，一单一商品限一次） ----------
const reviewing = ref(false)
const rvTarget = ref(null)
const rvRating = ref(5)
const rvText = ref('')
const rvAnon = ref(false)

const openReview = (i) => {
  rvTarget.value = i
  rvRating.value = 5
  rvText.value = ''
  rvAnon.value = false
  reviewing.value = true
}

const submitReview = async () => {
  const j = await post('/order/' + order.value.id + '/review', {
    med_id: rvTarget.value.med_id,
    rating: rvRating.value,
    content: rvText.value,
    anon: rvAnon.value ? 1 : 0
  })
  if (j && j.ok) {
    reviewing.value = false
    showToast(j.msg || '评价成功')
    load()
  } else {
    showToast((j && j.msg) || '评价失败，请稍后再试')
  }
}

const isGoods = computed(() => (order.value?.kind || '商品') === '商品')
const canDel = computed(() => ['已取消', '已关闭', '已退款', '已完成'].includes(order.value?.status))
</script>

<template>
  <div>
    <TopBar title="订单详情" />
    <div class="page" style="padding-bottom: 84px">
      <div v-if="loading" class="loading">加载中…</div>
      <div v-else-if="err" class="empty">{{ err }}</div>
      <template v-else-if="order">
        <div class="card hero">
          <div class="st">{{ order.status_text }}</div>
          <div class="tip">{{ order.status_tip }}</div>
        </div>

        <div class="card" v-if="timeline.length > 1">
          <div class="between" style="margin-bottom: 12px">
            <span class="b">物流轨迹</span>
            <span v-if="order.express_no" class="muted" @click="copy(order.express_no)">
              顺丰速运 {{ order.express_no }} · 复制
            </span>
          </div>
          <div class="tl">
            <div v-for="(n, i) in timeline" :key="n.title + i" class="n" :class="n.state">
              <div class="t">{{ n.title }}</div>
              <div class="d">{{ n.desc }}</div>
              <div class="m" v-if="n.time">{{ n.time }}</div>
            </div>
          </div>
        </div>

        <div class="card" v-if="order.addr_info">
          <div class="b" style="margin-bottom: 8px">收货信息</div>
          <div class="row" style="gap: 8px">
            <div class="em">📍</div>
            <div class="bd">
              <div class="tt">{{ order.addr_info.name }} {{ order.addr_info.phone }}</div>
              <div class="ds">{{ order.addr_info.region }}{{ order.addr_info.detail }}</div>
            </div>
          </div>
        </div>

        <div class="card">
          <div class="between" style="margin-bottom: 8px">
            <span class="b">商品清单</span>
            <span class="muted">共 {{ order.items.length }} 件</span>
          </div>
          <div v-for="(i, k) in order.items" :key="k" class="item" @click="goProduct(i)">
            <div class="em">{{ i.icon }}</div>
            <div class="bd">
              <div class="tt">{{ i.name }} × {{ i.qty }}</div>
              <div class="ds">{{ i.spec }}<span v-if="i.rx"> · 处方药</span></div>
            </div>
            <div style="display: flex; flex-direction: column; align-items: flex-end; gap: 6px">
              <div class="price">{{ yuan(i.amount) }}</div>
              <button
                v-if="order.status === '已完成'"
                class="btn btn-sm"
                :class="i.reviewed ? 'btn-gray' : 'btn-line'"
                :disabled="i.reviewed"
                @click.stop="openReview(i)"
              >
                {{ i.reviewed ? '已评价' : '评价' }}
              </button>
            </div>
          </div>
          <div class="split"></div>
          <div class="kv"><span>商品合计</span><span>{{ yuan(goods) }}</span></div>
          <div class="kv" v-if="order.discount">
            <span>优惠券{{ order.coupon_name ? '（' + order.coupon_name + '）' : '' }}</span>
            <span style="color: #ff5a3c">-{{ yuan(order.discount) }}</span>
          </div>
          <div class="kv">
            <span>运费</span>
            <span>{{ order.ship_fee ? yuan(order.ship_fee) : '免运费' }}</span>
          </div>
          <div class="kv">
            <span>实付金额</span>
            <span class="price" style="font-size: 17px">{{ yuan(order.amount) }}</span>
          </div>
        </div>

        <div class="card">
          <div class="b" style="margin-bottom: 6px">订单信息</div>
          <div class="kv">
            <span>订单编号</span>
            <span>{{ order.order_no }} <span class="muted" @click="copy(order.order_no)">复制</span></span>
          </div>
          <div class="kv"><span>下单时间</span><span>{{ order.created }}</span></div>
          <div class="kv" v-if="order.pay_time"><span>支付方式</span><span>{{ order.pay }}</span></div>
          <div class="kv" v-if="order.pay_time"><span>支付时间</span><span>{{ order.pay_time }}</span></div>
          <div class="kv" v-if="order.note"><span>订单备注</span><span>{{ order.note }}</span></div>
        </div>

        <div class="bottom-bar">
          <div style="flex: 1">
            <div class="muted">实付</div>
            <div class="price" style="font-size: 18px">{{ yuan(order.amount) }}</div>
          </div>
          <template v-if="order.status === '待支付'">
            <button class="btn btn-sm btn-gray" @click="cancel">取消订单</button>
            <button class="btn btn-sm" @click="paying = true">去支付</button>
          </template>
          <template v-else-if="order.status === '待发货'">
            <button class="btn btn-sm btn-line" @click="act('ship', '模拟商家发货，确认继续？', '提醒发货')">
              提醒发货
            </button>
            <button class="btn btn-sm btn-red" @click="act('refund', '确认申请退款？将模拟原路退回。')">
              申请退款
            </button>
          </template>
          <template v-else-if="order.status === '已发货'">
            <button class="btn btn-sm btn-red" @click="act('refund', '确认申请退款？将模拟原路退回。')">
              申请退款
            </button>
            <button class="btn btn-sm" @click="act('finish', '确认已收到商品？', '确认收货')">确认收货</button>
          </template>
          <template v-else-if="order.status === '已完成'">
            <button class="btn btn-sm btn-line" @click="remove">删除订单</button>
            <button class="btn btn-sm" @click="router.push('/shop')">再次购买</button>
          </template>
          <template v-else>
            <button class="btn btn-sm btn-gray" v-if="canDel" @click="remove">删除订单</button>
            <button class="btn btn-sm" @click="router.push('/shop')">去逛逛</button>
          </template>
        </div>

        <Sheet v-model="reviewing" title="评价商品">
          <div class="muted" style="margin-bottom: 10px">{{ rvTarget && rvTarget.name }}</div>
          <div class="stars">
            <span
              v-for="n in 5"
              :key="n"
              class="st"
              :class="{ on: n <= rvRating }"
              @click="rvRating = n"
            >★</span>
            <span class="muted" style="margin-left: 8px">{{ ['很差', '较差', '一般', '满意', '非常满意'][rvRating - 1] }}</span>
          </div>
          <textarea
            v-model="rvText"
            class="rv-box"
            maxlength="200"
            placeholder="说说商品效果、包装、物流等体验，帮助其他人做选择（选填）"
          ></textarea>
          <div class="between" style="padding: 8px 2px">
            <span class="muted">匿名评价</span>
            <span class="anon" :class="{ on: rvAnon }" @click="rvAnon = !rvAnon"><i></i></span>
          </div>
          <button class="btn" style="width: 100%" @click="submitReview">提交评价</button>
        </Sheet>

        <Sheet v-model="paying" title="选择支付方式">
          <div v-for="m in PAYS" :key="m" class="opt" @click="pay(m)">
            <div class="between">
              <span>{{ m }}</span>
              <span class="muted">模拟支付</span>
            </div>
          </div>
          <div class="between" style="padding: 6px 2px">
            <span class="muted">应付</span>
            <span class="price" style="font-size: 18px">{{ yuan(order.amount) }}</span>
          </div>
        </Sheet>
      </template>
    </div>
  </div>
</template>

<style scoped>
.hero {
  background: linear-gradient(135deg, #0f766e, #10b981);
  color: #fff;
}
.hero .st {
  font-size: 19px;
  font-weight: 600;
}
.hero .tip {
  font-size: 12px;
  opacity: 0.88;
  margin-top: 6px;
  line-height: 1.5;
}
.tl {
  position: relative;
  padding-left: 18px;
}
.tl .n {
  position: relative;
  padding-bottom: 14px;
}
.tl .n:last-child {
  padding-bottom: 0;
}
.tl .n::before {
  content: '';
  position: absolute;
  left: -15px;
  top: 4px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #d1d5db;
}
.tl .n:not(:last-child)::after {
  content: '';
  position: absolute;
  left: -11.5px;
  top: 14px;
  bottom: 0;
  width: 1px;
  background: #e5e7eb;
}
.tl .n.done::before,
.tl .n.doing::before {
  background: #10b981;
}
.tl .n.doing::before {
  box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.18);
}
.tl .t {
  font-size: 13px;
  color: #111827;
}
.tl .n.doing .t {
  color: #0f766e;
  font-weight: 600;
}
.tl .d {
  font-size: 12px;
  color: #6b7280;
  margin-top: 2px;
}
.tl .m {
  font-size: 11px;
  color: #9ca3af;
  margin-top: 2px;
}
.stars {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-bottom: 10px;
}
.stars .st {
  font-size: 24px;
  color: #e5e7eb;
  cursor: pointer;
  line-height: 1;
}
.stars .st.on {
  color: #f59e0b;
}
.anon {
  width: 42px;
  height: 24px;
  border-radius: 12px;
  background: #e5e7eb;
  position: relative;
  display: inline-block;
  transition: background 0.2s;
  cursor: pointer;
}
.anon i {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.15);
  transition: left 0.2s;
}
.anon.on {
  background: #10b981;
}
.anon.on i {
  left: 20px;
}
.rv-box {
  width: 100%;
  box-sizing: border-box;
  min-height: 84px;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  padding: 10px;
  font-size: 13px;
  line-height: 1.6;
  resize: none;
  outline: none;
  font-family: inherit;
}
</style>
