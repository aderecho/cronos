import { Capacitor } from '@capacitor/core'
import { SecureStoragePlugin } from 'capacitor-secure-storage-plugin'
import { apiBase } from './connection'
let access = ''
let refreshPromise:Promise<boolean>|null=null
const key='cronos.refresh'
async function readRefresh(){try{if(Capacitor.isNativePlatform()){const keys=await SecureStoragePlugin.keys();return keys.value.includes(key)?(await SecureStoragePlugin.get({key})).value:null}return sessionStorage.getItem(key)}catch{return null}}
async function writeRefresh(value:string){if(Capacitor.isNativePlatform()) await SecureStoragePlugin.set({key,value});else sessionStorage.setItem(key,value)}
export async function clearSession(){access='';if(Capacitor.isNativePlatform()){try{await SecureStoragePlugin.remove({key})}catch{}}else sessionStorage.removeItem(key)}
export async function establish(tokens:{access:string;refresh:string}){await writeRefresh(tokens.refresh);access=tokens.access}
async function renew(){const refresh=await readRefresh();if(!refresh)return false;try{const r=await fetch(`${apiBase()}/auth/refresh`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({refresh})});if(!r.ok){await clearSession();return false}const tokens=await r.json();await establish({access:tokens.access,refresh:tokens.refresh||refresh});return true}catch{return false}}
export async function restoreSession(){return renew()}
export async function logoutSession(){const refresh=await readRefresh();try{if(refresh)await api('/auth/logout',{method:'POST',body:JSON.stringify({refresh})})}finally{await clearSession()}}
export async function api<T=any>(path:string,options:RequestInit={},retry=true):Promise<T>{
  let response:Response
  try{response=await fetch(`${apiBase()}${path}`,{...options,headers:{'Content-Type':'application/json',...(access?{Authorization:`Bearer ${access}`} : {}),...options.headers},signal:options.signal||AbortSignal.timeout(20000)})}catch{throw new Error('Cannot connect to Cronos. Check your network and API address.')}
  if(response.status===401&&retry&&!path.startsWith('/auth/')){refreshPromise??=renew().finally(()=>{refreshPromise=null});if(await refreshPromise)return api(path,options,false);window.dispatchEvent(new Event('cronos:session-expired'))}
  if(response.status===204)return undefined as T
  const body=await response.json().catch(()=>({detail:'The server returned an invalid response.'}))
  if(!response.ok){const message=body.detail||Object.entries(body).map(([k,v])=>`${k}: ${Array.isArray(v)?v.join(', '):v}`).join('; ');throw new Error(message||`Request failed (${response.status})`)}
  return body
}
export async function allPages<T>(path:string):Promise<T[]>{let page=1;const all:T[]=[];while(true){const r=await api<{results:T[];next:string|null}>(`${path}${path.includes('?')?'&':'?'}page=${page}`);all.push(...r.results);if(!r.next)return all;page++}}
