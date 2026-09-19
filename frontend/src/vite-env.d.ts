/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Backend origin, e.g. "https://api.example.com". Empty = same origin (Vite proxy / Vercel rewrite). */
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
