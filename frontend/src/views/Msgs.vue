<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { SwipeCell, showConfirmDialog, showToast } from 'vant'
import { get, post, del } from '@/api'
import TopBar from '@/components/TopBar.vue'

const route = useRoute()
const router = useRouter()
const tab = ref(route.query.tab || 'chat')
const data = ref({ chats: [], notices: [], unread: 0 })
const PAGE = 20
const total = ref(0)
const hasMore = ref(false)
const loadingMore = ref(false)

const load = async () => {
  data.value = await get('/msgs', { limit: PAGE, offset: 0 })
  total.value = data.value.total || 0
  hasMore.value = !!data.value.has_more
}

// 只有 notices 走分页，chats / unread 仍由后端一次性返回全量
const loadMore = async () => {
  if (loadingMore.value || !hasMore.value) return
  loadingMore.value = true
  const j = await get('/msgs', { limit: PAGE, offset: data.value.notices.length })
  data.value = { ...data.value, notices: data.value.notices.concat(j.notices || []) }
  total.value = j.total || total.value
  hasMore.value = !!j.has_more
  loadingMore.value = false
}

const readAll = async () => {
  const j = await post('/msgs/read')
  if (j.ok) {
    showToast(j.msg || '已全部标记为已读')
    load()
  }
}

const tagClass = computed(() => (s) => (s === '问诊中' ? 'w' : s === '待支付' ? 'r' : 'g'))

const confirmDel = async (message) => {
  try {
    await showConfirmDialog({ title: '删除确认', message, confirmButtonText: '删除' })
    return true
  } catch (e) {
    return false // 用户取消
  }
}

// 左滑删除会话（后端软删除，会话详情页仍可打开，不会断链）
const delChat = async (c) => {
  if (!(await confirmDel('删除后该会话将从消息列表移除且不可恢复，确定删除？'))) return
  try {
    const j = await del('/chat/' + c.id)
    if (j.ok) {
      showToast(j.msg || '会话已删除')
      data.value = { ...data.value, chats: (data.value.chats || []).filter((x) => x.id !== c.id) }
    }
  } catch (e) {
    /* 失败提示已由 axios 拦截器按后端 msg 弹出 */
  }
}

// 左滑删除系统通知，同步扣减未读数与总数
const delNotice = async (n) => {
  if (!(await confirmDel('删除后该通知将不可恢复，确定删除？'))) return
  try {
    const j = await del('/msg/notice/' + n.id)
    if (j.ok) {
      showToast(j.msg || '通知已删除')
      const left = (data.value.notices || []).filter((x) => x.id !== n.id)
      const unread = Math.max(0, (data.value.unread || 0) - (n.read ? 0 : 1))
      data.value = { ...data.value, notices: left, unread }
      total.value = Math.max(0, total.value - 1)
    }
  } catch (e) {
    /* 失败提示已由 axios 拦截器按后端 msg 弹出 */
  }
}

onMounted(load)
</script>

<template>
  <div>
    <TopBar title="消息" right="全部已读" @right="readAll" />
    <div class="page">
      <div class="seg">
        <div :class="{ on: tab === 'chat' }" @click="tab = 'chat'">问诊消息</div>
        <div :class="{ on: tab === 'notice' }" @click="tab = 'notice'">
          系统通知<span v-if="data.unread"> ({{ data.unread }})</span>
        </div>
      </div>

      <div class="card">
        <template v-if="tab === 'chat'">
          <SwipeCell v-for="c in data.chats" :key="c.id">
            <div class="item" @click="router.push('/chat/' + c.id)">
              <div class="em">{{ c.icon }}</div>
              <div class="bd">
                <div class="between">
                  <span class="tt">{{ c.doc }}</span>
                  <span class="muted">{{ (c.created || '').slice(5) }}</span>
                </div>
                <div class="ds">{{ c.last || '主诉：' + (c.symptom || '') }}</div>
              </div>
              <div><span class="tag" :class="tagClass(c.status)">{{ c.status }}</span></div>
            </div>
            <template #right>
              <button class="swipe-del" @click="delChat(c)">删除</button>
            </template>
          </SwipeCell>
          <div v-if="!data.chats?.length" class="empty">暂无会话，去发起一次问诊吧</div>
        </template>
        <template v-else>
          <SwipeCell v-for="n in data.notices" :key="n.id">
            <div style="padding: 10px 0; border-bottom: 1px solid var(--line)">
              <div class="between">
                <span class="b">{{ n.title }}</span>
                <span class="muted">{{ (n.created || '').slice(5) }}</span>
              </div>
              <div class="muted" style="color: #374151; margin-top: 4px">{{ n.body }}</div>
            </div>
            <template #right>
              <button class="swipe-del" @click="delNotice(n)">删除</button>
            </template>
          </SwipeCell>
          <div v-if="!data.notices?.length" class="empty">暂无通知</div>
          <div v-if="data.notices?.length" class="more">
            <button v-if="hasMore" class="btn btn-line" :disabled="loadingMore" @click="loadMore">
              {{ loadingMore ? '加载中…' : '加载更多' }}
            </button>
            <div v-else class="muted">没有更多了</div>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.more {
  text-align: center;
  padding: 10px 0;
}
/* 左滑露出的删除按钮，与卡片行同高 */
.swipe-del {
  width: 72px;
  height: 100%;
  min-height: 56px;
  border: 0;
  background: #ef4444;
  color: #fff;
  font-size: 14px;
  border-radius: 0;
}
</style>
