/**
 * Selector móvil de operarios libres → asignación de un día (/api/v6/assign).
 */
(function () {
  'use strict';

  var t = window.SP_T || function (k) { return k; };
  var sheet = null;
  var listEl = null;
  var emptyEl = null;
  var searchEl = null;
  var obraNameEl = null;
  var dateLabelEl = null;
  var state = { workers: [], obraId: null, date: null, onSuccess: null };
  var bound = false;

  function esc(s) {
    return String(s || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function formatDateLabel(iso) {
    if (!iso) return '';
    var p = String(iso).split('-');
    if (p.length === 3) return p[2] + '/' + p[1] + '/' + p[0];
    return iso;
  }

  function workersFromKanbanDom() {
    var out = [];
    document.querySelectorAll('#list-libres-body .filterable-worker').forEach(function (el) {
      var id = el.getAttribute('data-worker-id');
      if (!id) return;
      out.push({
        id: id,
        name: el.getAttribute('data-worker-name') || '',
        company: el.getAttribute('data-company-code') || '',
      });
    });
    return out;
  }

  function fetchFreeWorkers(date) {
    return fetch('/api/v6/free_workers?date=' + encodeURIComponent(date), {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    }).then(function (r) {
      if (!r.ok) throw new Error('fetch');
      return r.json();
    }).then(function (data) {
      return (data && data.workers) ? data.workers : [];
    });
  }

  function renderList(filter) {
    if (!listEl || !emptyEl) return;
    var q = (filter || '').trim().toLowerCase();
    var items = state.workers.filter(function (w) {
      if (!q) return true;
      var hay = (w.name + ' ' + (w.company || '')).toLowerCase();
      return hay.indexOf(q) !== -1;
    });

    if (!items.length) {
      listEl.innerHTML = '';
      emptyEl.hidden = false;
      emptyEl.textContent = q
        ? t('Ningún operario libre coincide con la búsqueda.')
        : t('No hay operarios libres este día.');
      return;
    }

    emptyEl.hidden = true;
    listEl.innerHTML = items.map(function (w) {
      var meta = w.company ? esc(w.company) : t('Ext');
      return '<button type="button" class="sp-assign-worker" data-worker-id="' + esc(w.id) + '">' +
        '<span class="sp-assign-worker-name">' + esc(w.name) + '</span>' +
        '<span class="sp-assign-worker-meta">' + meta + '</span>' +
        '</button>';
    }).join('');
  }

  function closeSheet() {
    if (!sheet) return;
    sheet.classList.remove('is-open');
    sheet.setAttribute('hidden', '');
    sheet.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('sp-assign-sheet-open');
    state.workers = [];
    state.obraId = null;
    state.onSuccess = null;
  }

  function openSheet() {
    if (!sheet) return;
    sheet.removeAttribute('hidden');
    sheet.setAttribute('aria-hidden', 'false');
    requestAnimationFrame(function () {
      sheet.classList.add('is-open');
    });
    document.body.classList.add('sp-assign-sheet-open');
    if (searchEl) {
      searchEl.value = '';
      setTimeout(function () { searchEl.focus(); }, 280);
    }
  }

  function assignWorker(workerId) {
    if (!state.obraId || !state.date) return;
    var payload = {
      worker_id: parseInt(workerId, 10),
      target_obra_id: parseInt(state.obraId, 10),
      selected_dates: [state.date],
      overwrite_mode: 'check',
    };

    function send(p) {
      fetch('/api/v6/assign', {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
          'X-CSRFToken': (document.querySelector('meta[name="csrf-token"]') || {}).content || '',
        },
        body: JSON.stringify(p),
      }).then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
        .then(function (res) {
          var data = res.data || {};
          if (data.success) {
            var action = data.action || 'assigned';
            if (action === 'requested') {
              if (window.Swal) {
                Swal.fire({
                  toast: true, position: 'top-end', icon: 'info',
                  title: data.message || t('Solicitud enviada'),
                  showConfirmButton: false, timer: 2200,
                });
              }
              closeSheet();
              return;
            }
            if (window.Swal) {
              Swal.fire({
                toast: true, position: 'top-end', icon: 'success',
                title: t('Asignado'), showConfirmButton: false, timer: 1200,
              });
            }
            closeSheet();
            if (typeof state.onSuccess === 'function') state.onSuccess(payload);
            return;
          }
          if (data.conflict && typeof window.resolverConflictoAsignacion === 'function') {
            window.resolverConflictoAsignacion(data, p, function (np) { send(np); }, function () {});
            return;
          }
          if (window.Swal) {
            Swal.fire(t('Error'), data.error || data.message || t('Error desconocido'), 'error');
          }
        })
        .catch(function () {
          if (window.Swal) Swal.fire(t('Error'), t('Fallo de conexión'), 'error');
        });
    }

    send(payload);
  }

  function ensureDom() {
    sheet = document.getElementById('sp-mobile-assign-sheet');
    if (!sheet) return false;
    listEl = document.getElementById('sp-assign-list');
    emptyEl = document.getElementById('sp-assign-empty');
    searchEl = document.getElementById('sp-assign-search');
    obraNameEl = document.getElementById('sp-assign-obra-name');
    dateLabelEl = document.getElementById('sp-assign-date-label');
    return true;
  }

  function bindOnce() {
    if (bound || !ensureDom()) return;
    bound = true;

    sheet.querySelectorAll('[data-sp-assign-close]').forEach(function (el) {
      el.addEventListener('click', closeSheet);
    });

    if (searchEl) {
      searchEl.addEventListener('input', function () {
        renderList(searchEl.value);
      });
    }

    if (listEl) {
      listEl.addEventListener('click', function (e) {
        var btn = e.target.closest('.sp-assign-worker');
        if (!btn) return;
        assignWorker(btn.getAttribute('data-worker-id'));
      });
    }

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && sheet && sheet.classList.contains('is-open')) closeSheet();
    });
  }

  /**
   * @param {object} opts
   * @param {string|number} opts.obraId
   * @param {string} opts.obraName
   * @param {string} opts.date  YYYY-MM-DD
   * @param {Array} [opts.workers] precargados (tablero)
   * @param {Function} [opts.onSuccess]
   */
  window.spOpenMobileAssignPicker = function (opts) {
    opts = opts || {};
    bindOnce();
    if (!sheet) return;

    state.obraId = opts.obraId;
    state.date = opts.date;
    state.onSuccess = opts.onSuccess || null;

    if (obraNameEl) obraNameEl.textContent = opts.obraName || '';
    if (dateLabelEl) {
      dateLabelEl.textContent = t('Día') + ': ' + formatDateLabel(opts.date);
    }

    function show(workers) {
      state.workers = workers || [];
      renderList('');
      openSheet();
    }

    if (opts.workers && opts.workers.length) {
      show(opts.workers);
      return;
    }

    if (document.getElementById('list-libres-body')) {
      show(workersFromKanbanDom());
      return;
    }

    fetchFreeWorkers(opts.date).then(show).catch(function () {
      if (window.Swal) Swal.fire(t('Error'), t('No se pudo cargar la lista de operarios.'), 'error');
    });
  };

  document.addEventListener('click', function (e) {
    var btn = e.target.closest('.btn-obra-assign-mobile, .pmd-btn-assign');
    if (!btn || btn.disabled) return;

    var obraId = btn.getAttribute('data-obra-id');
    var obraName = btn.getAttribute('data-obra-name') || '';
    if (!obraId) return;

    var date = btn.getAttribute('data-date') || '';
    if (!date) {
      var timeline = document.getElementById('timeline-selected-date');
      var pmd = document.getElementById('pmd-date');
      if (timeline && timeline.value) date = timeline.value;
      else if (pmd && pmd.value) date = pmd.value;
      else if (typeof moment !== 'undefined') date = moment().format('YYYY-MM-DD');
    }

    var onSuccess = null;
    if (btn.classList.contains('btn-obra-assign-mobile')) {
      onSuccess = function () {
        setTimeout(function () { location.reload(); }, 500);
      };
    } else if (btn.classList.contains('pmd-btn-assign')) {
      onSuccess = function () {
        if (typeof window.loadTimelineData === 'function') window.loadTimelineData();
      };
    }

    window.spOpenMobileAssignPicker({
      obraId: obraId,
      obraName: obraName,
      date: date,
      onSuccess: onSuccess,
    });
  });
})();
