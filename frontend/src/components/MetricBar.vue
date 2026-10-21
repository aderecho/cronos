<script setup lang="ts">
defineProps<{label:string;value:number|null|undefined;stale?:boolean}>()
</script>
<template><div class="metric-bar"><span>{{label}}</span><b>{{stale||value==null?'—':`${Math.round(value)}%`}}</b><div class="track"><i :class="value!=null&&value>=85?'bad':''" :style="{width:`${stale?0:value||0}%`}"/></div></div></template>
