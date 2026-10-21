import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, establish, restoreSession, logoutSession } from '../services/api'
import { registerPush, disconnectPush } from '../services/push'
import type {Dashboard,User} from '../types'
export const useMonitor=defineStore('monitor',()=>{
 const user=ref<User|null>(null),data=ref<Dashboard|null>(null),loading=ref(false),error=ref(''),initialized=ref(false)
 function connect(){void registerPush(id=>{window.location.hash=`/alerts?incident=${id}`}).catch(e=>window.dispatchEvent(new CustomEvent('cronos:push-status',{detail:(e as Error).message})))}
 async function refresh(){if(!user.value||loading.value)return;loading.value=true;error.value='';try{data.value=await api<Dashboard>('/dashboard')}catch(e){error.value=(e as Error).message}finally{loading.value=false}}
 async function login(username:string,password:string,demo=false){const tokens=await api<{access:string;refresh:string}>(demo?'/auth/demo':'/auth/login',{method:'POST',body:JSON.stringify({username,password})});await establish(tokens);user.value=await api('/auth/me');await refresh();connect()}
 async function init(){try{if(await restoreSession()){user.value=await api('/auth/me');await refresh();connect()}}catch(e){error.value=(e as Error).message}finally{initialized.value=true}}
 async function logout(){disconnectPush();try{await logoutSession()}finally{user.value=null;data.value=null}}
 return {user,data,loading,error,initialized,refresh,login,init,logout}
})
