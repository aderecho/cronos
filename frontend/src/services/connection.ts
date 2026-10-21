import { Capacitor } from '@capacitor/core'
const fallback=import.meta.env.VITE_API_URL||''
const localDevelopment=import.meta.env.VITE_ALLOW_LOCAL_HTTP==='true'
export function configuredUrl(){return localStorage.getItem('cronos.api-url')||fallback}
export function apiBase(){return configuredUrl().replace(/\/$/,'')||'/api/v1'}
export function setApiUrl(value:string){const next=value.trim().replace(/\/$/,'');if(next){const url=new URL(next);if(url.username||url.password||url.hash||url.search)throw new Error('Use an API URL without credentials, query parameters, or fragments.');if(url.protocol!=='https:'&&!(url.protocol==='http:'&&['127.0.0.1','localhost'].includes(url.hostname)&&(!Capacitor.isNativePlatform()||localDevelopment)))throw new Error('Use an HTTPS API address.');if(!url.pathname.endsWith('/api/v1'))throw new Error('The API address must end with /api/v1.');localStorage.setItem('cronos.api-url',next)}else{localStorage.removeItem('cronos.api-url');if(Capacitor.isNativePlatform()&&!fallback)throw new Error('Enter your Cronos backend HTTPS address.')}}
