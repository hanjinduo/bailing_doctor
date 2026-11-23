<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { showConfirmDialog, showToast } from 'vant'
import { useUserStore } from '@/stores/user'
import { post } from '@/api'

const router = useRouter()
const store = useUserStore()
const user = ref(null)
const stat = ref({})
const oc = ref({ 待支付: 0, 待发货: 0, 已发货: 0, 已完成: 0, 已退款: 0 })
const cc = ref({ 待支付: 0, 待接诊: 0, 问诊中: 0, 已结束: 0 })

const TEL = '400-881-8120'
const VERSION = '1.0.0'

const phone = computed(() => {
  const p = (user.value && user.value.phone) || ''
  return /^\d{11}$/.test(p) ? p.slice(0, 3) + '****' + p.slice(7) : p
})
const isVip = computed(() => !!(user.value && user.value.vip && user.value.vip_until))

const orderTabs = [
  { n: '待付款', e: '💰', s: '待支付', k: '待支付' },
  { n: '待发货', e: '📦', s: '待发货', k: '待发货' },
  { n: '待收货', e: '🚚', s: '已发货', k: '已发货' },
  { n: '待评价', e: '✍️', s: '已完成', k: '已完成' },
  { n: '退款/售后', e: '↩️', s: '已退款', k: '已退款' }
]
const chatTabs = [
  { n: '待支付', e: '💳', s: '待支付', k: '待支付' },
  { n: '待接诊', e: '⏳', s: '待接诊', k: '待接诊' },
  { n: '问诊中', e: '💬', s: '问诊中', k: '问诊中' },
  { n: '已完成', e: '✅', s: '已结束', k: '已结束' }
]
const funcs = [
  { n: '我的处方', e: '💊', p: '/rxs' },
  { n: '健康档案', e: '📁', p: '/records' },
  { n: '收货地址', e: '📍', p: '/address' },
  { n: '我的挂号', e: '📅', p: '/appts' },
  { n: '我的收藏', e: '⭐', p: '' },
  { n: '家庭医生', e: '🩺', p: '' },
  { n: '用药提醒', e: '⏰', p: '' },
  { n: '客服中心', e: '🎧', p: '' }
]
const tools = [
  { n: 'BMI 测算', d: '身高体重算健康指数', e: '📐', p: '' },
  { n: '健康测评', d: '3 分钟评估身体状态', e: '🧪', p: '' },
  { n: '极速问诊', d: '1 分钟接诊 · 名医在线', e: '⚡', p: '/ask' },
  { n: '健康资讯', d: '权威科普每日更新', e: '📰', p: '/news' }
]

const go = (p, s) => {
  if (!p) return showToast('功能开发中')
  router.push(s ? { path: p, query: { status: s } } : p)
}
const todo = () => showToast('功能开发中')

const logout = async () => {
  await showConfirmDialog({ title: '退出登录', message: '确认退出当前账号？' })
  // 先通知后端注销（token_ver+1，旧 token 立即失效）；网络异常也要清理本地状态
  try {
    await post('/logout')
  } catch (e) {
    // 忽略网络异常：本地 token 照常清除，避免卡在已登录界面
  }
  store.logout()
  showToast('已退出')
  router.replace('/login')
}

onMounted(async () => {
  const j = await store.fetchMe()
  if (!j || !j.ok) return showToast('请重新登录')
  user.value = j.user
  stat.value = j.stat || {}
  // 宫格角标改用后端 stat 的全量分组计数（列表接口已分页，不能再靠拉全量数组统计）
  const os = stat.value.order_status || {}
  Object.keys(oc.value).forEach((k) => { oc.value[k] = os[k] || 0 })
  const cs = stat.value.chat_status || {}
  Object.keys(cc.value).forEach((k) => { cc.value[k] = cs[k] || 0 })
})
</script>

<template>
  <div>
    <div class="me-hd">
      <div class="me-top">
        <span class="set" @click="todo">⚙</span>
      </div>
      <div class="hd">
        <div class="avatar lg av">{{ (user && user.avatar) || '🙂' }}</div>
        <div class="who">
          <div class="name">
            {{ (user && user.name) || '未登录' }}
            <span v-if="user && user.phone" class="real">已实名</span>
          </div>
          <div class="sub">
            {{ phone }}<span v-if="user && user.sex"> · {{ user.sex }}{{ user.age ? ' · ' + user.age + '岁' : '' }}</span>
          </div>
        </div>
      </div>
      <div class="vipcard" :class="{ on: isVip }" @click="router.push('/vip')">
        <div>
          <div class="vt">👑 百灵健康会员</div>
          <div class="vs">{{ isVip ? '有效期至 ' + user.vip_until : '未开通 · 问诊 9 折 / 购药包邮 / 极速接诊' }}</div>
        </div>
        <span class="vbtn">{{ isVip ? '立即续费' : '立即开通' }}</span>
      </div>
    </div>

    <div class="page" style="margin-top: -20px">
      <div class="card assets">
        <div @click="router.push('/coupons')"><b>{{ stat.coupons || 0 }}</b><span>优惠券</span></div>
        <div @click="todo"><b class="na">—</b><span>积分</span></div>
        <div @click="todo"><b class="na">—</b><span>健康币</span></div>
      </div>

      <div class="card">
        <div class="cbar">
          <b>我的订单</b>
          <span class="more" @click="router.push('/orders')">查看全部 ›</span>
        </div>
        <div class="grid g5">
          <div v-for="x in orderTabs" :key="x.n" class="ico" @click="go('/orders', x.s)">
            <div class="em">
              <i>{{ x.e }}</i>
              <em v-if="oc[x.k]" class="dot">{{ oc[x.k] }}</em>
            </div>
            {{ x.n }}
          </div>
        </div>
      </div>

      <div class="card">
        <div class="cbar">
          <b>我的问诊</b>
          <span class="more" @click="router.push('/mychats')">问诊记录 {{ stat.chats || 0 }} 条 ›</span>
        </div>
        <div class="grid g4">
          <div v-for="x in chatTabs" :key="x.n" class="ico" @click="go('/mychats', x.s)">
            <div class="em">
              <i>{{ x.e }}</i>
              <em v-if="cc[x.k]" class="dot">{{ cc[x.k] }}</em>
            </div>
            {{ x.n }}
          </div>
        </div>
      </div>

      <div class="card">
        <div class="cbar"><b>常用功能</b></div>
        <div class="grid g4">
          <div v-for="x in funcs" :key="x.n" class="ico" @click="go(x.p)">
            <div class="em">{{ x.e }}</div>
            {{ x.n }}
          </div>
        </div>
      </div>

      <div class="card">
        <div class="cbar"><b>健康工具</b><span class="more">常用</span></div>
        <div v-for="x in tools" :key="x.n" class="tool" @click="go(x.p)">
          <div class="te">{{ x.e }}</div>
          <div>
            <div class="tn">{{ x.n }}</div>
            <div class="td">{{ x.d }}</div>
          </div>
          <span class="ar">›</span>
        </div>
      </div>

      <div class="foot">
        <div class="tel" @click="todo">📞 客服电话 {{ TEL }}</div>
        <div class="ver">百灵医生 v{{ VERSION }}</div>
        <button class="btn quit" @click="logout">退出登录</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.me-hd {
  background: linear-gradient(135deg, #13b8a6, #0a8f8a);
  padding: 6px 14px 38px;
  color: #fff;
}
.me-top {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  height: 32px;
}
.set {
  font-size: 18px;
  opacity: 0.95;
  padding: 2px 4px;
  cursor: pointer;
}
.av {
  background: rgba(255, 255, 255, 0.24);
  border: 2px solid rgba(255, 255, 255, 0.55);
}
.who {
  flex: 1;
  min-width: 0;
}
.name {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 18px;
  font-weight: 700;
}
.real {
  font-size: 10px;
  font-weight: 400;
  padding: 1px 6px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.22);
  border: 1px solid rgba(255, 255, 255, 0.5);
}
.sub {
  margin-top: 3px;
  font-size: 12px;
  opacity: 0.92;
}
.vipcard {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 14px;
  padding: 10px 12px;
  border-radius: 12px;
  background: rgba(15, 23, 42, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.2);
  cursor: pointer;
}
.vipcard.on {
  background: linear-gradient(135deg, #f7e1b5, #c9a25c);
  border: 0;
  color: #3a2d12;
}
.vt {
  font-size: 13px;
  font-weight: 700;
}
.vs {
  margin-top: 2px;
  font-size: 11px;
  opacity: 0.92;
}
.vbtn {
  flex: 0 0 auto;
  margin-left: 8px;
  padding: 5px 12px;
  border-radius: 14px;
  background: #fff;
  color: #0a8f8a;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}
.vipcard.on .vbtn {
  background: #3a2d12;
  color: #f7e1b5;
}
.assets {
  display: flex;
  text-align: center;
  padding: 12px 0;
}
.assets div {
  flex: 1;
  cursor: pointer;
}
.assets b {
  display: block;
  font-size: 19px;
  color: var(--ink);
}
.assets b.na {
  color: #c3cad3;
}
.assets span {
  font-size: 11px;
  color: var(--gray);
}
.cbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.more {
  font-size: 12px;
  color: var(--gray);
  font-weight: 400;
  cursor: pointer;
}
.ico .em {
  position: relative;
}
.ico .em i {
  font-style: normal;
}
.dot {
  position: absolute;
  top: -5px;
  right: -7px;
  min-width: 16px;
  height: 16px;
  line-height: 16px;
  padding: 0 4px;
  border-radius: 9px;
  background: #ff5a3c;
  color: #fff;
  font-size: 10px;
  font-style: normal;
  font-weight: 600;
}
.tool {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 0;
  border-bottom: 1px solid var(--line);
  cursor: pointer;
}
.tool:last-child {
  border-bottom: 0;
}
.tool .te {
  width: 36px;
  height: 36px;
  border-radius: 12px;
  background: #eefaf7;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
}
.tool .tn {
  font-size: 14px;
  font-weight: 600;
}
.tool .td {
  font-size: 11px;
  color: var(--gray);
}
.tool .ar {
  margin-left: auto;
  color: #c3cad3;
  font-size: 16px;
}
.foot {
  padding: 4px 0 20px;
  text-align: center;
}
.tel {
  font-size: 12px;
  color: var(--pri);
  margin-bottom: 4px;
  cursor: pointer;
}
.ver {
  font-size: 11px;
  color: var(--gray);
  margin-bottom: 12px;
}
.quit {
  background: #fff;
  color: #ef4444;
  border: 1px solid #f6d5d5;
  font-size: 15px;
}
</style>
