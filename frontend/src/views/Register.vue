<script setup>
import { ref, reactive, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { showToast } from 'vant'
import { post } from '@/api'
import { useUserStore } from '@/stores/user'
import TopBar from '@/components/TopBar.vue'

const router = useRouter()
const store = useUserStore()
const f = reactive({ phone: '', code: '', name: '', pwd: '', pwd2: '' })
const agree = ref(false)
const loading = ref(false)
const sending = ref(false)
const left = ref(0)
let timer = 0

const tick = () => {
  left.value = 60
  clearInterval(timer)
  timer = setInterval(() => {
    if (left.value <= 1) {
      clearInterval(timer)
      left.value = 0
    } else left.value--
  }, 1000)
}
onUnmounted(() => clearInterval(timer))

const sendCode = async () => {
  if (sending.value || left.value > 0) return
  if (!/^\d{11}$/.test(f.phone)) return showToast('请输入 11 位手机号')
  sending.value = true
  try {
    const r = await post('/sms/code', { phone: f.phone })
    if (r.ok) {
      tick()
      showToast('验证码已发送：' + r.code)
    }
  } finally {
    sending.value = false
  }
}

const submit = async () => {
  if (loading.value) return
  if (!/^\d{11}$/.test(f.phone)) return showToast('请输入 11 位手机号')
  if (!/^\d{4}$/.test(f.code)) return showToast('请输入 4 位验证码')
  if (f.pwd.length < 6) return showToast('密码至少 6 位')
  if (f.pwd !== f.pwd2) return showToast('两次输入的密码不一致')
  if (!agree.value) return showToast('请先阅读并同意用户协议与隐私政策')
  loading.value = true
  try {
    const r = await store.register(f.phone, f.pwd, f.name, f.code)
    if (r.ok) {
      showToast('注册成功')
      router.replace('/home')
    }
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div>
    <TopBar title="注册账号" />
    <div class="page">
      <div class="card">
        <div class="b" style="font-size:18px">注册百灵医生</div>
        <div class="muted" style="margin:4px 0 14px">新用户注册可领取新人优惠券，在线问诊更方便</div>

        <input v-model="f.phone" class="field" maxlength="11" inputmode="numeric" placeholder="请输入手机号" />
        <div class="row" style="gap:8px;margin-bottom:10px">
          <input
            v-model="f.code"
            class="field"
            maxlength="4"
            inputmode="numeric"
            placeholder="4 位验证码"
            style="flex: 1; margin-bottom: 0"
          />
          <button
            class="btn btn-sm btn-line"
            style="flex: 0 0 auto; margin: 0"
            :disabled="left > 0 || sending"
            @click="sendCode"
          >
            {{ left > 0 ? left + 's 后重发' : '获取验证码' }}
          </button>
        </div>
        <input v-model="f.name" class="field" maxlength="12" placeholder="昵称（选填）" />
        <input v-model="f.pwd" class="field" type="password" maxlength="20" placeholder="设置密码（至少 6 位）" />
        <input v-model="f.pwd2" class="field" type="password" maxlength="20" placeholder="再次输入密码" />

        <div
          class="muted row"
          style="align-items: flex-start; gap: 8px; line-height: 1.6; margin: 2px 0 12px; padding: 6px 0; cursor: pointer"
          @click="agree = !agree"
        >
          <span
            style="flex: 0 0 auto; width: 20px; height: 20px; border-radius: 50%; font-size: 12px; line-height: 20px; text-align: center; border: 1px solid #cbd5e1; background: #fff; color: #fff"
            :style="agree ? 'background:var(--pri);border-color:var(--pri)' : ''"
            >{{ agree ? '✓' : '' }}</span
          >
          <span>我已阅读并同意《用户协议》《隐私政策》，本平台仅提供健康咨询，急重症请立即线下就医</span>
        </div>

        <button class="btn" :disabled="loading" @click="submit">{{ loading ? '注册中…' : '注 册' }}</button>
      </div>

      <div style="text-align:center;margin-top:16px">
        <span class="muted">已有账号？</span>
        <span style="color:var(--pri);font-size:13px;font-weight:600" @click="router.replace('/login')">返回登录</span>
      </div>
    </div>
  </div>
</template>
