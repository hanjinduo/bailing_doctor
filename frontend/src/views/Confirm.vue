<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { showToast } from 'vant'
import { get, post } from '@/api'
import { yuan } from '@/utils/format'
import TopBar from '@/components/TopBar.vue'
import Sheet from '@/components/Sheet.vue'

const router = useRouter()
const PAYS = ['💚 微信支付', '💙 支付宝', '💰 余额支付']

const svc = JSON.parse(sessionStorage.getItem('svc') || 'null')
const pv = ref(null)
const fail = ref('')
const addr = ref(null)
const coupon = ref(null)
const disc = ref(0)
const rxSel = ref(null)
const note = ref('')
const show = ref('')
const paying = ref(null)
const listAddr = ref([])
const loading = ref(true)

const payable = () => {
  if (!pv.value) return 0
  const q = pv.value.quote
  return Math.max(0, q.subtotal + q.ship - disc.value)
}

const preview = async (silent) => {
  const body = { coupon_id: coupon.value || 0 }
  if (svc) body.pkg_id = svc.id
  const j = await post('/order/preview', body)
  loading.value = false
  if (!j.ok) {
    fail.value = j.msg || '无法结算'
    return null
  }
  pv.value = j
  if (!addr.value && (j.addresses || []).length) addr.value = j.addresses[0]
  return j
}

const openAddr = async () => {
  const j = await get('/addresses')
  listAddr.value = j.addresses || []
  show.value = 'addr'
}

const chooseAddr = (a) => {
  addr.value = a
  show.value = ''
}

const openCoupon = async () => {
  await preview(true)
  show.value = 'coupon'
}

const chooseCoupon = (c) => {
  coupon.value = c ? c.id : null
  disc.value = c ? c.amount : 0
  show.value = ''
  preview(false)
}

const openRx = async () => {
  await preview(true)
  show.value = 'rx'
}

const chooseRx = (r) => {
  rxSel.value = r
  show.value = ''
}

const submit = async () => {
  const body = {
    addr_id: addr.value ? addr.value.id : 0,
    coupon_id: coupon.value || 0,
    rx_id: rxSel.value ? rxSel.value.id : 0,
    pkg_id: svc ? svc.id : 0,
    note: note.value || ''
  }
  const j = await post('/order', body)
  if (!j.ok) return
  showToast(j.msg)
  sessionStorage.removeItem('svc')
  paying.value = { id: j.order_id, amount: j.payable }
}

const pay = async (method) => {
  const j = await post('/order/' + paying.value.id + '/pay', { pay: method })
  paying.value = null
  if (j.ok) {
    showToast(j.msg)
    router.replace('/orders')
  }
}

onMounted(() => preview(false))
</script>

<template>
  <div>
    <TopBar title="确认订单" />
    <div v-if="fail" class="empty">{{ fail }}</div>
    <div v-else-if="loading" class="loading">加载中…</div>
    <div v-else class="page" style="padding-bottom: 96px">
      <div class="card">
        <div class="muted" style="margin-bottom: 6px">收货地址</div>
        <div v-if="svc" class="between" @click="openAddr">
          <div>
            <div class="b">虚拟服务，无需收货地址</div>
            <div class="muted">
              {{ addr ? '联系地址：' + addr.region + ' ' + addr.detail : '可选填联系地址 ›' }}
            </div>
          </div>
          <span class="muted">›</span>
        </div>
        <div v-else-if="addr" class="between" @click="openAddr">
          <div>
            <div class="b">{{ addr.name }} {{ addr.phone }}</div>
            <div class="muted">{{ addr.region }} {{ addr.detail }}</div>
          </div>
          <span class="muted">›</span>
        </div>
        <div v-else class="between" @click="openAddr">
          <span style="color: var(--pri)">＋ 填写收货地址</span><span class="muted">›</span>
        </div>
      </div>

      <div class="card">
        <div class="b" style="margin-bottom: 6px">{{ svc ? '服务明细' : '商品明细' }}</div>
        <div v-for="(i, k) in pv.items" :key="k" class="item">
          <div class="em">{{ i.icon }}</div>
          <div class="bd">
            <div class="tt">{{ i.name }} <span v-if="i.rx" class="tag r">处方药</span></div>
            <div class="ds">{{ i.spec }} × {{ i.qty }}</div>
          </div>
          <div class="price">{{ yuan(i.amount) }}</div>
        </div>
      </div>

      <div v-if="pv.has_rx" class="card">
        <div class="between" @click="openRx">
          <span>处方<span class="muted">（含处方药必选）</span></span>
          <span :style="{ color: rxSel ? '' : '#ef4444' }">{{ rxSel ? '已选 ' + rxSel.no + ' ›' : '请选择可用处方 ›' }}</span>
        </div>
      </div>

      <div class="card">
        <div class="between" @click="openCoupon">
          <span>优惠券</span>
          <span style="color: #ff5a3c">
            {{ coupon ? '-' + yuan(disc) : pv.coupons.length ? pv.coupons.length + ' 张可用 ›' : '暂无可用 ›' }}
          </span>
        </div>
        <div class="split"></div>
        <div class="kv"><span>商品小计</span><span>{{ yuan(pv.quote.subtotal) }}</span></div>
        <div class="kv">
          <span>运费{{ pv.quote.ship === 0 ? '（满 ¥' + pv.quote.free_ship_at + ' 包邮 / 会员包邮）' : '' }}</span>
          <span>{{ pv.quote.ship === 0 ? '免运费' : yuan(pv.quote.ship) }}</span>
        </div>
        <div class="kv"><span>优惠抵扣</span><span style="color: #ff5a3c">-{{ yuan(disc) }}</span></div>
        <div class="kv">
          <span>合计</span><span class="price" style="font-size: 17px">{{ yuan(payable()) }}</span>
        </div>
      </div>

      <div class="card">
        <input v-model="note" class="field" placeholder="订单备注（选填）" style="margin: 0" />
      </div>

      <div class="bottom-bar">
        <div>
          <div class="muted">应付</div>
          <div class="price" style="font-size: 18px">{{ yuan(payable()) }}</div>
        </div>
        <button class="btn" @click="submit">提交订单</button>
      </div>
    </div>

    <Sheet v-model="show" :title="show === 'addr' ? '选择收货地址' : show === 'coupon' ? '选择优惠券' : '选择处方'">
      <template v-if="show === 'addr'">
        <div v-for="a in listAddr" :key="a.id" class="opt" :class="{ on: addr && addr.id === a.id }" @click="chooseAddr(a)">
          <div class="b">{{ a.name }} {{ a.phone }} <span v-if="a.is_default" class="tag">默认</span></div>
          <div class="muted">{{ a.region }} {{ a.detail }}</div>
        </div>
        <div v-if="!listAddr.length" class="empty">还没有收货地址</div>
        <button class="btn btn-line" @click="router.push('/address')">管理 / 新增地址</button>
      </template>

      <template v-else-if="show === 'coupon'">
        <div v-for="c in pv.coupons" :key="c.id" class="coupon" @click="chooseCoupon(c)">
          <div class="l"><b>¥{{ c.amount }}</b><span>满{{ c.threshold }}</span></div>
          <div class="r">
            <div class="b">{{ c.name }}</div>
            <div class="muted">{{ c.expire }} 到期 · 限{{ c.scope }}</div>
          </div>
        </div>
        <div v-for="c in pv.coupons_disabled" :key="'d' + c.id" class="coupon dead">
          <div class="l"><b>¥{{ c.amount }}</b><span>满{{ c.threshold }}</span></div>
          <div class="r">
            <div class="b">{{ c.name }}</div>
            <div class="muted">未达使用门槛（差 ¥{{ (c.threshold - pv.quote.subtotal).toFixed(2) }}）</div>
          </div>
        </div>
        <div v-if="!pv.coupons.length && !pv.coupons_disabled.length" class="empty">暂无满足门槛的优惠券</div>
        <button class="btn btn-gray" @click="chooseCoupon(null)">不使用优惠券</button>
      </template>

      <template v-else>
        <div v-for="r in pv.rxs" :key="r.id" class="opt" :class="{ on: rxSel && rxSel.id === r.id }" @click="chooseRx(r)">
          <div class="b">{{ r.diag }}</div>
          <div class="muted">{{ r.no }} · 可使用</div>
        </div>
        <div v-if="!(pv.rxs || []).length" class="empty">
          没有「可使用」状态的处方<br /><br />
          <button class="btn btn-sm btn-line" @click="router.push('/rxs')">去我的处方</button>
        </div>
      </template>
    </Sheet>

    <Sheet :model-value="!!paying" title="选择支付方式" @update:model-value="paying = null">
      <div v-for="m in PAYS" :key="m" class="opt" @click="pay(m)">
        <div class="between"><span>{{ m }}</span><span class="muted">模拟支付</span></div>
      </div>
      <div class="between" style="padding: 6px 2px">
        <span class="muted">应付</span>
        <span class="price" style="font-size: 18px">{{ paying ? yuan(paying.amount) : '' }}</span>
      </div>
    </Sheet>
  </div>
</template>
