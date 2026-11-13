// Shared behaviour for every page. No dependencies.
(function () {
  'use strict';

  var year = document.getElementById('year');
  if (year) year.textContent = new Date().getFullYear();

  // --- GA4 dataLayer helpers (safe when GTM is blocked) -----------------
  window.dataLayer = window.dataLayer || [];
  function dlpush(name, props) {
    var e = { event: name };
    if (props) for (var k in props) if (Object.prototype.hasOwnProperty.call(props, k)) e[k] = props[k];
    window.dataLayer.push(e);
  }
  function domainOf(url) {
    try { return new URL(url, location.href).hostname.replace(/^www\./, ''); } catch (e) { return ''; }
  }

  // paper_view: fires on /papers/<arxiv-id>.html
  var paperMatch = location.pathname.match(/\/papers\/([^\/]+?)\.html?$/);
  if (paperMatch) dlpush('paper_view', { paper_id: paperMatch[1] });

  // --- Consent banner (Google Consent Mode v2) --------------------------
  var CONSENT_KEY = 'consent-v1';
  var stored = null;
  try { stored = JSON.parse(localStorage.getItem(CONSENT_KEY)); } catch (e) {}

  function applyConsent(granted) {
    try { localStorage.setItem(CONSENT_KEY, JSON.stringify({ analytics: !!granted, ts: Date.now() })); } catch (e) {}
    if (typeof gtag === 'function') {
      gtag('consent', 'update', { analytics_storage: granted ? 'granted' : 'denied' });
    } else {
      window.dataLayer.push({ event: 'consent_update', analytics_storage: granted ? 'granted' : 'denied' });
    }
    dlpush(granted ? 'consent_accept' : 'consent_reject');
  }

  function buildBanner() {
    if (document.getElementById('consent-banner')) return;
    var w = document.createElement('div');
    w.id = 'consent-banner';
    w.setAttribute('role', 'dialog');
    w.setAttribute('aria-label', 'Cookie consent');
    w.setAttribute('aria-live', 'polite');
    w.innerHTML =
      '<p class="consent-text">This site uses Google Analytics to measure anonymous visits. ' +
      'No advertising, no profiling, no data sold. ' +
      '<a href="#" class="consent-more">Details</a></p>' +
      '<details class="consent-details" hidden>' +
      '<summary class="sr-only">Details</summary>' +
      '<p>Google Analytics 4 with IP anonymised. Measurement cookies (<code>_ga</code>, <code>_ga_*</code>) ' +
      'are only set if you accept. You can change your choice at any time from the link in the footer.</p>' +
      '</details>' +
      '<div class="consent-actions">' +
      '<button type="button" class="consent-btn consent-reject">Reject</button>' +
      '<button type="button" class="consent-btn consent-accept">Accept</button>' +
      '</div>';
    document.body.appendChild(w);

    w.querySelector('.consent-more').addEventListener('click', function (e) {
      e.preventDefault();
      var d = w.querySelector('.consent-details');
      d.hidden = !d.hidden;
    });
    w.querySelector('.consent-accept').addEventListener('click', function () {
      applyConsent(true); w.remove();
    });
    w.querySelector('.consent-reject').addEventListener('click', function () {
      applyConsent(false); w.remove();
    });
  }

  function addFooterToggle() {
    var footer = document.querySelector('.footer p') || document.querySelector('.footer');
    if (!footer) return;
    var sep = document.createTextNode(' · ');
    var a = document.createElement('a');
    a.href = '#';
    a.textContent = 'Cookies';
    a.addEventListener('click', function (e) {
      e.preventDefault();
      try { localStorage.removeItem(CONSENT_KEY); } catch (err) {}
      buildBanner();
    });
    footer.appendChild(sep);
    footer.appendChild(a);
  }

  if (!stored) {
    // Show banner on first visit (after DOM is ready — site.js is loaded defer).
    buildBanner();
  }
  addFooterToggle();

  // --- Event instrumentation --------------------------------------------
  var live = document.createElement('p');
  live.className = 'sr-only';
  live.setAttribute('aria-live', 'polite');
  document.body.appendChild(live);

  // Copy BibTeX buttons: data-copy holds the id of the <pre> to copy.
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-copy]');
    if (!b) return;
    var src = document.getElementById(b.getAttribute('data-copy'));
    if (!src || !navigator.clipboard) return;
    navigator.clipboard.writeText(src.textContent).then(function () {
      var old = b.textContent;
      b.textContent = 'Copied';
      live.textContent = 'BibTeX copied to the clipboard.';
      setTimeout(function () { b.textContent = old; }, 1600);
      dlpush('bibtex_copy', { paper_id: b.getAttribute('data-copy').replace(/^bib-pub-/, '') });
    });
  });

  // External profile clicks (ORCID, Scholar, arXiv, GitHub, LinkedIn, DOI).
  var PROFILE_HOSTS = {
    'orcid.org': 'orcid',
    'scholar.google.com': 'google_scholar',
    'arxiv.org': 'arxiv',
    'github.com': 'github',
    'linkedin.com': 'linkedin',
    'doi.org': 'doi',
    'zenodo.org': 'zenodo',
    'hdl.handle.net': 'handle',
    'dblp.org': 'dblp',
    'openalex.org': 'openalex',
    'semanticscholar.org': 'semantic_scholar',
    'wikidata.org': 'wikidata'
  };

  document.addEventListener('click', function (e) {
    var a = e.target.closest('a[href]');
    if (!a) return;
    var href = a.getAttribute('href') || '';

    // Contact (mailto).
    if (href.indexOf('mailto:') === 0) {
      dlpush('contact_click', { method: 'email' });
      return;
    }

    // CV button.
    if (a.id === 'cv-btn') {
      dlpush('cv_download');
      return;
    }

    // External profile.
    if (/^https?:/i.test(href)) {
      var host = domainOf(href);
      var dest = PROFILE_HOSTS[host];
      if (dest) dlpush('external_profile_click', { destination: dest, href: href });
    }
  });

  // Until cv.pdf exists, "Download CV" prints the page (choose "Save as PDF").
  var btn = document.getElementById('cv-btn');
  if (btn && location.protocol !== 'file:') {
    fetch('cv.pdf', { method: 'HEAD' }).then(function (r) { if (!r.ok) throw 0; }).catch(function () {
      btn.removeAttribute('download');
      btn.addEventListener('click', function (e) { e.preventDefault(); window.print(); });
    });
  }
})();
