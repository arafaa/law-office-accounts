// Service worker: استقبال الإشعارات + صفحة بديلة عند انقطاع الاتصال
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', e => {
  if (e.request.mode === 'navigate')
    e.respondWith(fetch(e.request).catch(() => new Response(
      '<meta charset="utf-8"><meta name="viewport" content="width=device-width"><body dir="rtl" style="font:18px Tahoma;text-align:center;padding:40px">لا يوجد اتصال بالخادم حالياً. حاول مرة أخرى لاحقاً.</body>',
      {headers: {'Content-Type': 'text/html; charset=utf-8'}})));
});
self.addEventListener('push', e => {
  let d = {}; try { d = e.data.json(); } catch (_) {}
  e.waitUntil(self.registration.showNotification(d.title || 'متابعة القضايا', {
    body: d.body || '', icon: '/icons/icon-192.png', badge: '/icons/icon-192.png', dir: 'rtl', lang: 'ar',
    tag: d.tag || undefined, data: {url: d.url || '/'}}));
});
self.addEventListener('notificationclick', e => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || '/';
  e.waitUntil(self.clients.matchAll({type: 'window', includeUncontrolled: true}).then(list => {
    for (const c of list) { if ('focus' in c) { if (c.navigate) c.navigate(url); return c.focus(); } }
    return self.clients.openWindow(url);
  }));
});
