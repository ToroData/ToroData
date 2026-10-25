// Shared behaviour for every page. No dependencies.
(function () {
  'use strict';

  var year = document.getElementById('year');
  if (year) year.textContent = new Date().getFullYear();

  // "Copy BibTeX" buttons: data-copy holds the id of the <pre> to copy.
  var live = document.createElement('p');
  live.className = 'sr-only';
  live.setAttribute('aria-live', 'polite');
  document.body.appendChild(live);
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
    });
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
