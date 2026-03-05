const CACHE_NAME = 'dingchung-v4';
const ASSETS = [
  './',
  './index.html',
  './manifest.json',
  'https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;700&display=swap',
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (e) => {
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        const clone = res.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(e.request, clone));
        return res;
      })
      .catch(() => caches.match(e.request))
  );
});

// 알림 클릭 → 앱 열기
self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  const url = e.notification.data?.url || './';
  e.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
      for (const client of list) {
        if (client.url.includes('etf_report') && 'focus' in client) {
          return client.focus();
        }
      }
      return clients.openWindow(url);
    })
  );
});

// 메시지 기반 알림 (페이지에서 SW로 알림 요청)
self.addEventListener('message', (e) => {
  if (e.data && e.data.type === 'SHOW_NOTIFICATION') {
    const { title, body, tag, url } = e.data;
    self.registration.showNotification(title, {
      body,
      icon: './icons/icon-192.png',
      badge: './icons/icon-192.png',
      tag: tag || 'ding-alert',
      data: { url: url || './' },
      vibrate: [200, 100, 200],
      requireInteraction: false,
    });
  }

  // 예약 알림 스케줄 (알림 반복)
  if (e.data && e.data.type === 'SCHEDULE_CHECK') {
    // 알림 데이터 캐시에 저장
    caches.open('ding-alerts').then((cache) => {
      const blob = new Blob([JSON.stringify(e.data.alerts)], { type: 'application/json' });
      cache.put('alert-data', new Response(blob));
    });
  }
});
