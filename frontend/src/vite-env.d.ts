/// <reference types="vite/client" />

interface AppConfig {
  gatewayUrl: string;
  ingestionUrl: string;
  retrievalUrl: string;
}

interface Window {
  __APP_CONFIG__?: Partial<AppConfig>;
}
