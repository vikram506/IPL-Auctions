// ============================================================
// Client core: formatting, API helpers, local session
// ============================================================
(function (root) {
  'use strict';

  function fmtLakh(l) {
    if (l == null || isNaN(l)) return '—';
    if (l >= 100) {
      const cr = l / 100;
      return '₹' + (Number.isInteger(cr) ? cr : cr.toFixed(2)) + ' Cr';
    }
    return '₹' + l + ' L';
  }

  function fmtCr(cr) {
    if (cr == null || isNaN(cr)) return '—';
    return '₹' + (Number.isInteger(cr) ? cr : cr.toFixed(2)) + ' Cr';
  }

  async function api(path, body) {
    const opts = body
      ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
      : {};
    const res = await fetch(path, opts);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || ('HTTP ' + res.status));
    return data;
  }

  const Session = {
    set(data) {
      try { localStorage.setItem('iplSession', JSON.stringify(data)); } catch (e) {}
    },
    get() {
      try { return JSON.parse(localStorage.getItem('iplSession')); } catch (e) { return null; }
    },
    clear() {
      try { localStorage.removeItem('iplSession'); } catch (e) {}
    }
  };

  function qs(name) {
    return new URLSearchParams(location.search).get(name);
  }

  root.Core = { fmtLakh, fmtCr, api, Session, qs };
})(window);
