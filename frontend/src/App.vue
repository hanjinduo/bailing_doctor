<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import TabBar from '@/components/TabBar.vue'

const route = useRoute()
const showTab = computed(() => !!route.meta.tab)
</script>

<template>
  <div class="phone">
    <div id="view" :style="{ paddingBottom: showTab ? '70px' : '0' }">
      <router-view />
    </div>
    <TabBar v-if="showTab" :current="route.meta.tab" />
  </div>
</template>
