<script setup lang="ts">
import { ref,computed,onMounted,onUnmounted } from 'vue'
import { useRoute,useRouter } from 'vue-router'
import { LayoutGrid,Server,Boxes,Bell,Settings,Activity,LogOut,RefreshCw,ShieldCheck,ArrowRight } from 'lucide-vue-next'
import { useMonitor } from './stores/monitor'
import { unregisterPush } from './services/push'
import { App as NativeApp } from '@capacitor/app'
import { Capacitor } from '@capacitor/core'
import { configuredUrl,setApiUrl } from './services/connection'
const store=useMonitor(),route=useRoute(),router=useRouter()
const backendUrl=ref(configuredUrl())
const username=ref(''),password=ref(''),loginError=ref(''),signingIn=ref(false)
const nav=computed(()=>[{path:'/',label:'Overview',icon:LayoutGrid},{path:'/servers',label:'Servers',icon:Server},{path:'/applications',label:'Applications',icon:Boxes},{path:'/alerts',label:'Alerts',icon:Bell},{path:'/settings',label:'Settings',icon:Settings},...(store.user?.is_admin?[{path:'/users',label:'Users & roles',icon:ShieldCheck}]:[])])
let timer:ReturnType<typeof setInterval>|undefined
let removeNative:(()=>Promise<void>)|undefined
async function signIn(demo=false){signingIn.value=true;loginError.value='';try{if(!demo)setApiUrl(backendUrl.value);await store.login(username.value,password.value,demo)}catch(e){loginError.value=(e as Error).message}finally{signingIn.value=false}}
async function signOut(){try{await unregisterPush()}catch{}await store.logout();await router.replace('/')}
const refresh=()=>{if(document.visibilityState==='visible')void store.refresh()}
const expired=()=>{void store.logout()}
onMounted(async()=>{await store.init();timer=setInterval(refresh,30000);document.addEventListener('visibilitychange',refresh);window.addEventListener('cronos:refresh',refresh);window.addEventListener('cronos:session-expired',expired);if(Capacitor.isNativePlatform()){const h=await NativeApp.addListener('appStateChange',({isActive})=>{if(isActive)void store.refresh()});removeNative=()=>h.remove()}})
onUnmounted(()=>{clearInterval(timer);document.removeEventListener('visibilitychange',refresh);window.removeEventListener('cronos:refresh',refresh);window.removeEventListener('cronos:session-expired',expired);void removeNative?.()})
</script>
<template>
 <div v-if="!store.initialized" class="startup"><Activity class="pulse-logo"/><p>Connecting to Cronos…</p><q-spinner color="primary" size="26px"/></div>
 <main v-else-if="!store.user" class="login-page">
  <div class="login-brand"><Activity :size="32"/><span>Cronos</span></div>
  <section class="login-panel">
   <div class="login-symbol"><ShieldCheck :size="30"/></div><h1>Your infrastructure.<br>Your peace of mind.</h1><p>Sign in to monitor your servers and applications.</p>
   <form @submit.prevent="signIn()"><q-input v-if="Capacitor.isNativePlatform()" v-model="backendUrl" label="Backend API URL" hint="https://monitor.example.com/api/v1" outlined type="url" required/><q-input v-model="username" label="Username" outlined autocomplete="username" required/><q-input v-model="password" label="Password" type="password" outlined autocomplete="current-password" required/><div v-if="loginError" class="error-box" role="alert">{{loginError}}</div><q-btn type="submit" color="primary" unelevated no-caps class="full-width" label="Sign in" :loading="signingIn"/></form>
   <button v-if="!Capacitor.isNativePlatform()" class="demo-link" @click="signIn(true)" :disabled="signingIn">Explore the demo <ArrowRight :size="16"/></button>
   <div class="login-foot">Cronos · Server & application monitoring</div>
  </section>
  <div class="login-aside"><span class="orb"><Activity :size="100" :stroke-width="1.2"/></span><h2>Know before<br>it becomes downtime.</h2><p>Server health. Application status.<br>Every incident, in one place.</p><div class="login-signal"><i/> Monitoring that stays awake.</div></div>
 </main>
 <q-layout v-else view="hHh Lpr fFf">
  <aside class="sidebar">
   <router-link to="/" class="brand"><Activity :size="37"/><span>Cronos</span></router-link>
   <nav aria-label="Main navigation"><router-link v-for="item in nav" :key="item.path" :to="item.path" :class="{selected:route.path===item.path}"><component :is="item.icon" :size="21"/><span>{{item.label}}</span><span v-if="item.path==='/alerts'&&store.data?.incidents.length" class="nav-count">{{store.data.incidents.length}}</span></router-link></nav>
   <div class="sidebar-bottom"><div v-if="store.data?.demo" class="demo-note"><Server :size="17"/><b>Demo data</b><p>Synthetic infrastructure.<br>Connect a server to monitor real metrics.</p></div><button @click="signOut" class="account"><span class="avatar">{{store.user?.username.slice(0,1).toUpperCase()}}</span><span>{{store.user?.username}}<small>{{store.user?.is_admin?'Administrator':'Team member'}}</small></span><LogOut :size="17"/></button></div>
  </aside>
  <header class="mobile-header"><router-link to="/" class="brand"><Activity :size="27"/>Cronos</router-link><div><q-btn flat round size="sm" aria-label="Settings" to="/settings"><Settings :size="20"/></q-btn><q-btn flat round size="sm" aria-label="Sign out" @click="signOut"><LogOut :size="19"/></q-btn></div></header>
  <main class="app-main">
   <div v-if="store.error" class="connection-banner" role="alert"><span>{{store.error}} <b v-if="store.data">Showing previously fetched data.</b></span><q-btn flat no-caps label="Retry" @click="store.refresh"/></div>
   <router-view/>
   <footer class="app-footer"><span><span class="status-dot" :class="store.data?.monitoring.scheduler_healthy?'good':'warn'"/>{{store.data?.monitoring.scheduler_healthy?'Monitoring worker connected':'Monitoring worker needs attention'}}</span><span>Times shown in Asia/Manila · Refreshes every 30s</span></footer>
  </main>
  <nav class="bottom-nav" aria-label="Mobile navigation"><router-link v-for="item in nav.slice(0,4)" :key="item.path" :to="item.path" :class="{selected:route.path===item.path}"><component :is="item.icon" :size="21"/><span>{{item.label}}</span></router-link></nav>
 </q-layout>
</template>
