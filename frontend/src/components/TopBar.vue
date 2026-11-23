<script setup>
import { useRouter } from 'vue-router'
const props = defineProps({
  title: { type: String, default: '' },
  right: { type: String, default: '' },
  green: { type: Boolean, default: false },
  back: { type: Boolean, default: true }
})
const emit = defineEmits(['right'])
const router = useRouter()
const onBack = () => (window.history.length > 1 ? router.back() : router.push('/home'))
</script>

<template>
  <div class="top" :class="{ green }">
    <div class="bk" @click="onBack">{{ back ? '‹' : '' }}</div>
    <div class="tt">{{ title }}</div>
    <div class="rt" @click="emit('right')">{{ right }}</div>
  </div>
</template>
