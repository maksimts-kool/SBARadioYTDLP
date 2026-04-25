/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
  readonly VITE_ENABLE_JOB_EVENTS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
