import { defineConfig } from '@playwright/test'
export default defineConfig({testDir:'./e2e',fullyParallel:false,workers:1,timeout:60000,reporter:'list',use:{baseURL:'http://127.0.0.1:9100',channel:'chrome',headless:true},outputDir:process.env.CRONOS_QA_DIR||'/tmp/cronos-playwright-results'})
