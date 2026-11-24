<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { showToast } from 'vant'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const store = useUserStore()
const phone = ref('13800000000')
const pwd = ref('123456')
const loading = ref(false)

const submit = async () => {
  if (loading.value) return
  loading.value = true
  try {
    const r = await store.login(phone.value.trim(), pwd.value.trim())
    if (r.ok) {
      showToast('登录成功')
      router.replace('/home')
    }
  } catch (e) {
    // 401 已由 axios 拦截器提示「手机号或密码错误」，此处只吞掉异常避免控制台报错
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div>
    <div style="padding: 56px 24px 0; text-align: center">
      <div style="font-size: 52px">🩺</div>
      <div style="font-size: 22px; font-weight: 700; margin: 10px 0 2px">🩺 百灵医生 · DevOps 自动部署演示成功 ✓</div>
      <div class="muted" style="margin-bottom: 26px">三甲名医在线 · 图文语音视频问诊</div>
    </div>
    <div style="padding: 0 24px">
      <input v-model="phone" class="field" placeholder="手机号" />
      <input v-model="pwd" class="field" type="password" placeholder="密码" />
      <button class="btn" :disabled="loading" @click="submit">登 录</button>
      <div
        style="text-align: center; margin-top: 14px; padding: 8px 0; font-size: 13px; cursor: pointer"
        @click="router.push('/register')"
      >
        <span class="muted">没有账号？</span>
        <span style="color: var(--pri); font-weight: 600">请先注册</span>
      </div>
      <div class="muted" style="margin-top: 10px; text-align: center">演示账号 13800000000 / 123456</div>
      <div class="muted" style="margin-top: 30px; text-align: center; line-height: 1.8">
        登录即代表同意《用户协议》《隐私政策》<br />本平台仅提供健康咨询，急重症请立即线下就医
      </div>
    </div>
  </div>
</template>