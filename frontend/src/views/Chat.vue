<script setup>
import { ref, computed, nextTick, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showToast, showConfirmDialog } from 'vant'
import { get, post } from '@/api'
import { streamPost } from '@/api/stream'
import TopBar from '@/components/TopBar.vue'
import { yuan } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const cid = computed(() => route.params.cid)
const chat = ref(null)
const msgs = ref([])
const rx = ref(null)
const text = ref('')
const inCall = ref(false)
const seconds = ref(0)
const listEl = ref(null)
const sending = ref(false)   // 流式回复进行中，禁用重复发送
const kbInfo = ref('')       // 本次回复命中/参考的知识库来源
let timer = null

const load = async () => {
  const j = await get('/chat/' + cid.value)
  if (!j.ok) {
    chat.value = { doc: '问诊', dept: '', status: '', msg: j.msg }
    return
  }
  if (j.chat.status === '待接诊') {
    await post('/chat/' + cid.value + '/enter')
    return load()
  }
  chat.value = j.chat
  msgs.value = j.msgs || []
  rx.value = j.rx || null
  const m = j.chat.mode
  if ((m === 'video' || m === 'voice') && j.chat.status !== '已结束' && !inCall.value && seconds.value === 0) {
    inCall.value = true
    startTimer()
  }
  await nextTick()
  window.scrollTo(0, document.body.scrollHeight)
}

const startTimer = () => {
  clearInterval(timer)
  timer = setInterval(() => seconds.value++, 1000)
}

const clock = () => {
  const m = String(Math.floor(seconds.value / 60)).padStart(2, '0')
  const s = String(seconds.value % 60).padStart(2, '0')
  return m + ':' + s
}

const hangUp = () => {
  clearInterval(timer)
  inCall.value = false
}

const scrollBottom = async () => {
  await nextTick()
  window.scrollTo(0, document.body.scrollHeight)
}

// 流式发送：先本地乐观插入用户消息与空的医生气泡，再逐帧填充，
// 首字延迟从 2 到 3 秒（等完整回复）降到 100 毫秒级，不再白屏。
const send = async () => {
  const t = text.value.trim()
  if (!t || sending.value) return
  text.value = ''
  sending.value = true
  kbInfo.value = ''
  msgs.value.push({ role: 'user', text: t })
  const idx = msgs.value.push({ role: 'dr', text: '', typing: true }) - 1
  await scrollBottom()
  try {
    await streamPost('/chat/stream', { chat_id: Number(cid.value), text: t }, {
      onDelta: (v) => {
        msgs.value[idx].text += v
        scrollBottom()
      },
      onDone: (o) => {
        msgs.value[idx].typing = false
        if (o.hits && o.hits.length) {
          kbInfo.value = o.hits.map((h) => h.src.replace(/\.md$/, '')).join(' / ')
        }
      }
    })
  } catch (e) {
    msgs.value[idx].typing = false
    if (!msgs.value[idx].text) msgs.value[idx].text = '回复失败，请重试'
    showToast(e.message || '发送失败')
  } finally {
    sending.value = false
    scrollBottom()
  }
}

const end = async () => {
  await showConfirmDialog({ title: '结束问诊', message: '确认结束本次问诊？结束后可请医生开具处方。' })
  const j = await post('/chat/end', { chat_id: Number(cid.value) })
  if (j.ok) showToast('问诊已结束')
  await load()
}

const makeRx = async () => {
  const j = await post('/rx', { chat_id: Number(cid.value) })
  if (j.ok && j.rx) {
    showToast(j.msg || '处方已开具')
    router.push('/rx/' + j.rx.id)
  }
}

onMounted(load)
// 从会话列表切换到另一个会话时路由参数变化、组件实例复用，需重置状态后重新拉取
watch(cid, (v) => {
  if (!v) return
  clearInterval(timer)
  timer = null; inCall.value = false; seconds.value = 0
  chat.value = null; msgs.value = []; rx.value = null; kbInfo.value = ''; text.value = ''
  load()
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div>
    <div v-if="inCall" class="call">
      <div class="big">{{ chat?.mode === 'video' ? '🎥' : '📞' }}</div>
      <div style="font-size: 18px">{{ chat?.doc }} 医生</div>
      <div class="muted" style="color: #d1fae5">
        {{ chat?.mode === 'video' ? '视频问诊中' : '语音问诊中' }} · {{ clock() }}
      </div>
      <div class="muted" style="color: #a7f3d0; padding: 0 30px; text-align: center">
        模拟通话，挂断后可在会话中继续文字沟通
      </div>
      <div class="hang" @click="hangUp">📵</div>
    </div>

    <template v-else-if="chat">
      <TopBar
        :title="chat.doc ? chat.doc + ' · ' + chat.dept : '问诊'"
        :right="chat.status === '问诊中' ? '结束' : ''"
        @right="end"
      />
      <div class="page" :style="{ paddingBottom: chat.status === '问诊中' ? '90px' : '24px' }">
        <div v-if="!chat.doc" class="empty">{{ chat.msg || '会话不存在' }}</div>
        <template v-else>
          <div v-if="chat.pay_time" class="warn">
            已支付 {{ yuan(chat.fee) }}（{{ chat.pay || '' }}），当前状态：{{ chat.status }}
          </div>
          <div class="card" style="background: #f8fafb" @click="router.push('/mychats')">
            <div class="between">
              <span class="muted">主诉：{{ chat.symptom }}</span>
              <span class="tag">{{ chat.status }}</span>
            </div>
          </div>

          <div ref="listEl">
            <div v-for="(m, i) in msgs" :key="i" class="bubble" :class="m.role === 'dr' ? 'dr' : 'me'">
              {{ m.text }}<span v-if="m.typing" class="caret">▋</span>
            </div>
            <div v-if="!msgs.length" class="empty">医生正在整理您的病情…</div>
            <div v-if="kbInfo" class="kb-tip">📚 参考资料 · {{ kbInfo }}</div>
          </div>

          <div v-if="chat.status === '已结束'" class="card">
            <div class="b" style="margin-bottom: 6px">问诊小结</div>
            <div class="muted" style="line-height: 1.8; color: #374151">{{ chat.summary || '暂无小结' }}</div>
            <div class="split"></div>
            <button v-if="rx" class="btn btn-line" @click="router.push('/rx/' + rx.id)">查看处方（{{ rx.status }}）</button>
            <button v-else class="btn" @click="makeRx">请医生开具处方</button>
          </div>

          <div v-if="chat.status === '问诊中'" class="chatbox">
            <input v-model="text" placeholder="描述症状或补充信息…" :disabled="sending" @keydown.enter="send" />
            <button :disabled="sending" @click="send">{{ sending ? '回复中' : '发送' }}</button>
          </div>
        </template>
      </div>
    </template>
    <div v-else class="loading">加载中…</div>
  </div>
</template>
