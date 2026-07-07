// Minimal typing for the Telegram Mini App bridge — only what the login uses.

interface TelegramWebApp {
  initData: string;
  ready: () => void;
}

declare global {
  interface Window {
    Telegram?: { WebApp?: TelegramWebApp };
  }
}

export function readInitData(): string | null {
  const webApp = window.Telegram?.WebApp;
  if (!webApp || !webApp.initData) return null;
  webApp.ready();
  return webApp.initData;
}
