(function () {
  var cfg = window.SP_COOKIE_CONFIG || {};
  var name = cfg.cookieName || 'sp_cookie_consent';
  var days = cfg.maxAgeDays || 180;
  var gaId = (cfg.gaId || '').trim();

  function readConsent() {
    var m = document.cookie.match(new RegExp('(?:^|; )' + name.replace(/([.$?*|{}()[\]\\/+^])/g, '\\$1') + '=([^;]*)'));
    if (!m) return null;
    try {
      return JSON.parse(decodeURIComponent(m[1]));
    } catch (e) {
      return null;
    }
  }

  function writeConsent(obj) {
    var maxAge = days * 24 * 60 * 60;
    var value = encodeURIComponent(JSON.stringify(obj));
    var secure = location.protocol === 'https:' ? '; Secure' : '';
    document.cookie = name + '=' + value + '; path=/; max-age=' + maxAge + '; SameSite=Lax' + secure;
  }

  function loadAnalytics() {
    if (!gaId || window.__spGaLoaded) return;
    window.__spGaLoaded = true;
    window.dataLayer = window.dataLayer || [];
    function gtag() { dataLayer.push(arguments); }
    window.gtag = gtag;
    gtag('js', new Date());
    gtag('config', gaId, {
      anonymize_ip: true,
      send_page_view: true,
    });
    var s = document.createElement('script');
    s.async = true;
    s.src = 'https://www.googletagmanager.com/gtag/js?id=' + encodeURIComponent(gaId);
    document.head.appendChild(s);
  }

  function apply(consent) {
    if (consent && consent.analytics) loadAnalytics();
  }

  function hideBanner() {
    var el = document.getElementById('sp-cookie-banner');
    if (el) el.hidden = true;
  }

  function showBanner() {
    var el = document.getElementById('sp-cookie-banner');
    if (el) el.hidden = false;
  }

  document.addEventListener('DOMContentLoaded', function () {
    var existing = readConsent();
    if (existing) {
      apply(existing);
      hideBanner();
      return;
    }
    showBanner();
    document.querySelectorAll('[data-sp-cookie]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var mode = btn.getAttribute('data-sp-cookie');
        var consent = {
          essential: true,
          analytics: mode === 'all' && !!gaId,
          marketing: false,
          ts: Date.now(),
        };
        writeConsent(consent);
        apply(consent);
        hideBanner();
      });
    });
  });

  window.SP_openCookiePreferences = function () {
    showBanner();
  };
})();
