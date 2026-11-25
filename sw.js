/* 뉴스레이더 — 오프라인에서도 마지막으로 본 뉴스를 보여주는 최소 서비스워커
   네트워크 우선(network-first): 항상 최신을 먼저 받고, 실패했을 때만 캐시를 쓴다.
   캐시가 먼저 나갔다가 네트워크로 덮어쓰는 방식이 아니므로 화면이 두 번 그려지지 않는다.
   새 판(이 파일이 바뀌면)은 install 에서 곧바로 대기 없이 넘겨받고(skipWaiting),
   activate 에서 옛 버전 캐시를 전부 지운 뒤 화면을 넘겨받는다(clients.claim).
   그래서 사용자가 캐시를 직접 지우거나 새로고침하지 않아도 접속할 때마다 최신 화면·최신 데이터가 뜬다.
   index.html · data/*.json 은 쿼리스트링까지 포함해 언제나 네트워크를 먼저 탄다(cache:'no-store'). */
const CACHE = 'newsradar-v110';
const SHELL = ['./', './index.html', './manifest.json', './icons/icon-192.png', './data/calendar.json', './data/radar.json'];
const NEWS_KEY = './data/news.json';   // 쿼리스트링이 붙어도 캐시에는 이 한 자리에만 남긴다

self.addEventListener('install', e => {
  self.skipWaiting();
  /* 껍데기(index.html)도 브라우저 HTTP 캐시에 기대지 않고 서버에서 새로 받아 둔다
     파일별로 따로 받는다 — 아직 없는 자료(calendar·radar 등)가 하나 있어도 나머지 껍데기는 캐시에 남게 */
  e.waitUntil(caches.open(CACHE).then(c => Promise.all(SHELL.map(u => c.add(new Request(u, {cache:'reload'})).catch(() => {})))).catch(() => {}));
});

self.addEventListener('activate', e => {
  e.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)));
    await self.clients.claim();
  })());
});

const isNewsJson = url => /\/data\/news\.json$/.test(url.pathname);
const isCalJson = url => /\/data\/calendar\.json$/.test(url.pathname);
const isRadarJson = url => /\/data\/radar\.json$/.test(url.pathname);
const isHotJson = url => /\/data\/hotbar\.json$/.test(url.pathname);
const isHotMonJson = url => /\/data\/hotbar_monthly\.json$/.test(url.pathname);
const isPopupJson = url => /\/data\/popup\.json$/.test(url.pathname);
const isDayJson = url => /\/data\/day125\.json$/.test(url.pathname);
const isWeekJson = url => /\/data\/week\.json$/.test(url.pathname);
const isSchedJson = url => /\/data\/schedule\.json$/.test(url.pathname);
/* 화면 문서는 index.html 하나다 — 주소가 '/'든 '/index.html'이든, 새로 열든 늘 서버에서 새로 */
const isDoc = (req, url) => req.mode === 'navigate' || /\/index\.html$/.test(url.pathname) || url.pathname.endsWith('/');
const CAL_KEY = './data/calendar.json';
const RADAR_KEY = './data/radar.json';
const HOT_KEY = './data/hotbar.json';
const HOTMON_KEY = './data/hotbar_monthly.json';
const POPUP_KEY = './data/popup.json';
const DAY_KEY = './data/day125.json';
const WEEK_KEY = './data/week.json';
const SCHED_KEY = './data/schedule.json';

/* 캐시에서 꺼낸 응답에는 표시(x-news-cache)를 붙인다.
   화면은 이 표시를 보면 "새로고침 실패(저장본 표시)"로 알린다 — 오래된 데이터를 최신이라고 말하지 않기 위해. */
async function markCached(res){
  try{
    const h = new Headers(res.headers);
    h.set('x-news-cache', '1');
    h.delete('content-length');
    h.delete('content-encoding');
    return new Response(await res.blob(), {status: res.status, statusText: res.statusText, headers: h});
  }catch(e){ return res; }
}

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  const news = isNewsJson(url);
  const cal = isCalJson(url);
  const rdr = isRadarJson(url);
  const hot = isHotJson(url);
  const hotmon = isHotMonJson(url);
  const popup = isPopupJson(url);
  const day = isDayJson(url);
  const week = isWeekJson(url);
  const sch = isSchedJson(url);
  const doc = isDoc(req, url);

  e.respondWith((async () => {
    try {
      // 문서·데이터는 쿼리스트링과 무관하게 항상 네트워크가 먼저(그리고 캐시 협상 없이)
      const fresh = await fetch(req, {cache: (doc || news || cal || rdr || hot || hotmon || popup || day || week || sch) ? 'no-store' : 'no-cache'});
      if (fresh && fresh.ok && (fresh.type === 'basic' || fresh.type === 'default')) {
        const copy = fresh.clone();
        const key = doc ? './index.html' : (news ? NEWS_KEY : (cal ? CAL_KEY : (rdr ? RADAR_KEY : (hot ? HOT_KEY : (hotmon ? HOTMON_KEY : (popup ? POPUP_KEY : (day ? DAY_KEY : (week ? WEEK_KEY : (sch ? SCHED_KEY : req)))))))));   // 데이터 파일은 한 자리에만 저장(매번 다른 ?_= 주소로 쌓이지 않게)
        caches.open(CACHE).then(c => c.put(key, copy)).catch(() => {});
      }
      return fresh;
    } catch (err) {
      const hit = await caches.match(req, {ignoreSearch: true});
      if (hit) return news ? await markCached(hit) : hit;
      if (doc) {
        const shell = await caches.match('./index.html', {ignoreSearch: true});
        if (shell) return shell;
      }
      throw err;
    }
  })());
});
