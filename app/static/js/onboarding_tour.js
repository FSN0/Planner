/**
 * Guía interactiva SignaPlan — capítulos trabajadores + obra.
 * Estado en sessionStorage; se puede saltar en cualquier momento.
 */
(function (window, document) {
  'use strict';

  var t = window.SP_T || function (key) { return key; };
  var STORAGE_KEY = 'signaplan_tour_v1';
  var PAD = 8;
  var INICIO_CHAIN = ['tablero_leer', 'tablero_asignar', 'obra', 'trabajadores', 'fichaje'];

  function loadState() {
    try {
      return JSON.parse(sessionStorage.getItem(STORAGE_KEY) || 'null');
    } catch (e) {
      return null;
    }
  }

  function saveState(state) {
    if (!state) {
      sessionStorage.removeItem(STORAGE_KEY);
      return;
    }
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  }

  function qs(sel, root) {
    return (root || document).querySelector(sel);
  }

  function pathIs(re) {
    return re.test(window.location.pathname || '');
  }

  function csrfToken() {
    var meta = qs('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
  }

  function setFichaje(activo) {
    if (window.SP_pageLoading) {
      window.SP_pageLoading.show(activo ? t('Activando fichaje…') : t('Guardando…'));
    }
    return fetch('/admin/api/tour/fichaje', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrfToken(),
      },
      body: JSON.stringify({ activo: !!activo }),
      credentials: 'same-origin',
    })
      .then(function (r) { return r.json().catch(function () { return {}; }); })
      .finally(function () {
        // run() puede navegar después; si no, quitamos el overlay
        if (window.SP_pageLoading) window.SP_pageLoading.hide();
      });
  }

  function goFicharProbar(opts) {
    opts = opts || {};
    var chapter = opts.chapter || 'fichaje';
    var oficina = (opts.oficina === 0 || opts.oficina === '0') ? '0' : '1';
    var href = '/admin/tour/fichaje-probar?chapter=' + encodeURIComponent(chapter) +
      '&oficina=' + oficina;
    return setFichaje(true).then(function () {
      window.location.href = href;
    }, function () {
      window.location.href = href;
    });
  }

  function resolveWantFichaje(chapter, opts) {
    opts = opts || {};
    if (opts.wantFichaje === true || opts.wantFichaje === false) {
      return opts.wantFichaje;
    }
    var prev = loadState() || {};
    if (prev.wantFichaje === true || prev.wantFichaje === false) {
      return prev.wantFichaje;
    }
    if (window.__ONB_FICHAJE_ASKED__) {
      return !!window.__ONB_FICHAJE_ACTIVO__;
    }
    if (chapter === 'fichaje') return true;
    return null;
  }

  function hubReturnUrl(chapter) {
    if (isInicioTrack()) {
      return '/admin/obras_detailed';
    }
    var id = chapter ? academiaIdForChapter(chapter) : null;
    if (id && id !== 'seed' && id !== 'import') {
      return '/admin/primeros-pasos?focus=tour&id=' + encodeURIComponent(id);
    }
    if (id === 'seed' || chapter === 'trabajadores' || chapter === 'obra' || chapter === 'fichaje') {
      return '/admin/primeros-pasos?focus=guide&done=seed';
    }
    return '/admin/primeros-pasos?focus=next';
  }

  function isInicioTrack(st) {
    st = st || loadState() || {};
    return st.track === 'inicio';
  }

  function copyTourFields(st, extra) {
    st = st || {};
    var out = {
      active: true,
      track: st.track || null,
      mode: st.mode || 'full',
      fromGuide: !!st.fromGuide,
      returnTo: st.returnTo,
      wantFichaje: st.wantFichaje !== false,
      fromDemo: st.fromDemo != null ? !!st.fromDemo : hasDemoBanner(),
      createdDni: st.createdDni || null,
      createdPin: st.createdPin || null,
      createdObraNombre: st.createdObraNombre || null,
      createdObraId: st.createdObraId || null,
      createdWorkerName: st.createdWorkerName || null,
      chainResume: st.chainResume || null,
      ficharOficina: !!st.ficharOficina,
      assignedOk: !!st.assignedOk,
      welcomeDone: !!st.welcomeDone,
      sawCalendario: !!st.sawCalendario,
      obraCelebrate: !!st.obraCelebrate,
      paused: !!st.paused,
      resumeHref: st.resumeHref || null,
    };
    extra = extra || {};
    Object.keys(extra).forEach(function (k) { out[k] = extra[k]; });
    return out;
  }

  function inicioChapterIndex(chapter) {
    return INICIO_CHAIN.indexOf(chapter);
  }

  function inicioProgressLabel(chapter, extra) {
    var i = inicioChapterIndex(chapter);
    if (i < 0) return extra || '';
    return (i + 1) + '/' + INICIO_CHAIN.length + (extra ? ' · ' + extra : '');
  }

  function inicioHref(chapter) {
    if (chapter === 'tablero_leer' || chapter === 'tablero_asignar' || chapter === 'calendario') {
      return '/admin/obras_detailed';
    }
    if (chapter === 'obra') return '/admin/obras_detailed';
    if (chapter === 'trabajadores') return '/admin/obras_detailed';
    if (chapter === 'fichaje') return '/admin/obras_detailed';
    return '/admin/obras_detailed';
  }

  function inicioAcademiaChapter(st) {
    st = st || loadState() || {};
    var ch = st.chapter || '';
    if (ch === 'calendario') {
      return ((st.step || 0) >= 8) ? 'obra' : 'tablero_asignar';
    }
    return ch;
  }

  function resumeChaptersMatch(requested, stored) {
    if (!requested) return true;
    if (requested === stored) return true;
    if (stored === 'calendario' && requested === 'tablero_asignar') return true;
    if (stored === 'tablero_asignar' && requested === 'calendario') return true;
    return false;
  }

  function normalizePausedTourState(st) {
    st = st || {};
    var path = window.location.pathname || '';
    var ch = st.chapter || '';
    if (ch === 'calendario' && (st.step || 0) >= 8) {
      st.chapter = 'obra';
      st.step = 0;
      ch = 'obra';
    } else if (ch === 'calendario') {
      st.step = 0;
    }
    if (ch === 'obra' && /create_obra|import_obras/.test(path)) {
      st.chapter = 'obra';
      st.step = 0;
    }
    if (ch === 'trabajadores' && /create_user|import_users/.test(path)) {
      st.chapter = 'trabajadores';
      st.step = 0;
    }
    return st;
  }

  function pauseResumeHref(st, fromMi) {
    st = st || {};
    var ch = st.chapter || '';
    if (fromMi) {
      var chMi = ch === 'fichajes' ? 'fichajes' : 'fichaje';
      return '/admin/tour/fichaje-probar?chapter=' + encodeURIComponent(chMi) +
        (chMi === 'fichaje' ? '&oficina=0' : '');
    }
    if (ch === 'obra' || ch === 'trabajadores' || ch === 'tablero_leer' ||
        ch === 'tablero_asignar' || ch === 'calendario') {
      return '/admin/obras_detailed';
    }
    return (window.location.pathname || '') + (window.location.search || '');
  }

  function hereIsInicioChapter(next) {
    var here = window.location.pathname || '';
    if (next === 'tablero_leer' || next === 'tablero_asignar' || next === 'calendario' || next === 'fichaje') {
      return /obras_detailed/.test(here);
    }
    if (next === 'obra') {
      return /\/admin\/create_obra|\/admin\/import_obras/.test(here) ||
        (/\/admin\/obras(\/|$)/.test(here) && !/obras_detailed/.test(here));
    }
    if (next === 'trabajadores') {
      return /\/admin\/personal|\/admin\/create_user|\/admin\/import_users/.test(here);
    }
    return false;
  }

  function goToInicioChapter(next, st, opts) {
    opts = opts || {};
    st = st || loadState() || {};
    var i = inicioChapterIndex(next);
    if (i > 0) {
      markAcademiaDoneMany(INICIO_CHAIN.slice(0, i));
    }
    if (next) postTourStart(academiaIdForChapter(next) || next);
    saveState(copyTourFields(st, { chapter: next, step: 0, pendingComplete: false, active: true }));
    // Obras y trabajadores: el usuario pulsa el menú; no redirigimos.
    var stay = opts.stay === true || next === 'obra' || next === 'trabajadores';
    if (stay || hereIsInicioChapter(next)) {
      run();
      return;
    }
    var href = inicioHref(next);
    window.location.href = href + (href.indexOf('?') >= 0 ? '&' : '?') + 'tour=' + encodeURIComponent(next);
  }

  function purgeTourFichaje(done) {
    var st = loadState() || {};
    var dni = (st.createdDni || '').trim();
    if (!dni) {
      if (done) done();
      return;
    }
    fetch('/admin/api/tour/fichaje-demo', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrfToken(),
      },
      credentials: 'same-origin',
      keepalive: true,
      body: JSON.stringify({ dni: dni }),
    })
      .catch(function () { /* ignore */ })
      .finally(function () { if (done) done(); });
  }

  function calendarWorkerSelected() {
    var sel = qs('#assignmentModal.show .univ-worker-select');
    return !!(sel && String(sel.value || '').trim());
  }

  function calendarVehicleToggleOn() {
    var tog = qs('#assignmentModal.show .univ-vehicle-toggle');
    return !!(tog && tog.checked);
  }

  function calendarVehicleSelected() {
    var tog = qs('#assignmentModal.show .univ-vehicle-toggle');
    var sel = qs('#assignmentModal.show .univ-vehicle-select');
    return !!(tog && tog.checked && sel && String(sel.value || '').trim());
  }

  function calendarGhostPresent() {
    return !!(qs('#assignmentModal.show .fc-ghost-event') || qs('.fc-ghost-event'));
  }

  function assignmentConflictOpen() {
    try {
      if (typeof Swal === 'undefined' || !Swal.isVisible()) return false;
      var titleEl = Swal.getTitle && Swal.getTitle();
      var title = (titleEl && (titleEl.textContent || titleEl.innerText)) || '';
      var html = '';
      try {
        var box = Swal.getHtmlContainer && Swal.getHtmlContainer();
        html = box ? (box.textContent || '') : '';
      } catch (e2) { /* ignore */ }
      return /conflicto/i.test(title + ' ' + html);
    } catch (e) {
      return false;
    }
  }

  function wrapAssignmentConflictForTour() {
    var orig = window.resolverConflictoAsignacion;
    if (typeof orig !== 'function' || orig.__spTourWrapped) return;
    window.resolverConflictoAsignacion = function (data, payload, onRetry, onCancel) {
      var st = loadState();
      if (st && st.active && (st.chapter === 'calendario' || st.chapter === 'tablero_asignar')) {
        if (ui.card) ui.card.style.display = 'none';
        if (ui.backdrop) ui.backdrop.style.display = 'none';
        try { placeHole(null); } catch (eHide) { /* ignore */ }
        var tipo = (data && (data.conflict_type || data.conflict_type)) || '';
        var esAusencia = tipo === 'leave' || tipo === 'leave'
          || !!(data && Array.isArray(data.leave_dates) && data.leave_dates.length);
        // Ausencia: el modal ya dice Entendido / gestiona la baja. No mezclar con pluriempleo.
        if (!esAusencia) {
          var hint = '<p class="sp-tour-conflict-hint">' +
            t('Esta persona ya está en otra obra en parte de esas fechas.') + ' ' +
            t('<strong>Sobrescribir</strong>: la saca de la otra obra.') + ' ' +
            t('<strong>Pluriempleo</strong>: queda en las dos.') + ' ' +
            t('<strong>Asignar solo días libres</strong>: lo habitual aquí; solo pone los días que no pisa.') + ' ' +
            t('<strong>Cancelar</strong>: no cambia nada.') +
            '</p>';
          data = Object.assign({}, data || {}, {
            message: hint + ((data && data.message) || ''),
          });
        }
      }
      return orig.call(this, data, payload, onRetry, onCancel);
    };
    window.resolverConflictoAsignacion.__spTourWrapped = true;
  }

  function advanceInicioChain() {
    var st = loadState() || {};
    var chapter = st.chapter || '';
    markAcademiaDone(chapter);
    var i = inicioChapterIndex(chapter);
    if (i < 0 || i >= INICIO_CHAIN.length - 1) {
      finishInicioTrack();
      return;
    }
    goToInicioChapter(INICIO_CHAIN[i + 1], st);
  }

  function finishInicioTrack() {
    var done = false;
    function go() {
      if (done) return;
      done = true;
      teardown();
      saveState(null);
      try {
        sessionStorage.setItem(
          'signaplan_tour_flash',
          t('Recorrido inicial listo. El tablero sigue con los ejemplos; quítalos cuando quieras.')
        );
      } catch (e) { /* ignore */ }
      postOnboardingDone();
    }
    purgeTourFichaje(function () {
      markAcademiaDoneMany([
        'seed', 'tablero_leer', 'tablero_asignar', 'obra', 'trabajadores', 'fichaje',
      ]).then(go, go);
      setTimeout(go, 2500);
    });
  }

  function startCalendarioFromBoard() {
    var st = loadState() || {};
    if (st.chapter === 'calendario' && (st.step || 0) >= 1 && assignmentModalOpen()) {
      run();
      return;
    }
    var resume = st.chainResume || { chapter: st.chapter || 'tablero_asignar', step: st.step || 0 };
    saveState(copyTourFields(st, {
      chapter: 'calendario',
      step: 1,
      chainResume: resume,
      active: true,
    }));
    if (assignmentModalOpen()) run();
  }

  function usesOwnObraFichaje(st) {
    st = st || loadState() || {};
    if ((st.chapter || '') === 'fichajes') return false;
    if (isInicioTrack(st)) return true;
    if (st.ficharOficina === false) return true;
    return (st.chapter || '') === 'fichaje';
  }

  function assignmentModalOpen() {
    var modal = qs('#assignmentModal');
    if (!modal) return false;
    if (modal.classList.contains('show') || modal.classList.contains('in')) return true;
    if (modal.getAttribute('aria-hidden') === 'false') return true;
    try {
      var style = window.getComputedStyle ? window.getComputedStyle(modal) : null;
      if (style && style.display === 'block') return true;
    } catch (e) { /* ignore */ }
    try {
      if (window.jQuery && window.jQuery(modal).hasClass('show')) return true;
    } catch (e2) { /* ignore */ }
    return false;
  }

  function postTourStart(id) {
    if (!id) return Promise.resolve(false);
    var meta = document.querySelector('meta[name="csrf-token"]');
    var token = meta ? meta.getAttribute('content') : '';
    return fetch('/admin/api/tour/' + encodeURIComponent(id) + '/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': token },
      credentials: 'same-origin',
      keepalive: true,
      body: '{}',
    }).then(function (r) {
      return !!(r && r.ok);
    }).catch(function () {
      return false;
    });
  }

  function academiaResumeUrl(chapter) {
    var id = academiaIdForChapter(chapter);
    var q = '/admin/primeros-pasos?focus=resume';
    if (id) q += '&id=' + encodeURIComponent(id);
    return q;
  }

  function pauseTourToAcademia(message) {
    var st = normalizePausedTourState(loadState() || {});
    var chapter = st.chapter || '';
    if (chapter === 'blocked') chapter = '';
    var mapped = inicioAcademiaChapter(st);
    var id = academiaIdForChapter(mapped) || academiaIdForChapter(chapter);
    var idx = inicioChapterIndex(mapped);
    var prior = idx > 0 ? INICIO_CHAIN.slice(0, idx) : [];
    var dest = academiaResumeUrl(mapped || chapter);
    var fromMi = isMiEntrar() || isMiFichar();

    st.active = false;
    st.paused = true;
    st.resumeHref = pauseResumeHref(st, fromMi);
    saveState(st);
    teardown();

    function go() {
      try {
        sessionStorage.setItem(
          'signaplan_tour_flash',
          t(message || 'Tutorial en pausa. En la Academia ves en cuál te quedaste y puedes continuar.')
        );
      } catch (e) { /* ignore */ }
      if (fromMi) {
        window.location.href = '/auth/tour-volver-admin?next=' + encodeURIComponent(dest);
        return;
      }
      window.location.href = dest;
    }

    var pending = [];
    if (prior.length) pending.push(markAcademiaDoneMany(prior));
    if (id) pending.push(postTourStart(id));
    if (!pending.length) {
      go();
      return;
    }
    var done = false;
    function once() {
      if (done) return;
      done = true;
      go();
    }
    Promise.all(pending).then(once, once);
    setTimeout(once, 2500);
  }

  function tryResumePaused(chapter) {
    var st = loadState() || {};
    if (!st.paused || !st.chapter) return false;
    if (!resumeChaptersMatch(chapter, st.chapter)) return false;
    st.active = true;
    st.paused = false;
    saveState(st);
    var href = st.resumeHref || '';
    var here = (window.location.pathname || '') + (window.location.search || '');
    if (href && href !== here) {
      window.location.href = href;
      return true;
    }
    document.body.classList.add('sp-tour-active');
    run();
    return true;
  }

  function skipEntireInicio() {
    pauseTourToAcademia();
  }

  function onSkipEntire() {
    var st = loadState() || {};
    if ((st.chapter || '') === 'import') {
      stopTour({});
      return;
    }
    pauseTourToAcademia();
  }

  function resumeAfterCalendario() {
    var st = loadState() || {};
    st.sawCalendario = true;
    st.assignedOk = true;
    if (isInicioTrack(st)) {
      goToInicioChapter('obra', st, { stay: true });
      return;
    }
    var resume = st.chainResume;
    if (resume && resume.chapter) {
      saveState(copyTourFields(st, {
        chapter: resume.chapter,
        step: typeof resume.step === 'number' ? resume.step : 0,
        chainResume: null,
        assignedOk: true,
        sawCalendario: true,
        active: true,
      }));
      run();
      return;
    }
    finishSoloAndReturn('Calendario de la obra visto. Forma parte de Asignar en el tablero.');
  }

  function goHubAfterGuide(message) {
    teardown();
    saveState(null);
    try {
      sessionStorage.setItem(
        'signaplan_tour_flash',
        t(message || 'Tutorial guiado completado. Abajo ya puedes ver el resto de guías.')
      );
    } catch (e) { /* ignore */ }
    window.location.href = '/admin/primeros-pasos?focus=guide&done=seed';
  }

  function finishGuideToHub(message) {
    // Esperar al POST: si redirigimos al momento, el navegador cancela el fetch
    // y el tic de «Tutorial guiado» no se guarda. Tope 2.5s por si la red falla.
    var done = false;
    function go() {
      if (done) return;
      done = true;
      goHubAfterGuide(message);
    }
    markAcademiaDone('seed').then(go, go);
    setTimeout(go, 2500);
  }

  function finishSoloAndReturn(message) {
    var st = loadState() || {};
    var chapter = st.chapter || '';
    var href = st.returnTo || hubReturnUrl(chapter);
    var done = false;
    function go() {
      if (done) return;
      done = true;
      teardown();
      saveState(null);
      if (message) {
        try {
          sessionStorage.setItem('signaplan_tour_flash', t(message));
        } catch (e) { /* ignore */ }
      }
      window.location.href = href;
    }
    markAcademiaDone(chapter).then(go, go);
    setTimeout(go, 2500);
  }

  function ensureTourTargetVisible(selector) {
    if (!selector) return null;
    var el = qs(selector);
    if (!el) return null;
    var li = el.closest('li');
    if (li && li.classList.contains('is-nav-hidden')) {
      li.classList.remove('is-nav-hidden');
      li.setAttribute('data-tour-forced-visible', '1');
    }
    var section = el.closest('.sidebar-section');
    if (section) {
      section.classList.remove('is-section-all-hidden');
      section.setAttribute('data-tour-forced-visible', '1');
    }
    var group = el.closest('.sidebar-nav-group');
    if (group) group.classList.add('is-open');
    document.documentElement.classList.remove('sidebar-collapsed');
    return el;
  }

  var NAV_FALLBACK_HREF = {
    '[data-tour="nav-tablero"], a[href*="obras_detailed"]': '/admin/obras_detailed',
    '[data-tour="nav-tablero"]': '/admin/obras_detailed',
    '[data-tour="nav-trabajadores"]': '/admin/personal',
    '[data-tour="nav-directorio"]': '/admin/obras',
    '[data-tour="nav-empresas"]': '/admin/companies',
    '[data-tour="nav-vehiculos"]': '/admin/vehiculos',
    '[data-tour="nav-coches-libres"]': '/admin/vehiculos/libres',
    '[data-tour="nav-auditoria-fichajes"]': '/sync/auditoria',
  };

  function hasDemoBanner() {
    try {
      return !!document.querySelector('[data-demo-banner]');
    } catch (e) {
      return false;
    }
  }

  function tourFromDemo() {
    var st = loadState() || {};
    if (st.fromDemo != null) return !!st.fromDemo;
    return hasDemoBanner();
  }

  function isSeedGuideState(st) {
    st = st || loadState() || {};
    if (isInicioTrack(st)) return false;
    if (st.fromGuide) return true;
    var ch = st.chapter || '';
    var step = st.step || 0;
    // Recuperar guía rota si alguien metió mode=solo en la URL a mitad del fichaje
    if (st.mode === 'solo') {
      if (st.track) return false;
      if (ch === 'fichaje' && step >= 7) return true;
      if (ch === 'obra' && step >= 5) return true;
      if (ch === 'flota' && st.fleetAsked) return true;
      return false;
    }
    return ch === 'trabajadores' || ch === 'obra' || ch === 'fichaje' ||
      (ch === 'flota' && !!st.fleetAsked);
  }

  function startTour(chapter, opts) {
    opts = opts || {};
    var prev = loadState() || {};
    var ch = chapter || 'tablero_leer';
    var track = opts.track;
    if (track == null && prev.track === 'inicio' && INICIO_CHAIN.indexOf(ch) >= 0 &&
        opts.mode !== 'solo') {
      track = 'inicio';
    }
    if (track === 'inicio') {
      opts.wantFichaje = true;
      opts.fromGuide = false;
      opts.mode = opts.mode || 'full';
    }
    var want = resolveWantFichaje(ch, opts);
    var mode = opts.mode || 'full';
    var fromGuide = !!opts.fromGuide;
    if (!fromGuide && mode !== 'solo' && track !== 'inicio' &&
        (ch === 'trabajadores' || ch === 'obra' || ch === 'fichaje')) {
      fromGuide = true;
    }
    var keep = !!opts.keepCreds || track === 'inicio' || ch === 'fichaje' || ch === 'calendario';
    var ficharOficina = opts.ficharOficina;
    if (ficharOficina == null) {
      if (ch === 'fichaje' || track === 'inicio') ficharOficina = false;
      else ficharOficina = !!prev.ficharOficina;
    }
    saveState(copyTourFields(prev, {
      active: true,
      paused: false,
      resumeHref: null,
      chapter: ch,
      step: typeof opts.step === 'number' ? opts.step : 0,
      mode: mode,
      track: track || null,
      fromGuide: fromGuide,
      returnTo: opts.returnTo || hubReturnUrl(ch),
      createdDni: keep ? (prev.createdDni || null) : null,
      createdPin: keep ? (prev.createdPin || null) : null,
      createdObraNombre: keep ? (prev.createdObraNombre || null) : null,
      createdObraId: keep ? (prev.createdObraId || null) : null,
      createdWorkerName: keep ? (prev.createdWorkerName || null) : null,
      wantFichaje: want,
      fromDemo: opts.fromDemo != null ? !!opts.fromDemo : hasDemoBanner(),
      fleetAsked: !!opts.fleetAsked,
      fleetDecided: !!opts.fleetDecided,
      ficharOficina: !!ficharOficina,
      chainResume: opts.chainResume || (ch === 'calendario' ? prev.chainResume : null),
      assignedOk: !!prev.assignedOk,
      welcomeDone: opts.resetWelcome ? false : (ch === 'tablero_leer' ? !!prev.welcomeDone : false),
    }));
    document.body.classList.add('sp-tour-active');
    if (ch === 'demo') {
      saveState(null);
      return;
    }
    run();
  }

  function postOnboardingDone(redirectHref) {
    var form = document.createElement('form');
    form.method = 'POST';
    form.action = '/admin/primeros-pasos';
    form.style.display = 'none';
    var csrf = document.querySelector('meta[name="csrf-token"]');
    var token = csrf ? csrf.getAttribute('content') : '';
    [['csrf_token', token], ['accion', 'listo']].forEach(function (pair) {
      var inp = document.createElement('input');
      inp.type = 'hidden';
      inp.name = pair[0];
      inp.value = pair[1] || '';
      form.appendChild(inp);
    });
    document.body.appendChild(form);
    if (redirectHref) {
      // listo ya redirige al tablero; ignoramos redirectHref extra
    }
    form.submit();
  }

  function stopTour(opts) {
    opts = opts || {};
    teardown();
    saveState(null);
    if (opts.message) showDoneCard(opts.message);
  }

  function askFleetOrPause() {
    var st = loadState() || {};
    // Solo los tutoriales cortos sueltos del hub saltan la pregunta de flota
    if (st.mode === 'solo' && !isSeedGuideState(st)) {
      finishSoloAndReturn();
      return;
    }
    if (st.fleetDecided) {
      finishGuideToHub();
      return;
    }
    if (st.fleetPromptOpen) {
      // Reponer el modal si se perdió al navegar
      st.fleetPromptOpen = false;
      saveState(st);
    }

    st.fleetPromptOpen = true;
    st.pendingComplete = false;
    st.fromGuide = true;
    st.mode = 'full';
    saveState(st);
    ensureUi();
    clearTargets();
    placeHole(null);
    ui.card.classList.add('is-modal');
    ui.card.style.transform = 'translateX(-50%)';
    ui.card.style.top = '28%';
    ui.card.style.left = '50%';
    ui.card.style.zIndex = '20050';
    ui.card.style.display = '';
    ui.card.innerHTML =
      '<div class="sp-tour-progress">' + t('Tutorial guiado · flota') + '</div>' +
      '<h3>' + t('¿Vais a usar vehículos?') + '</h3>' +
      '<p>' + t('Si sí, te enseñamos a dar de alta el primero. Si no, damos el tutorial guiado por terminado y volvemos a Primeros pasos.') + '</p>' +
      '<div class="sp-tour-actions" style="flex-direction:column;align-items:stretch;">' +
      '<button type="button" class="sp-tour-primary" data-act="fleet-yes">' + t('Sí, crear un vehículo') + '</button>' +
      '<button type="button" class="sp-tour-ghost" data-act="fleet-no">' + t('No, terminar tutorial') + '</button>' +
      '</div>';
    ui.card.querySelector('[data-act="fleet-yes"]').onclick = function () {
      var prev = loadState() || {};
      saveState({
        active: true,
        chapter: 'flota',
        step: 0,
        mode: 'full',
        fromGuide: true,
        fleetAsked: true,
        fleetDecided: true,
        fleetPromptOpen: false,
        returnTo: '/admin/primeros-pasos?focus=guide&done=seed',
        wantFichaje: prev.wantFichaje,
        fromDemo: prev.fromDemo,
        createdDni: prev.createdDni,
        createdObraNombre: prev.createdObraNombre,
      });
      document.body.classList.add('sp-tour-active');
      run();
    };
    ui.card.querySelector('[data-act="fleet-no"]').onclick = function () {
      var prev = loadState() || {};
      prev.fleetDecided = true;
      prev.fleetPromptOpen = false;
      prev.fleetAsked = true;
      prev.fromGuide = true;
      saveState(prev);
      finishGuideToHub(
        'Tutorial guiado completado. Abajo verás el resto de guías cuando tengas material.'
      );
    };
  }

  function pauseAtChapterEnd() {
    var state = loadState();
    if (!state) return;
    var chapter = state.chapter || '';
    var didFichaje = !!state.wantFichaje;
    var mode = state.mode || 'full';
    var returnTo = state.returnTo || hubReturnUrl(chapter);

    if (chapter === 'calendario') {
      resumeAfterCalendario();
      return;
    }

    if (isInicioTrack(state)) {
      advanceInicioChain();
      return;
    }

    var seedChapters = chapter === 'trabajadores' || chapter === 'obra' || chapter === 'fichaje' ||
      (chapter === 'flota' && !!state.fleetAsked);
    var seedGuide = isSeedGuideState(state) || (seedChapters && mode !== 'solo');

    // Paso suelto del hub (Repetir este paso): volver sin pregunta de flota
    if (mode === 'solo' && !state.fromGuide && !state.fleetAsked && !isSeedGuideState(state)) {
      markAcademiaDone(chapter);
      finishSoloAndReturn();
      return;
    }

    // Fin del recorrido guiado: SIEMPRE preguntar flota / volver al hub
    if (seedGuide || seedChapters) {
      if (!state.fleetDecided && chapter !== 'flota') {
        askFleetOrPause();
        return;
      }
      if (chapter === 'flota') {
        markAcademiaDone('flota');
      }
      finishGuideToHub(
        chapter === 'flota'
          ? 'Vehículo creado. Tutorial guiado completado.'
          : (didFichaje
            ? 'Tutorial guiado completado (persona, obra y fichaje). Abajo tienes el resto de guías.'
            : 'Tutorial guiado completado (persona y obra). Abajo tienes el resto de guías.')
      );
      return;
    }

    state.active = false;
    state.chapter = 'blocked';
    state.step = 0;
    state.pendingComplete = false;
    state.createdPin = null;
    saveState(state);
    teardown();

    markAcademiaDone(chapter);

    if (chapter === 'import') {
      ensureUi();
      clearTargets();
      placeHole(null);
      ui.card.classList.add('is-modal');
      ui.card.style.transform = 'translateX(-50%)';
      ui.card.style.top = '28%';
      ui.card.style.left = '50%';
      var msg = 'Importación guiada lista. Puedes seguir importando más listados o abrir la Academia.';
      ui.card.innerHTML =
        '<h3>' + t('Guía terminada') + '</h3><p>' + t(msg) + '</p>' +
        '<div class="sp-tour-actions">' +
        '<button type="button" class="sp-tour-skip" data-act="hub">' + t('Ir a Academia') + '</button>' +
        '<button type="button" class="sp-tour-primary" data-act="done">' + t('Ir al tablero') + '</button></div>';
      ui.card.querySelector('[data-act="hub"]').onclick = function () {
        teardown();
        window.location.href = hubReturnUrl(chapter);
      };
      ui.card.querySelector('[data-act="done"]').onclick = function () {
        postOnboardingDone();
      };
      return;
    }

    if (isAcademiaChapter(chapter)) {
      if (mode === 'solo') {
        saveState(null);
        try {
          sessionStorage.setItem(
            'signaplan_tour_flash',
            t('Tutorial completado. Lo siguiente está justo debajo.')
          );
        } catch (e) { /* ignore */ }
        window.location.href = returnTo || hubReturnUrl(chapter);
        return;
      }
      showDoneCard(
        'Tutorial completado. Puedes repetirlo o seguir con el siguiente desde la Academia.'
      );
      return;
    }

    showDoneCard(
      didFichaje
        ? 'Guía completada: alta, obra, fichaje de prueba y cómo resolver la pelota roja en auditoría. Sigue en la Academia.'
        : 'Hasta aquí la guía por ahora. Ya tienes trabajador y obra. Más adelante puedes activar fichaje en Configuración. Sigue en la Academia.'
    );
  }

  function isAcademiaChapter(ch) {
    return [
      'tablero_leer', 'tablero_asignar', 'calendario',
      'tablero_basico', 'planificador_multi', 'fichajes',
      'auditoria_fichajes', 'registro_jornada',
      'flota', 'coches_libres', 'auditoria_vehiculos',
    ].indexOf(ch) >= 0;
  }

  function academiaIdForChapter(ch) {
    if (ch === 'calendario') return 'tablero_asignar';
    if (ch === 'tablero_leer' || ch === 'tablero_asignar' ||
        ch === 'obra' || ch === 'trabajadores' || ch === 'fichaje' ||
        ch === 'seed' || ch === 'demo') {
      return ch;
    }
    if (ch === 'import') return 'import';
    if (ch === 'auditoria_fichajes' || ch === 'registro_jornada') return 'fichajes';
    if (isAcademiaChapter(ch)) return ch;
    return null;
  }

  function markAcademiaDone(chapter) {
    var id = academiaIdForChapter(chapter);
    if (!id) return Promise.resolve(false);
    return markAcademiaDoneMany([id]);
  }

  function markAcademiaDoneMany(ids) {
    var list = (ids || []).map(function (ch) {
      return academiaIdForChapter(ch) || ch;
    }).filter(Boolean);
    if (!list.length) return Promise.resolve(false);
    var meta = document.querySelector('meta[name="csrf-token"]');
    var token = meta ? meta.getAttribute('content') : '';
    return fetch('/admin/api/tour/complete-many', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': token },
      credentials: 'same-origin',
      keepalive: true,
      body: JSON.stringify({ ids: list }),
    }).then(function (r) {
      return !!(r && r.ok);
    }).catch(function () {
      return false;
    });
  }

  function sectionSkipLabel(chapter) {
    if (chapter === 'calendario') return t('Cerrar calendario →');
    if (chapter === 'tablero_leer' || chapter === 'tablero_asignar') return t('Saltar este capítulo →');
    if (chapter === 'trabajadores') return t('Saltar plantilla →');
    if (chapter === 'obra') return t('Saltar obras →');
    if (chapter === 'fichaje') return t('Saltar fichaje →');
    if (chapter === 'import') return t('Saltar importación →');
    if (isAcademiaChapter(chapter)) return t('Saltar tutorial →');
    return t('Saltar sección →');
  }

  /**
   * Salta el capítulo actual entero (plantilla / obras / fichaje).
   * Útil si ya lo tienes hecho o para probar tramos posteriores.
   */
  function skipSection() {
    var st = loadState();
    if (!st || !st.active) return;

    var chapter = st.chapter || 'trabajadores';

    if (chapter === 'calendario') {
      resumeAfterCalendario();
      return;
    }

    if (isInicioTrack(st)) {
      var iSkip = inicioChapterIndex(chapter);
      if (iSkip < 0 || iSkip >= INICIO_CHAIN.length - 1) {
        pauseTourToAcademia();
        return;
      }
      advanceInicioChain();
      return;
    }

    if (chapter === 'tablero_leer' || chapter === 'tablero_asignar') {
      pauseAtChapterEnd();
      return;
    }

    if (chapter === 'trabajadores') {
      saveState({
        active: true,
        chapter: 'obra',
        step: 0,
        wantFichaje: st.wantFichaje,
        createdDni: st.createdDni,
        createdPin: st.createdPin,
        createdObraNombre: st.createdObraNombre,
        createdWorkerName: st.createdWorkerName,
      });
      // Si estamos en una pantalla de alta/import, volver a un sitio cómodo
      if (pathIs(/\/admin\/create_user/) || pathIs(/\/admin\/import_users/) || pathIs(/\/admin\/personal/)) {
        window.location.href = '/admin/obras';
        return;
      }
      run();
      return;
    }

    if (chapter === 'obra') {
      if (st.wantFichaje) {
        saveState({
          active: true,
          chapter: 'fichaje',
          step: 0,
          wantFichaje: true,
          createdDni: st.createdDni,
          createdPin: st.createdPin,
          createdObraNombre: st.createdObraNombre,
          createdWorkerName: st.createdWorkerName,
        });
        if (pathIs(/\/admin\/create_obra/) || pathIs(/\/admin\/import_obras/)) {
          window.location.href = '/admin/obras_detailed';
          return;
        }
        run();
        return;
      }
      pauseAtChapterEnd();
      return;
    }

    if (chapter === 'fichaje') {
      pauseTourToAcademia();
      return;
    }

    if (chapter === 'import') {
      // Salir limpio: sin cartel encima ni pantalla a oscuras
      stopTour({});
      return;
    }

    if (isAcademiaChapter(chapter)) {
      pauseTourToAcademia();
      return;
    }

    pauseAtChapterEnd();
  }

  var ui = { backdrop: null, hole: null, card: null, banner: null };
  var holeTrack = { el: null, els: null, opts: null, cardEl: null, cardPlace: null };

  function teardown() {
    document.body.classList.remove('sp-tour-active');
    document.querySelectorAll('.sp-tour-target').forEach(function (el) {
      el.classList.remove('sp-tour-target');
    });
    hideTourBanner();
    unbindHoleReposition();
    holeTrack.el = holeTrack.els = holeTrack.opts = holeTrack.cardEl = null;
    if (ui.backdrop) ui.backdrop.remove();
    if (ui.card) ui.card.remove();
    ui.backdrop = ui.hole = ui.card = null;
  }

  function ensureUi() {
    if (ui.backdrop) return;
    document.body.classList.add('sp-tour-active');
    ui.backdrop = document.createElement('div');
    ui.backdrop.className = 'sp-tour-backdrop';
    ui.hole = document.createElement('div');
    ui.hole.className = 'sp-tour-hole';
    ui.backdrop.appendChild(ui.hole);
    document.body.appendChild(ui.backdrop);
    ui.card = document.createElement('div');
    ui.card.className = 'sp-tour-card';
    document.body.appendChild(ui.card);
    bindHoleReposition();
  }

  function bindHoleReposition() {
    if (window.__spTourHoleBound) return;
    window.__spTourHoleBound = true;
    var ticking = false;
    function refresh() {
      ticking = false;
      if (!ui.hole || !document.body.classList.contains('sp-tour-active')) return;
      if (holeTrack.els && holeTrack.els.length) {
        placeHoleUnion(holeTrack.els, holeTrack.opts || {}, true);
      } else if (holeTrack.el && holeTrack.el.getBoundingClientRect) {
        placeHole(holeTrack.el, true);
      }
      repositionTourCard();
    }
    function onScrollOrResize() {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(refresh);
    }
    window.__spTourHoleRefresh = onScrollOrResize;
    window.addEventListener('scroll', onScrollOrResize, true);
    window.addEventListener('resize', onScrollOrResize, { passive: true });
  }

  function unbindHoleReposition() {
    if (!window.__spTourHoleBound) return;
    window.__spTourHoleBound = false;
    if (window.__spTourHoleRefresh) {
      window.removeEventListener('scroll', window.__spTourHoleRefresh, true);
      window.removeEventListener('resize', window.__spTourHoleRefresh);
      window.__spTourHoleRefresh = null;
    }
  }

  function placeHole(el, fromTrack) {
    if (!ui.hole) return;
    if (!fromTrack) {
      if (el && el.getBoundingClientRect) {
        holeTrack.el = el;
        holeTrack.els = null;
        holeTrack.opts = null;
      } else {
        // null o rect crudo: no reanclar en scroll/resize
        holeTrack.el = holeTrack.els = holeTrack.opts = null;
      }
    }
    var r = null;
    if (el) {
      if (el.getBoundingClientRect) r = _visibleRect(el);
      else if (el.width >= 8 && el.height >= 8) r = el;
    }
    if (!r) {
      // Nunca dejar un agujero 0×0 en (0,0): se ve como círculo en la esquina.
      ui.hole.classList.add('is-hidden');
      ui.hole.style.top = '0';
      ui.hole.style.left = '0';
      ui.hole.style.width = '0';
      ui.hole.style.height = '0';
      return;
    }
    ui.hole.classList.remove('is-hidden');
    ui.hole.style.top = Math.max(0, r.top - PAD) + 'px';
    ui.hole.style.left = Math.max(0, r.left - PAD) + 'px';
    ui.hole.style.width = Math.max(0, r.width + PAD * 2) + 'px';
    ui.hole.style.height = Math.max(0, r.height + PAD * 2) + 'px';
  }

  /** Quita el gris del overlay (agujero a pantalla completa) para poder arrastrar viendo el desktop. */
  function revealTourDesktop() {
    placeHole({
      top: 0,
      left: 0,
      width: window.innerWidth || 1200,
      height: window.innerHeight || 800,
    });
  }

  /** Zona del planificador donde el doble clic crea bloques (centro, sin eje de obras). */
  function planifClickableGridEl() {
    return qs('#planificador-calendar .vis-panel.vis-center') ||
      qs('.vis-timeline .vis-panel.vis-center') ||
      qs('#planificador-calendar [data-tour="planif-grid"]') ||
      qs('#planificador-calendar');
  }

  /**
   * Zoom horizontal de toda la franja del timeline a la altura de la barra
   * (para poder coger el borde izq/dcho sin que el overlay tape el arrastre).
   */
  function placeHolePlanifItemStrip(el) {
    if (!el) {
      placeHole(planifClickableGridEl() || qs('#planificador-calendar'));
      return;
    }
    var center = planifClickableGridEl();
    var ir = el.getBoundingClientRect();
    var cr = center ? center.getBoundingClientRect() : ir;
    var padY = 14;
    var top = Math.max(cr.top, ir.top - padY);
    var bottom = Math.min(cr.bottom || (ir.top + ir.height + padY), ir.bottom + padY);
    var height = Math.max(bottom - top, Math.max(ir.height + padY * 2, 40));
    placeHole({
      top: top,
      left: cr.left,
      width: Math.max(cr.width, ir.width + 48),
      height: height,
    });
  }

  function findPlanifFeedbackToast() {
    return qs('.swal2-container.swal2-top .swal2-toast') ||
      qs('.swal2-container .swal2-toast') ||
      qs('.swal2-toast') ||
      qs('.toast.show') ||
      qs('.alert-success, .alert-info');
  }

  /** Agujero que cubre la unión de varios nodos (p. ej. chip + columna obra). */
  function placeHoleUnion(els, opts, fromTrack) {
    if (!ui.hole) return;
    opts = opts || {};
    if (!fromTrack) {
      holeTrack.els = (els || []).filter(Boolean);
      holeTrack.el = null;
      holeTrack.opts = opts;
    }
    var rects = [];
    (els || []).forEach(function (el) {
      var r = el && el.getBoundingClientRect ? _visibleRect(el) : null;
      if (r) rects.push(r);
    });
    if (!rects.length) {
      placeHole(null, true);
      return;
    }
    var top = Math.min.apply(null, rects.map(function (r) { return r.top; }));
    var left = Math.min.apply(null, rects.map(function (r) { return r.left; }));
    var right = Math.max.apply(null, rects.map(function (r) { return r.left + r.width; }));
    var bottom = Math.max.apply(null, rects.map(function (r) { return r.top + r.height; }));
    if (opts.clampViewport) {
      var maxBottom = (window.innerHeight || 800) - 16;
      var minTop = opts.minTop != null ? opts.minTop : 64;
      top = Math.max(minTop, top);
      bottom = Math.min(maxBottom, bottom);
      if (bottom < top + 80) bottom = Math.min(maxBottom, top + 220);
    }
    placeHole({ top: top, left: left, width: right - left, height: bottom - top }, true);
  }

  /**
   * Foco ajustado al contenido real de una tabla/listado (no al contenedor
   * scroll que a menudo ocupa casi toda la ventana).
   */
  function placeHoleForList(el) {
    if (!ui.hole || !el) {
      placeHole(el);
      return;
    }
    var table = el;
    if (el.querySelector) {
      table = el.matches && el.matches('table') ? el : (el.querySelector('table') || el);
    }
    var first = table.querySelector
      ? (table.querySelector('thead tr.header-row') || table.querySelector('thead tr') || table.querySelector('tbody tr') || table)
      : table;
    var last = table.querySelector
      ? (table.querySelector('tbody tr:last-child') || table.querySelector('thead tr:last-child') || first)
      : table;
    var box = table.getBoundingClientRect ? table.getBoundingClientRect() : null;
    var a = first && first.getBoundingClientRect ? first.getBoundingClientRect() : box;
    var b = last && last.getBoundingClientRect ? last.getBoundingClientRect() : box;
    if (!a || !box) {
      placeHole(table);
      return;
    }
    var top = a.top;
    var bottom = b ? b.bottom : a.bottom;
    // Si el contenedor es más alto que el contenido, recortar al contenido
    var height = Math.max(24, bottom - top);
    var maxH = Math.min(height, (window.innerHeight || height) - Math.max(0, top) - 12);
    placeHole({
      top: top,
      left: box.left,
      width: box.width,
      height: Math.min(height, maxH),
    });
  }

  function dataEntryCluster(el) {
    if (!el || !el.closest) return el;
    var login = el.closest('[data-tour="fichar-login"]');
    if (login) {
      return login.closest('.contenido') || login.closest('.entrar') || login;
    }
    var fichaje = el.closest('.fichaje');
    if (fichaje) {
      return fichaje.closest('.contenido') || fichaje;
    }
    return el.closest('.entrar') || el.closest('.contenido') || el;
  }

  function placeCardLeftOf(el) {
    if (!ui.card) return;
    var cluster = dataEntryCluster(el) || el;
    holeTrack.cardEl = cluster && cluster.getBoundingClientRect ? cluster : (el || null);
    holeTrack.cardPlace = 'left-of';
    ui.card.classList.remove('is-modal');
    ui.card.style.transform = '';
    ui.card.style.display = '';
    var vw = window.innerWidth;
    var vh = window.innerHeight;
    var cardW = Math.min(360, vw - 24);
    ui.card.style.width = cardW + 'px';
    var estH = Math.min(280, Math.max(140, ui.card.offsetHeight || 180));
    var top = 24;
    var left = 12;
    var gap = 16;
    if (cluster && cluster.getBoundingClientRect) {
      var r = cluster.getBoundingClientRect();
      top = Math.max(12, Math.min(r.top, vh - estH - 12));
      var leftPos = r.left - cardW - gap;
      if (leftPos >= 12) {
        left = leftPos;
      } else if (r.right + gap + cardW <= vw - 12) {
        left = r.right + gap;
      } else {
        left = Math.max(12, Math.min(r.left, vw - cardW - 12));
        var below = r.bottom + 14;
        var above = r.top - estH - 12;
        if (below + Math.min(estH, 180) <= vh - 12) {
          top = Math.min(below, vh - estH - 12);
        } else if (above >= 12) {
          top = above;
        } else {
          top = Math.max(12, Math.min(r.top, vh - estH - 12));
        }
      }
    }
    top = Math.max(12, Math.min(top, vh - Math.min(estH, vh - 24)));
    left = Math.max(12, Math.min(left, vw - cardW - 12));
    ui.card.style.top = top + 'px';
    ui.card.style.left = left + 'px';
  }

  function repositionTourCard() {
    var place = holeTrack.cardPlace;
    var el = holeTrack.cardEl;
    if (place === 'left-of') {
      placeCardLeftOf(el);
      return;
    }
    if (place === 'corner') {
      placeCardCorner();
      return;
    }
    if (place === 'bottom') {
      placeCardDockBottom();
      return;
    }
    if (place === 'kanban') {
      placeCardClearOfKanban();
      return;
    }
    if (place === 'away') {
      placeCardOutside(el);
      return;
    }
    if (el && el.getBoundingClientRect) placeCardNear(el);
  }

  function placeCardNear(el) {
    if (!ui.card) return;
    if (el && el.getBoundingClientRect) holeTrack.cardEl = el;
    else if (!el) holeTrack.cardEl = null;
    ui.card.classList.remove('is-modal');
    ui.card.style.transform = '';
    ui.card.style.display = '';
    var vw = window.innerWidth;
    var vh = window.innerHeight;
    var cardW = Math.min(360, vw - 24);
    ui.card.style.width = cardW + 'px';
    var top = 24;
    var left = Math.max(12, (vw - cardW) / 2);
    var estH = Math.min(280, Math.max(140, ui.card.offsetHeight || 180));
    if (el && el.getBoundingClientRect) {
      var r = el.getBoundingClientRect();
      var isSidebar = !!(el.closest && el.closest('.sidebar-nav, .admin-sidebar, .sidebar'));
      var isTallSide = r.height > vh * 0.42 && r.width < vw * 0.42;
      var isLibres = !!(el.closest && (
        el.closest('[data-tour="tablero-libres"]') ||
        el.classList.contains('kanban-libres-panel') ||
        el.classList.contains('col-libres')
      ));
      if (isSidebar || (el.classList && el.classList.contains('sidebar-link'))) {
        // A la derecha del enlace del menú
        top = Math.max(12, Math.min(r.top, vh - estH - 12));
        left = Math.min(r.right + 16, vw - cardW - 12);
        if (left < 160) left = Math.max(12, (vw - cardW) / 2);
      } else if (isTallSide || isLibres) {
        // Paneles altos (libres): a la derecha, no debajo (quedaría fuera de vista)
        top = Math.max(72, Math.min(r.top + 8, vh - estH - 12));
        left = Math.min(r.right + 14, vw - cardW - 12);
        if (left < r.right - 20) {
          left = Math.max(12, vw - cardW - 12);
          top = Math.max(72, Math.min(120, vh - estH - 12));
        }
      } else {
        // Preferir ENCIMA del ancla (el tip no se pierde bajo el fold)
        top = r.top - estH - 12;
        left = Math.min(Math.max(12, r.left), vw - cardW - 12);
        if (top < 12) {
          top = Math.min(r.bottom + 14, vh - estH - 12);
        }
      }
    }
    top = Math.max(12, Math.min(top, vh - Math.min(estH, vh - 24)));
    left = Math.max(12, Math.min(left, vw - cardW - 12));
    ui.card.style.top = top + 'px';
    ui.card.style.left = left + 'px';
  }

  /** Tip fijo fuera del área de drop (no tapa las obras). */
  function placeCardClearOfKanban() {
    if (!ui.card) return;
    ui.card.classList.remove('is-modal');
    ui.card.style.transform = '';
    ui.card.style.display = '';
    var vw = window.innerWidth;
    var vh = window.innerHeight;
    var cardW = Math.min(340, vw - 24);
    ui.card.style.width = cardW + 'px';
    var estH = Math.min(260, Math.max(140, ui.card.offsetHeight || 180));
    var libres = qs('[data-tour="tablero-libres"], .kanban-libres-panel');
    var left = 12;
    var top = Math.max(12, vh - estH - 20);
    if (libres) {
      var r = libres.getBoundingClientRect();
      left = Math.max(12, Math.min(r.left + 8, vw - cardW - 12));
      top = Math.max(64, Math.min(r.bottom - estH - 8, vh - estH - 16));
    }
    ui.card.style.top = top + 'px';
    ui.card.style.left = left + 'px';
  }

  function placeCardDockBottom() {
    if (!ui.card) return;
    ui.card.classList.remove('is-modal');
    ui.card.style.transform = '';
    ui.card.style.display = '';
    var vw = window.innerWidth;
    var vh = window.innerHeight;
    var cardW = Math.min(360, vw - 24);
    ui.card.style.width = cardW + 'px';
    var estH = Math.min(280, Math.max(140, ui.card.offsetHeight || 180));
    ui.card.style.top = Math.max(12, vh - estH - 20) + 'px';
    ui.card.style.left = '12px';
  }

  function placeCardCorner() {
    if (!ui.card) return;
    ui.card.classList.remove('is-modal');
    ui.card.style.transform = '';
    ui.card.style.display = '';
    var vw = window.innerWidth;
    var cardW = Math.min(340, vw - 24);
    ui.card.style.width = cardW + 'px';
    ui.card.style.top = '16px';
    ui.card.style.left = Math.max(12, vw - cardW - 16) + 'px';
  }

  function placeCardForStep(step, el) {
    var mode = step.cardPlacement || (step.hero ? 'modal' : '');
    holeTrack.cardPlace = mode || (el ? 'near' : '');
    if (mode === 'bottom') {
      holeTrack.cardEl = null;
      placeCardDockBottom();
      return;
    }
    if (mode === 'left-of') {
      placeCardLeftOf(el);
      return;
    }
    if (mode === 'corner') {
      holeTrack.cardEl = null;
      placeCardCorner();
      return;
    }
    if (mode === 'away') {
      holeTrack.cardEl = el || null;
      placeCardOutside(el);
      return;
    }
    if (mode === 'kanban') {
      holeTrack.cardEl = null;
      placeCardClearOfKanban();
      return;
    }
    if (step.modal || step.hero) {
      holeTrack.cardEl = null;
      holeTrack.cardPlace = 'modal';
      placeCardModal();
      return;
    }
    if (el) placeCardNear(el);
    else placeCardNear(null);
  }

  /** Comentario fuera de un área (p. ej. calendario): no solapa el foco. */
  function placeCardOutside(avoidEl) {
    if (!ui.card) return;
    holeTrack.cardEl = null;
    ui.card.classList.remove('is-modal');
    ui.card.style.transform = '';
    ui.card.style.display = '';
    var vw = window.innerWidth;
    var vh = window.innerHeight;
    var cardW = Math.min(340, vw - 24);
    ui.card.style.width = cardW + 'px';
    var estH = Math.min(260, Math.max(140, ui.card.offsetHeight || 180));
    var top = 16;
    var left = Math.max(12, vw - cardW - 16);
    var avoid = avoidEl && avoidEl.getBoundingClientRect ? avoidEl.getBoundingClientRect() : null;
    if (avoid && avoid.width > 8) {
      var rightSpace = vw - avoid.right;
      var leftSpace = avoid.left;
      if (rightSpace >= cardW + 20) {
        left = avoid.right + 14;
        top = Math.max(12, Math.min(avoid.top + 8, vh - estH - 12));
      } else if (leftSpace >= cardW + 20) {
        left = Math.max(12, avoid.left - cardW - 14);
        top = Math.max(12, Math.min(avoid.top + 8, vh - estH - 12));
      } else if (avoid.top > estH + 24) {
        top = Math.max(12, avoid.top - estH - 12);
        left = Math.min(Math.max(12, avoid.left), vw - cardW - 12);
      } else {
        top = Math.min(avoid.bottom + 12, vh - estH - 12);
        left = Math.min(Math.max(12, avoid.left), vw - cardW - 12);
      }
    }
    top = Math.max(12, Math.min(top, vh - Math.min(estH, vh - 24)));
    left = Math.max(12, Math.min(left, vw - cardW - 12));
    ui.card.style.top = top + 'px';
    ui.card.style.left = left + 'px';
  }

  /** Mensaje siempre visible + foco en un ancla (botón / nav). */
  function spotlightWithCard(el) {
    ensureUi();
    if (ui.card) ui.card.style.display = '';
    if (!el) {
      placeHole(null);
      placeCardModal();
      return;
    }
    el.classList.add('sp-tour-target');
    // Scroll instantáneo: si es smooth, placeCardNear calcula mal y el tip queda fuera
    try { el.scrollIntoView({ block: 'center', behavior: 'auto' }); } catch (e) {
      try { el.scrollIntoView(true); } catch (e2) {}
    }
    placeHole(el);
    placeCardNear(el);
    requestAnimationFrame(function () {
      placeHole(el);
      placeCardNear(el);
    });
  }

  function placeCardModal() {
    if (!ui.card) return;
    ui.card.classList.add('is-modal');
    var vw = window.innerWidth;
    var isHero = ui.card.classList.contains('is-hero');
    var cardW = Math.min(isHero ? 540 : (ui.card.classList.contains('is-wide') ? 420 : 360), vw - 32);
    ui.card.style.width = cardW + 'px';
    ui.card.style.top = isHero ? '10%' : '22%';
    ui.card.style.left = '50%';
    ui.card.style.transform = 'translateX(-50%)';
    placeHole(null);
  }

  function hideTourBanner() {
    if (ui.banner && ui.banner.parentNode) ui.banner.parentNode.removeChild(ui.banner);
    ui.banner = null;
    document.body.classList.remove('sp-tour-banner-active');
  }

  function showTourBanner(opts) {
    opts = opts || {};
    ensureUi();
    hideTourBanner();
    clearTargets();
    placeHole(null);
    if (ui.card) {
      ui.card.style.display = 'none';
      ui.card.classList.remove('is-modal');
    }
    ui.banner = document.createElement('div');
    ui.banner.className = 'sp-tour-banner';
    ui.banner.innerHTML =
      '<p><strong>' + t(opts.title || 'Guía en pausa') + '</strong> — ' +
      t(opts.body || 'Revisa el mapeo con calma. Cuando quieras, vuelve a la guía.') + '</p>' +
      '<div class="sp-tour-actions">' +
      '<button type="button" class="sp-tour-skip" data-act="skip">' + t('Saltar guía') + '</button>' +
      '<button type="button" class="sp-tour-ghost" data-act="skip-section">' +
      sectionSkipLabel((loadState() || {}).chapter) + '</button>' +
      (opts.doneLabel
        ? '<button type="button" class="sp-tour-primary" data-act="done">' + t(opts.doneLabel) + '</button>'
        : '') +
      '<button type="button" class="sp-tour-primary" data-act="resume">' +
      t(opts.resumeLabel || 'Volver a la guía') + '</button>' +
      '</div>';
    document.body.appendChild(ui.banner);
    document.body.classList.add('sp-tour-banner-active');
    ui.banner.querySelector('[data-act="skip"]').onclick = function () {
      hideTourBanner();
      onSkipEntire();
    };
    var skipSec = ui.banner.querySelector('[data-act="skip-section"]');
    if (skipSec) {
      skipSec.onclick = function () {
        hideTourBanner();
        skipSection();
      };
    }
    var resume = ui.banner.querySelector('[data-act="resume"]');
    if (resume) {
      resume.onclick = function () {
        hideTourBanner();
        if (ui.card) ui.card.style.display = '';
        if (opts.onResume) opts.onResume();
        else run();
      };
    }
    var done = ui.banner.querySelector('[data-act="done"]');
    if (done) {
      done.onclick = function () {
        hideTourBanner();
        if (opts.onDone) opts.onDone();
        else pauseAtChapterEnd();
      };
    }
  }

  function clearTargets() {
    document.querySelectorAll('.sp-tour-target, .sp-tour-highlight-user').forEach(function (el) {
      el.classList.remove('sp-tour-target', 'sp-tour-highlight-user');
    });
  }

  function bindNavClick(el, nextStep) {
    if (!el) return;
    el.addEventListener('click', function (ev) {
      var st = loadState();
      if (!st) return;
      st.step = nextStep;
      saveState(st);
      // Navegar explícitamente: así el paso no se queda colgado si algo cancela el clic.
      var href = el.getAttribute('href');
      if (href && href !== '#' && !ev.defaultPrevented) {
        // Dejar que el navegador siga el enlace; el estado ya está guardado.
        return;
      }
      if (href && href !== '#') {
        ev.preventDefault();
        window.location.href = href;
      }
    }, { capture: true, once: true });
  }

  function renderStep(step) {
    ensureUi();
    hideTourBanner();
    clearTargets();
    if (ui.card) ui.card.style.display = '';

    var isModal = !!(step.modal || (step.choices && step.choices.length && !step.selector));
    var el = null;
    if (!isModal && step.selector && !step.manualTarget) {
      ensureTourTargetVisible(step.selector);
      el = qs(step.selector);
    }

    if (step.selector && !step.manualTarget && !el && !isModal) {
      if (step.ifMissing === 'skip') {
        advance(1);
        return;
      }
      if (step.ifMissing === 'wait') {
        // Mostrar el mensaje aunque el ancla aún no esté en el DOM
        placeHole(null);
        placeCardNear(null);
        var waitTitle = (typeof step.title === 'function') ? step.title() : (step.title || '');
        var waitBody = (typeof step.body === 'function') ? step.body() : (step.body || '');
        var waitNextLabel = (typeof step.nextLabel === 'function') ? step.nextLabel() : step.nextLabel;
        var waitProgress = (typeof step.progress === 'function') ? step.progress() : (step.progress || '');
        var waitHtml = '';
        waitHtml += '<div class="sp-tour-progress">' + t(waitProgress) + '</div>';
        waitHtml += '<h3>' + t(waitTitle) + '</h3>';
        waitHtml += '<p>' + t(waitBody) + '</p>';
        waitHtml += '<div class="sp-tour-actions">';
        waitHtml += '<button type="button" class="sp-tour-skip" data-act="skip">' +
          t((loadState() || {}).chapter === 'import' ? 'Salir de la guía' : (isInicioTrack() ? 'Saltar el recorrido' : 'Saltar guía')) + '</button>';
        if (!step.noSkipSection) {
          waitHtml += '<button type="button" class="sp-tour-ghost" data-act="skip-section">' +
            sectionSkipLabel((loadState() || {}).chapter) + '</button>';
        }
        if (step.waitClick || step.nextLabel || step.onNext) {
          waitHtml += '<button type="button" class="sp-tour-primary" data-act="next">' +
            t(waitNextLabel || (step.waitClick ? 'Ya lo hice →' : 'Siguiente')) + '</button>';
        }
        waitHtml += '</div>';
        ui.card.innerHTML = waitHtml;
        var waitSkip = ui.card.querySelector('[data-act="skip"]');
        if (waitSkip) {
          waitSkip.onclick = function () {
            onSkipEntire();
          };
        }
        var waitSkipSec = ui.card.querySelector('[data-act="skip-section"]');
        if (waitSkipSec) waitSkipSec.onclick = function () { skipSection(); };
        var waitNext = ui.card.querySelector('[data-act="next"]');
        if (waitNext) {
          waitNext.onclick = function () {
            if (step.onNext) {
              step.onNext();
              return;
            }
            if (step.selector) {
              ensureTourTargetVisible(step.selector);
              var t = qs(step.selector);
              var href = (t && t.getAttribute ? t.getAttribute('href') : null) ||
                NAV_FALLBACK_HREF[step.selector] || null;
              if (href && href !== '#') {
                var st = loadState() || {};
                st.step = (typeof step.advanceTo === 'number') ? step.advanceTo : ((st.step || 0) + 1);
                saveState(st);
                window.location.href = href;
                return;
              }
            }
            advance(1);
          };
        }
        setTimeout(function () { renderStep(step); }, 400);
        return;
      }
    }

    // Ancla: scroll ya; el tip se coloca DESPUÉS de rellenar el HTML (si no, mide mal)
    if (el) {
      el.classList.add('sp-tour-target');
      if (!step.noScroll) {
        try { el.scrollIntoView({ block: 'center', behavior: 'auto' }); } catch (e) {}
      }
    }

    var html = '';
    var stepTitle = (typeof step.title === 'function') ? step.title() : (step.title || '');
    var stepBody = (typeof step.body === 'function') ? step.body() : (step.body || '');
    var stepNextLabel = (typeof step.nextLabel === 'function') ? step.nextLabel() : step.nextLabel;
    var stepProgress = (typeof step.progress === 'function') ? step.progress() : (step.progress || '');
    if (step.hero) {
      ui.card.classList.add('is-hero', 'is-wide');
    } else {
      ui.card.classList.remove('is-hero');
    }
    if (!step.noProgress && !step.hero && stepProgress) {
      html += '<div class="sp-tour-progress">' + t(stepProgress) + '</div>';
    }
    html += '<h3>' + t(stepTitle) + '</h3>';
    html += '<p>' + t(stepBody) + '</p>';

    var skipEntireLabel = (loadState() || {}).chapter === 'import'
      ? 'Salir de la guía'
      : (isInicioTrack() ? 'Saltar el recorrido' : 'Saltar guía');
    var stackChoices = !!(step.choices && step.choices.length && (step.choicesLayout === 'stack' || step.hero));
    if (stackChoices) {
      ui.card.classList.add('is-wide');
      html += '<div class="sp-tour-choices">';
      step.choices.forEach(function (c, i) {
        var done = !!c.done;
        var cls = (c.kind === 'ghost' ? 'sp-tour-ghost' : 'sp-tour-primary') + (done ? ' is-done' : '');
        html += '<button type="button" class="' + cls + '" data-act="choice" data-i="' + i + '">' +
          '<span>' + t(typeof c.label === 'function' ? c.label() : c.label) + '</span>' +
          (done ? '<span class="sp-tour-choice-tick" aria-hidden="true">✓</span>' : '') +
          '</button>';
      });
      html += '</div>';
      if (!step.hideSkip || !step.noSkipSection) {
        html += '<div class="sp-tour-actions">';
        if (!step.hideSkip) {
          html += '<button type="button" class="sp-tour-skip" data-act="skip">' + t(skipEntireLabel) + '</button>';
        }
        if (!step.noSkipSection) {
          html += '<button type="button" class="sp-tour-ghost" data-act="skip-section">' +
            sectionSkipLabel((loadState() || {}).chapter) + '</button>';
        }
        html += '</div>';
      }
    } else {
      if (!step.hero) ui.card.classList.remove('is-wide');
      html += '<div class="sp-tour-actions">';
      if (!step.hideSkip) {
        html += '<button type="button" class="sp-tour-skip" data-act="skip">' + t(skipEntireLabel) + '</button>';
      }
      if (!step.noSkipSection) {
        var stNow = loadState() || {};
        html += '<button type="button" class="sp-tour-ghost" data-act="skip-section">' +
          sectionSkipLabel(stNow.chapter) + '</button>';
      }
      if (step.choices && step.choices.length) {
        step.choices.forEach(function (c, i) {
          html += '<button type="button" class="sp-tour-primary" data-act="choice" data-i="' + i + '">' +
            t(typeof c.label === 'function' ? c.label() : c.label) + '</button>';
        });
      } else if (step.waitClick && !step.hideNext) {
        html += '<button type="button" class="sp-tour-ghost" data-act="next">' +
          t(stepNextLabel || 'Ya lo hice →') + '</button>';
      } else if (step.primaryHref) {
        html += '<button type="button" class="sp-tour-primary" data-act="go">' +
          t(step.primaryLabel || 'Continuar') + '</button>';
      } else if (step.reviewMode) {
        html += '<button type="button" class="sp-tour-primary" data-act="review">' +
          t(step.reviewLabel || 'Revisar →') + '</button>';
        html += '<button type="button" class="sp-tour-ghost" data-act="next">' +
          t(stepNextLabel || 'Terminar guía →') + '</button>';
      } else if (!step.hideNext) {
        html += '<button type="button" class="sp-tour-next" data-act="next">' +
          t(stepNextLabel || 'Siguiente') + '</button>';
      }
      html += '</div>';
    }
    ui.card.innerHTML = html;
    ui.card.style.display = '';

    // Posicionar tip ya con el contenido real
    if (isModal || step.hero) {
      placeCardModal();
      requestAnimationFrame(function () { placeCardModal(); });
    } else if (step.cardPlacement) {
      if (el) placeHole(el);
      else if (!step.manualTarget) placeHole(null);
      placeCardForStep(step, el);
      if (step.cardPlacement === 'left-of') {
        requestAnimationFrame(function () { placeCardForStep(step, el); });
      }
    } else if (el) {
      placeHole(el);
      placeCardNear(el);
    } else if (!step.manualTarget) {
      placeHole(null);
      placeCardNear(null);
    }

    var skipEntireBtn = ui.card.querySelector('[data-act="skip"]');
    if (skipEntireBtn) {
      skipEntireBtn.onclick = function () {
        onSkipEntire();
      };
    }

    var skipSecBtn = ui.card.querySelector('[data-act="skip-section"]');
    if (skipSecBtn) {
      skipSecBtn.onclick = function () { skipSection(); };
    }

    var reviewBtn = ui.card.querySelector('[data-act="review"]');
    if (reviewBtn) {
      reviewBtn.onclick = function () {
        showTourBanner({
          title: step.bannerTitle || 'Revisa el asistente',
          body: step.bannerBody || 'Cuando termines el mapeo o la importación, vuelve aquí.',
          resumeLabel: 'Volver a la guía',
          doneLabel: step.nextLabel || 'Terminar guía →',
          onResume: function () {
            if (typeof step.onResumeFromBanner === 'function') {
              step.onResumeFromBanner();
              return;
            }
            renderStep(step);
          },
          onDone: function () {
            if (step.onNext) step.onNext();
            else advance(1);
          },
        });
      };
    }

    var nextBtn = ui.card.querySelector('[data-act="next"]');
    if (nextBtn) {
      nextBtn.onclick = function () {
        // Si el paso exige una acción y no está hecha:
        // - gateRetry → volver a enfocar el mismo paso (no cortar la guía)
        // - si no → cortar
        if (typeof step.requireGate === 'function') {
          var okGate = false;
          try { okGate = !!step.requireGate(); } catch (eGate) { okGate = false; }
          if (!okGate) {
            if (step.gateRetry) {
              if (typeof step.onGateFail === 'function') {
                try { step.onGateFail(); } catch (eFail) { /* ignore */ }
              }
              // Re-render del mismo paso para recuperar el foco/spotlight
              run();
              // Aviso breve en la tip si hay mensaje
              setTimeout(function () {
                if (!ui.card || !step.gateFail) return;
                var p = ui.card.querySelector('p');
                if (p) {
                  p.innerHTML = '<span style="color:#b45309;">' + t(step.gateFail) + '</span>';
                }
              }, 30);
              return;
            }
            stopTour({
              message: step.gateFail ||
                'No se completó el paso indicado. Sin eso la guía no tiene sentido: reábrela cuando quieras intentarlo de nuevo.',
            });
            return;
          }
        }
        // Si el paso pide un clic en un enlace del menú, «Ya lo hice» navega ahí.
        if (step.waitClick && step.selector) {
          var target = el || qs(step.selector);
          var href = target && target.getAttribute ? target.getAttribute('href') : null;
          if (href && href !== '#') {
            var st = loadState() || {};
            st.step = (typeof step.advanceTo === 'number') ? step.advanceTo : ((st.step || 0) + 1);
            saveState(st);
            if (window.SP_pageLoading) window.SP_pageLoading.show(t('Cargando…'));
            window.location.href = href;
            return;
          }
        }
        if (step.onNext) {
          step.onNext();
          return;
        }
        advance(1);
      };
    }

    var goBtn = ui.card.querySelector('[data-act="go"]');
    if (goBtn && step.primaryHref) {
      goBtn.onclick = function () {
        var prep = step.onBeforeGo ? step.onBeforeGo() : null;
        var go = function () { window.location.href = step.primaryHref; };
        if (prep && typeof prep.then === 'function') prep.then(go, go);
        else go();
      };
    }
    ui.card.querySelectorAll('[data-act="choice"]').forEach(function (btn) {
      btn.onclick = function () {
        var choice = step.choices[parseInt(btn.getAttribute('data-i'), 10)];
        if (choice && choice.onPick) choice.onPick();
      };
    });

    if (step.waitClick && el) {
      bindNavClick(el, typeof step.advanceTo === 'number' ? step.advanceTo : ((loadState() || {}).step || 0) + 1);
    }

    if (step.onShow) step.onShow(el, loadState() || {});
  }

  function advance(delta) {
    var state = loadState();
    if (!state || !state.active) return;
    state.step = (state.step || 0) + (delta || 1);
    saveState(state);
    run();
  }

  function showDoneCard(message) {
    ensureUi();
    clearTargets();
    placeHole(null);
    ui.card.classList.add('is-modal');
    ui.card.style.transform = 'translateX(-50%)';
    ui.card.innerHTML =
      '<h3>' + t('Guía en pausa') + '</h3><p>' + t(message || '') + '</p>' +
      '<div class="sp-tour-actions">' +
      '<button type="button" class="sp-tour-primary" data-act="ok">' + t('Entendido') + '</button></div>';
    ui.card.style.top = '30%';
    ui.card.style.left = '50%';
    ui.card.querySelector('[data-act="ok"]').onclick = function () { teardown(); };
  }

  function highlightGroup(selector) {
    var group = qs(selector);
    if (!group) return null;
    clearTargets();
    group.classList.add('sp-tour-target');
    placeHole(group);
    placeCardNear(group);
    return group;
  }

  function highlightRowByDni(dni) {
    clearTargets();
    var needle = String(dni || '').toUpperCase().trim();
    var row = null;
    if (needle) {
      document.querySelectorAll('[data-tour-user-row]').forEach(function (tr) {
        if (row) return;
        var d = (tr.getAttribute('data-dni') || '').toUpperCase().trim();
        if (d === needle) row = tr;
      });
    }
    if (!row) return null;
    row.classList.add('sp-tour-target', 'sp-tour-highlight-user');
    try { row.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch (e) {}
    placeHole(row);
    placeCardNear(row);
    return row;
  }

  function highlightWorkerChip() {
    clearTargets();
    var st = loadState() || {};
    var needle = String(st.createdDni || '').toUpperCase().trim();
    var obraName = String(st.createdObraNombre || '').toLowerCase().trim();
    var obraRoot = qs('.kanban-works-wrapper') || document;
    var chip = null;

    // Solo chips DENTRO de una obra (nunca el panel de libres / ocupados)
    function chipsInObras() {
      return obraRoot.querySelectorAll('.kanban-col .worker-chip, .obra-card .worker-chip');
    }

    if (needle) {
      chipsInObras().forEach(function (el) {
        if (chip) return;
        if ((el.getAttribute('data-dni') || '').toUpperCase().trim() === needle) chip = el;
      });
    }

    if (!chip && obraName) {
      document.querySelectorAll('.kanban-col[data-obra-id]').forEach(function (col) {
        if (chip) return;
        var title = (col.querySelector('.header-title') || {}).textContent || '';
        if (title.toLowerCase().indexOf(obraName) === -1) return;
        chip = col.querySelector('.worker-chip');
      });
    }

    if (!chip) {
      var obraId = (new URLSearchParams(window.location.search || '')).get('obra');
      if (obraId) {
        var col = qs('.kanban-col[data-obra-id="' + obraId + '"]');
        if (col) chip = col.querySelector('.worker-chip');
      }
    }

    // Último recurso: primer chip con pelota roja dentro de una obra
    if (!chip) {
      chipsInObras().forEach(function (el) {
        if (chip) return;
        if (el.querySelector('.dot-danger')) chip = el;
      });
    }

    if (!chip) return null;
    chip.classList.add('sp-tour-target', 'sp-tour-highlight-user');
    var dot = chip.querySelector('.dot-danger, .status-dot-kanban');
    if (dot) dot.classList.add('sp-tour-target');
    var card = chip.closest('.kanban-col, .obra-card') || chip;
    try { card.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch (e) {}
    if (dot) placeHoleUnion([chip, dot]);
    else placeHole(card);
    placeCardDockBottom();
    return chip;
  }

  function _visibleRect(el) {
    if (!el || !el.getBoundingClientRect) return null;
    var r = el.getBoundingClientRect();
    if (r.width < 8 || r.height < 8) return null;
    if (r.bottom < 0 || r.right < 0) return null;
    if (r.top > (window.innerHeight || 0) && r.left > (window.innerWidth || 0)) return null;
    return r;
  }

  function selectOficinaInFichajeSelect(el) {
    el = el || qs('[data-tour="fichar-obra"], #obra');
    if (!el || !el.options) return false;
    var found = null;
    var foundExact = null;
    Array.prototype.forEach.call(el.options, function (opt) {
      if (!opt || opt.disabled) return;
      var val = (opt.value || '').trim();
      if (!val) return;
      var t = (opt.textContent || '').replace(/\s+/g, ' ').trim().toLowerCase();
      if (t === 'oficina') foundExact = opt;
      else if (!found && t.indexOf('oficina') >= 0) found = opt;
    });
    found = foundExact || found;
    if (!found) return false;
    // Quitar selected de las demás y forzar esta
    Array.prototype.forEach.call(el.options, function (opt) {
      opt.selected = (opt === found);
      try { opt.removeAttribute('selected'); } catch (e0) { /* ignore */ }
    });
    try { found.setAttribute('selected', 'selected'); } catch (e1) { /* ignore */ }
    el.value = found.value;
    try { el.selectedIndex = found.index; } catch (e2) { /* ignore */ }
    try {
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
    } catch (e3) { /* ignore */ }
    return String(el.value) === String(found.value);
  }

  function ensureOficinaSelected(retries) {
    retries = retries == null ? 6 : retries;
    var ok = selectOficinaInFichajeSelect();
    if (ok || retries <= 0) return ok;
    setTimeout(function () { ensureOficinaSelected(retries - 1); }, 120);
    return false;
  }

  function selectObraInFichajeSelect(el, needle) {
    el = el || qs('[data-tour="fichar-obra"], #obra');
    needle = String(needle || '').toLowerCase().trim();
    if (!el || !el.options) return false;
    var st = loadState() || {};
    var wantId = String(st.createdObraId || '').trim();
    var found = null;
    Array.prototype.forEach.call(el.options, function (opt) {
      if (!opt || opt.disabled || found) return;
      var val = (opt.value || '').trim();
      if (!val) return;
      if (wantId && String(val) === wantId) {
        found = opt;
        return;
      }
      var txt = (opt.textContent || '').replace(/\s+/g, ' ').trim().toLowerCase();
      if (needle && txt.indexOf(needle) >= 0) found = opt;
    });
    if (!found) return false;
    Array.prototype.forEach.call(el.options, function (opt) {
      opt.selected = (opt === found);
    });
    el.value = found.value;
    try {
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
    } catch (e3) { /* ignore */ }
    return String(el.value) === String(found.value);
  }

  function ensureCreatedObraSelected(retries) {
    retries = retries == null ? 8 : retries;
    var st = loadState() || {};
    var ok = selectObraInFichajeSelect(null, st.createdObraNombre || '');
    if (ok || retries <= 0) return ok;
    setTimeout(function () { ensureCreatedObraSelected(retries - 1); }, 120);
    return false;
  }

  /**
   * Detecta en auditoría qué sección aplica al fichaje del tour
   * (desviación vs sin planificar) y enfoca esa.
   */
  function resolveAuditTourSection() {
    var st = loadState() || {};
    var dni = String(st.createdDni || '').toUpperCase().trim();

    var defs = [
      {
        kind: 'desviaciones',
        root: qs('[data-tour="audit-desviaciones"]'),
        toggle: qs('[data-tour="audit-desviaciones-toggle"]'),
        collapse: qs('#collapseConflictos'),
        collapseSel: '#collapseConflictos',
        title: 'Desviaciones de plan',
        explain:
          'Has fichado en <strong>Oficina</strong> pero estabas planificado en otra obra. Por eso cae aquí: <strong>Desviaciones de plan</strong>.',
      },
      {
        kind: 'paracaidistas',
        root: qs('[data-tour="audit-paracaidistas"]'),
        toggle: qs('[data-tour="audit-paracaidistas-toggle"]'),
        collapse: qs('#collapseParacaidistas'),
        collapseSel: '#collapseParacaidistas',
        title: 'Fichajes sin planificar',
        explain:
          'Has fichado sin tener cuadrante en esa obra. Por eso cae aquí: <strong>Fichajes sin planificar</strong>.',
      },
    ];

    function rowsIn(def) {
      if (!def.root) return [];
      return Array.prototype.slice.call(
        def.root.querySelectorAll('tr.audit-data-row, tr[data-tour-audit-row], tbody tr')
      ).filter(function (tr) {
        return tr.querySelectorAll('td').length > 2;
      });
    }

    function rowMatch(tr) {
      if (!tr) return false;
      if (dni && (tr.getAttribute('data-dni') || '').toUpperCase().trim() === dni) return true;
      if (/oficina/i.test(tr.textContent || '')) return true;
      return false;
    }

    // 1) Fila que encaja con el DNI / Oficina
    for (var i = 0; i < defs.length; i++) {
      var rows = rowsIn(defs[i]);
      for (var r = 0; r < rows.length; r++) {
        if (rowMatch(rows[r])) {
          defs[i].matchedRow = rows[r];
          return defs[i];
        }
      }
    }

    // 2) Sección abierta con filas
    for (var j = 0; j < defs.length; j++) {
      if (defs[j].collapse && defs[j].collapse.classList.contains('show') && rowsIn(defs[j]).length) {
        return defs[j];
      }
    }

    // 3) Primera con filas (desviaciones antes que sin planificar: caso típico con demo)
    for (var k = 0; k < defs.length; k++) {
      if (rowsIn(defs[k]).length) return defs[k];
    }

    // 4) Fallback
    return defs[0].root ? defs[0] : defs[1];
  }

  function highlightAuditSection() {
    clearTargets();
    placeHole(null);
    var info = resolveAuditTourSection();
    if (!info || !info.root) {
      placeCardModal();
      return null;
    }
    var target = info.toggle || info.root;
    target.classList.add('sp-tour-target');
    try { target.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch (e) {}
    if (_visibleRect(target)) {
      placeHole(target);
      placeCardOutside(target);
    } else {
      placeHole(null);
      placeCardModal();
    }
    if (ui.card) {
      var h = ui.card.querySelector('h3');
      var p = ui.card.querySelector('p');
      if (h) h.textContent = t(info.title);
      if (p) p.innerHTML = t(info.explain);
    }
    try {
      if (info.collapse && !info.collapse.classList.contains('show')) {
        if (typeof window.openAuditoriaSection === 'function') {
          window.openAuditoriaSection(info.collapseSel);
        } else if (window.jQuery) {
          window.jQuery(info.collapse).collapse('show');
        } else if (info.toggle) {
          info.toggle.click();
        }
      }
    } catch (e2) {}
    return target;
  }

  function highlightAuditParacaidista(done) {
    clearTargets();
    placeHole(null);

    var st = loadState() || {};
    var needle = String(st.createdDni || '').toUpperCase().trim();
    var info = resolveAuditTourSection();
    var toggle = (info && info.toggle) || qs('[data-tour="audit-paracaidistas-toggle"]');
    var collapse = (info && info.collapse) || qs('#collapseParacaidistas');
    var collapseSel = (info && info.collapseSel) || '#collapseParacaidistas';
    var settled = false;
    var attempts = 0;
    var MAX_ATTEMPTS = 8;

    function finishRow(row) {
      if (settled) return row || null;
      settled = true;
      clearTargets();
      if (!row) {
        placeHole(null);
        placeCardModal();
        if (done) done(null);
        return null;
      }
      row.classList.add('sp-tour-target', 'sp-tour-highlight-user');
      var actionsCell = row.querySelector('td.no-row-nav') ||
        row.querySelector('td.text-right') ||
        row.querySelector('td:last-child');
      var buttons = Array.prototype.slice.call(
        row.querySelectorAll('button.btn-audit, button[onclick*="resolver"], [data-tour="audit-aceptar"]')
      );
      buttons.forEach(function (b) { b.classList.add('sp-tour-target'); });
      try {
        (actionsCell || row).scrollIntoView({ block: 'center', behavior: 'smooth' });
      } catch (e) {}
      // Agujero en los botones; tip FUERA para no taparlos
      if (buttons.length >= 2) {
        placeHoleUnion(buttons);
      } else if (actionsCell && _visibleRect(actionsCell)) {
        placeHole(actionsCell);
      } else if (_visibleRect(row)) {
        placeHole(row);
      } else {
        placeHole(null);
      }
      placeCardOutside(actionsCell || row);
      if (done) done(buttons[0] || row, buttons, row);
      return buttons[0] || row;
    }

    function pickRow() {
      var row = null;
      var scope = collapse || (info && info.root) || document;
      if (needle) {
        scope.querySelectorAll('[data-tour-audit-row], tr.audit-data-row').forEach(function (tr) {
          if (row) return;
          if ((tr.getAttribute('data-dni') || '').toUpperCase().trim() === needle) row = tr;
        });
      }
      if (!row) {
        scope.querySelectorAll('[data-tour-audit-row], tr.audit-data-row').forEach(function (tr) {
          if (row) return;
          if (/oficina/i.test(tr.textContent || '')) row = tr;
        });
      }
      if (!row) {
        row = (collapse && collapse.querySelector('[data-tour-audit-row], tr.audit-data-row')) ||
          qs('#collapseConflictos tr.audit-data-row, #collapseParacaidistas [data-tour-audit-row]');
      }
      return row;
    }

    function afterOpen() {
      if (settled) return null;
      var row = pickRow();
      if (row && _visibleRect(row)) {
        return finishRow(row);
      }
      attempts += 1;
      if (attempts < MAX_ATTEMPTS) {
        setTimeout(afterOpen, 80);
        return null;
      }
      return finishRow(null);
    }

    function openThenFocus() {
      var needsOpen = collapse && !collapse.classList.contains('show');
      if (!needsOpen) {
        afterOpen();
        return null;
      }
      var onShown = function () {
        if (collapse) {
          collapse.removeEventListener('shown.bs.collapse', onShown);
        }
        setTimeout(afterOpen, 50);
      };
      if (collapse && collapse.addEventListener) {
        collapse.addEventListener('shown.bs.collapse', onShown);
      }
      try {
        if (typeof window.openAuditoriaSection === 'function') {
          window.openAuditoriaSection(collapseSel);
        } else if (window.jQuery) {
          window.jQuery(collapse).collapse('show');
        } else if (toggle) {
          toggle.click();
        }
      } catch (e) {
        if (toggle) try { toggle.click(); } catch (e2) {}
      }
      setTimeout(function () {
        if (!settled) afterOpen();
      }, 500);
      return null;
    }

    return openThenFocus();
  }

  function openAuditHistoricoSection() {
    var toggle = qs('[data-tour="audit-historico-toggle"]');
    var collapse = qs('#collapseHistorial');
    var root = qs('[data-tour="audit-historico"]');
    try {
      if (collapse && !collapse.classList.contains('show')) {
        if (typeof window.openAuditoriaSection === 'function') {
          window.openAuditoriaSection('#collapseHistorial');
        } else if (window.jQuery) {
          window.jQuery(collapse).collapse('show');
        } else if (toggle) {
          toggle.click();
        }
      }
    } catch (e) { /* ignore */ }
    return { toggle: toggle, collapse: collapse, root: root };
  }

  function findHistoricoTourRow() {
    var st = loadState() || {};
    var dni = String(st.createdDni || '').toUpperCase().trim();
    var scope = qs('#collapseHistorial') || qs('[data-tour="audit-historico"]') || document;
    var rows = Array.prototype.slice.call(
      scope.querySelectorAll('[data-tour-historico-row], #historialTable tbody tr.audit-data-row')
    );
    var hit = null;
    if (dni) {
      rows.forEach(function (tr) {
        if (hit) return;
        if ((tr.getAttribute('data-dni') || '').toUpperCase().trim() === dni) hit = tr;
      });
    }
    if (!hit) {
      rows.forEach(function (tr) {
        if (hit) return;
        if (/oficina/i.test(tr.textContent || '') &&
            /reasign|asignad|ignor|resuelto|multitarea/i.test(tr.textContent || '')) {
          hit = tr;
        }
      });
    }
    if (!hit) {
      rows.forEach(function (tr) {
        if (hit) return;
        if (/oficina/i.test(tr.textContent || '')) hit = tr;
      });
    }
    return hit || rows[0] || null;
  }

  /** Lee los hitos del modal de actividad y arma el tip según lo que realmente hay. */
  function buildActivityTourTipHtml(root) {
    var scope = root || document;
    var items = Array.prototype.slice.call(scope.querySelectorAll('.person-day-timeline-item'));
    if (!items.length) {
      if (scope.querySelector('.person-day-timeline-loading')) {
        return null; // aún cargando
      }
      return t('Aquí se lee la historia del día. En este caso aún no hay eventos listados.');
    }

    var hadPlan = false;
    var points = [];

    function esc(s) {
      return String(s || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
    }

    function obraFromDesc(desc) {
      var m = /→\s*'([^']+)'/.exec(desc || '') ||
        /en\s+'([^']+)'/i.exec(desc || '') ||
        /fich[oó]\s+en\s+([^.]+)/i.exec(desc || '');
      return m ? m[1].trim() : '';
    }

    items.forEach(function (item) {
      var title = ((item.querySelector('.person-day-timeline-title') || {}).textContent || '').trim();
      var desc = ((item.querySelector('.person-day-timeline-desc') || {}).textContent || '').trim();
      var blob = (title + ' ' + desc).toLowerCase();
      if (!title || title === 'Sin actividad') return;

      if (/auto-?asignaci[oó]n|fichaje f[ií]sico/i.test(blob)) {
        var obraAuto = obraFromDesc(desc);
        if (hadPlan) {
          points.push(
            t('Fichó en otra') + (obraAuto ? ' (<strong>' + esc(obraAuto) + '</strong>)' : '') +
            t(': el sistema lo anota como <strong>autoasignación por fichaje físico</strong>.')
          );
        } else {
          points.push(
            t('No estaba <strong>planificada</strong> en ninguna obra') +
            (obraAuto ? ' ' + t('y fichó en') + ' <strong>' + esc(obraAuto) + '</strong>' : '') +
            t(': cae como fichaje <strong>sin planificar</strong> (autoasignación por fichaje físico).')
          );
        }
        return;
      }

      if (/^planificaci[oó]n$/i.test(title) ||
          (/asignado/i.test(desc) && !/auto/i.test(blob) && !/resoluci/i.test(blob))) {
        hadPlan = true;
        var obraPlan = obraFromDesc(desc);
        points.push(
          t('Estaba <strong>planificada</strong>') +
          (obraPlan ? ' ' + t('en') + ' <strong>' + esc(obraPlan) + '</strong>' : ' ' + t('en una obra')) + '.'
        );
        return;
      }

      if (/resoluci[oó]n de fichaje|reabrir resoluci/i.test(title)) {
        if (/mover/i.test(blob)) {
          points.push(t('Tú resolviste con <strong>Mover</strong>: el cuadrante pasa a la obra del fichaje.'));
        } else if (/a[ñn]adir|multi|pluri/i.test(blob)) {
          points.push(t('Tú resolviste con <strong>Añadir</strong>: se mantiene la planificada y se suma la del fichaje.'));
        } else if (/ignor/i.test(blob)) {
          points.push(t('Tú resolviste con <strong>Ignorar</strong>: se oculta la alerta sin cambiar el plan.'));
        } else if (/acept/i.test(blob)) {
          points.push(t('Tú resolviste con <strong>Aceptar</strong>: se asigna oficialmente a la obra del fichaje.'));
        } else if (/borrar|error al planificar/i.test(blob)) {
          points.push(t('Tú resolviste borrando la planificación que no encajaba.'));
        } else {
          points.push(t('Tú <strong>resolviste</strong> la incidencia en auditoría') + ' (<em>' + esc(title) + '</em>).');
        }
        return;
      }

      if (/entrada|salida|fichaje_app|fichaje en app|marca/i.test(blob) || /fichaje/i.test(title)) {
        points.push(t('Queda el <strong>registro de fichaje</strong> (entrada/salida) de ese momento.'));
        return;
      }

      if (/pausa/i.test(blob)) {
        points.push(t('Hay una <strong>pausa</strong> registrada en la jornada.'));
        return;
      }

      // Cualquier otro hito visible: un punto con su título
      points.push('<strong>' + esc(title) + '</strong>' + (desc ? ': ' + esc(desc.length > 110 ? desc.slice(0, 107) + '…' : desc) : ''));
    });

    if (!points.length) {
      return t('Aquí se lee la historia del día en orden. Abre cada evento del zoom para ver el detalle.');
    }

    var html = t('En esta actividad (el zoom) aparece, en orden:') + '<br>';
    points.forEach(function (pt, i) {
      html += '<strong>' + (i + 1) + '.</strong> ' + pt + '<br>';
    });
    return html;
  }

  function highlightHistoricoTourRow() {
    clearTargets();
    var parts = openAuditHistoricoSection();
    var tries = 0;
    function focus() {
      var row = findHistoricoTourRow();
      if (!row && tries < 10) {
        tries += 1;
        setTimeout(focus, 120);
        return null;
      }
      if (!row) {
        var fallback = parts.toggle || parts.root;
        if (fallback) {
          placeHole(fallback);
          placeCardOutside(fallback);
        } else {
          placeHole(null);
          placeCardModal();
        }
        return null;
      }
      row.classList.add('sp-tour-target', 'sp-tour-highlight-user');
      try { row.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch (e) {}
      placeHole(row);
      placeCardOutside(row);
      return row;
    }
    setTimeout(focus, 350);
    return focus();
  }

  var AUDIT_SECTION_COPY = {
    desviaciones: {
      root: '[data-tour="audit-desviaciones"]',
      toggle: '[data-tour="audit-desviaciones-toggle"]',
      collapse: '#collapseConflictos',
      title: 'Desviaciones de plan',
      body:
        'Cuando alguien ficha en una obra distinta a la del cuadrante, la alerta aparece aquí. ' +
        'Solo es para que sepas qué es esta sección: no hace falta pulsar nada de estas filas de ejemplo.',
    },
    paracaidistas: {
      root: '[data-tour="audit-paracaidistas"]',
      toggle: '[data-tour="audit-paracaidistas-toggle"]',
      collapse: '#collapseParacaidistas',
      title: 'Fichajes sin planificar',
      body:
        'Fichó sin tener obra ese día. Esta sección agrupa esos casos. ' +
        'No hace falta actuar sobre las filas de ejemplo.',
    },
    ausencias: {
      root: '[data-tour="audit-ausencias"]',
      toggle: '[data-tour="audit-ausencias-toggle"]',
      collapse: '#collapseAusencias',
      title: 'Ausencias',
      body:
        'Estaba planificado y no fichó. Aquí ves quién faltó respecto al cuadrante. ' +
        'Si tu fichaje no ha caído aquí, no tienes que hacer nada en esta lista.',
    },
  };

  function explainAuditSection(kind) {
    var def = AUDIT_SECTION_COPY[kind];
    if (!def) return;
    clearTargets();
    var root = qs(def.root);
    var toggle = qs(def.toggle);
    var collapse = qs(def.collapse);
    try {
      if (collapse && !collapse.classList.contains('show')) {
        if (typeof window.openAuditoriaSection === 'function') {
          window.openAuditoriaSection(def.collapse);
        } else if (window.jQuery) {
          window.jQuery(collapse).collapse('show');
        } else if (toggle) {
          toggle.click();
        }
      }
    } catch (eOpen) { /* ignore */ }

    function paint() {
      var holeEl = toggle || root;
      if (toggle) toggle.classList.add('sp-tour-target');
      else if (root) root.classList.add('sp-tour-target');
      if (holeEl && _visibleRect(holeEl)) placeHole(holeEl);
      else if (root && _visibleRect(root)) placeHole(root);
      else placeHole(null);
      placeCardOutside(holeEl || root);
      if (ui.card) {
        var h = ui.card.querySelector('h3');
        var p = ui.card.querySelector('p');
        if (h) h.textContent = t(def.title);
        if (p) p.innerHTML = t(def.body);
      }
    }
    paint();
    setTimeout(paint, 380);
  }

  function showAuditActivityTourCard() {
    clearTargets();
    var tries = 0;
    function placeTipReadable(modalOrRoot) {
      if (!ui.card) return false;
      var tip = buildActivityTourTipHtml(modalOrRoot || document);
      var p = ui.card.querySelector('p');
      if (tip === null) {
        if (p) p.textContent = t('Cargando la actividad del día…');
        ui.card.style.zIndex = '20050';
        if (ui.backdrop) ui.backdrop.style.zIndex = '20040';
        return false;
      }
      if (p) p.innerHTML = tip;
      ui.card.style.zIndex = '20050';
      if (ui.backdrop) ui.backdrop.style.zIndex = '20040';
      return true;
    }
    function focusTimeline() {
      var modal = qs('#modalPersonDayTimeline.show, .person-day-timeline-modal.show');
      if (!modal) {
        var any = qs('#modalPersonDayTimeline, .person-day-timeline-modal');
        if (any && (any.classList.contains('show') || (any.style && any.style.display === 'block'))) {
          modal = any;
        } else if (any && tries < 16) {
          tries += 1;
          setTimeout(focusTimeline, 200);
          return;
        } else {
          modal = any;
        }
      }
      var holeEl = null;
      if (modal) {
        holeEl = modal.querySelector('.person-day-timeline-container') ||
          modal.querySelector('[data-timeline-content]') ||
          modal.querySelector('[data-person-day-timeline-root]') ||
          modal.querySelector('.modal-body') ||
          modal.querySelector('.person-day-timeline-modal-content') ||
          modal.querySelector('.modal-content') ||
          modal;
      }
      if (holeEl) {
        var r = holeEl.getBoundingClientRect ? holeEl.getBoundingClientRect() : null;
        var tipReady = placeTipReadable(modal || holeEl);
        var loading = !!(modal && modal.querySelector('.person-day-timeline-loading'));
        if (((!r || r.width < 40 || r.height < 40) || loading || tipReady === false) && tries < 20) {
          tries += 1;
          setTimeout(focusTimeline, 220);
          if (r && r.width >= 40 && r.height >= 40) {
            placeHole(holeEl);
            placeCardOutside(holeEl);
            holeTrack.cardEl = null;
          }
          return;
        }
        placeHole(holeEl);
        placeTipReadable(modal || holeEl);
        placeCardOutside(holeEl);
        holeTrack.cardEl = null;
      } else if (tries < 16) {
        tries += 1;
        setTimeout(focusTimeline, 200);
      } else {
        placeHole(null);
        placeTipReadable(document);
        placeCardModal();
      }
    }
    setTimeout(focusTimeline, 280);
  }

  function makeAuditWalkthroughSteps(opts) {
    opts = opts || {};
    var S = opts.startStep || 10;
    var prefix = opts.progressPrefix || 'Auditoría';
    var extraWhen = opts.extraWhen || function () { return true; };
    var onFinish = opts.onFinish || function () { pauseAtChapterEnd(); };
    var includeResolve = opts.includeResolve !== false;

    function band(n) {
      return function () {
        var st = loadState() || {};
        return pathIs(/\/sync\/auditoria/) && extraWhen(st) && (st.step || 0) >= n && (st.step || 0) < n + 1;
      };
    }
    function go(n) {
      return function () {
        var st = loadState() || {};
        st.step = n;
        saveState(st);
        run();
      };
    }
    function reloadAfterResolve() {
      var st = loadState() || {};
      if (typeof opts.reloadHref === 'function') return opts.reloadHref(st);
      if (st.chapter === 'fichajes') return '/sync/auditoria?tour=fichajes&mode=solo';
      return '/sync/auditoria?tour=fichaje&continue=1';
    }

    var resolveN = S;
    var introN = includeResolve ? S + 1 : S;
    var desvN = introN + 1;
    var paraN = desvN + 1;
    var ausN = paraN + 1;
    var histN = ausN + 1;
    var corrN = histN + 1;
    var doneN = corrN + 1;

    var out = [];

    if (includeResolve) {
      out.push({
        when: band(resolveN),
        manualTarget: true,
        title: 'Cómo resolverlo',
        body: 'Elige una acción sobre la fila de quien acabas de fichar.',
        progress: prefix + ' · resolver',
        waitClick: true,
        nextLabel: 'Ya lo resolví →',
        onShow: function () {
          var info = resolveAuditTourSection();
          var advanced = false;
          function goNextSections() {
            if (advanced) return;
            advanced = true;
            var st = loadState() || {};
            st.step = introN;
            st.auditResolved = true;
            if (info && info.kind) st.auditKind = info.kind;
            saveState(st);
            setTimeout(function () {
              window.location.href = reloadAfterResolve();
            }, 700);
          }
          highlightAuditParacaidista(function (btn, buttons) {
            var list = (buttons && buttons.length) ? buttons : (btn ? [btn] : []);
            list.forEach(function (b) {
              b.addEventListener('click', goNextSections, true);
            });
          });
          if (ui.card) {
            var h = ui.card.querySelector('h3');
            var p = ui.card.querySelector('p');
            if (info && info.kind === 'desviaciones') {
              if (h) h.textContent = t('Desviaciones: tres acciones');
              if (p) {
                p.innerHTML =
                  t('<strong>Mover</strong>: cambia el cuadrante a la obra del fichaje.') + '<br>' +
                  t('<strong>+ Añadir</strong>: mantiene la planificada y añade la del fichaje.') + '<br>' +
                  t('<strong>Ignorar</strong>: oculta la alerta sin tocar el plan.');
              }
            } else if (info && info.kind === 'paracaidistas') {
              if (h) h.textContent = t('Sin planificar: dos acciones');
              if (p) {
                p.innerHTML =
                  t('<strong>Aceptar</strong>: asigna oficialmente a esa obra.') + '<br>' +
                  t('<strong>Ignorar</strong>: oculta la alerta sin cambiar el cuadrante.');
              }
            } else if (info && info.kind === 'ausencias') {
              if (h) h.textContent = t('Ausencias: qué puedes hacer');
              if (p) {
                p.innerHTML =
                  t('<strong>Ausencia</strong>: confirma que no vino (el plan se mantiene).') + '<br>' +
                  t('<strong>Falta</strong>: quita la planificación de ese día.') + '<br>' +
                  t('<strong>Ignorar</strong>: oculta la alerta sin cambios.');
              }
            }
          }
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = introN;
          st.auditResolved = true;
          saveState(st);
          window.location.href = reloadAfterResolve();
        },
      });
    }

    out.push({
      when: band(introN),
      modal: true,
      title: 'Tour de la auditoría',
      body: 'Te voy a hacer un tour completo por la auditoría de fichajes: las secciones, el histórico y cómo corregir una marca. Solo te he pedido una acción en la alerta que acabas de resolver; el resto es para que sepas qué hay en cada sitio.',
      progress: prefix + ' · tour',
      nextLabel: 'Empezar el tour →',
      onShow: function () {
        clearTargets();
        placeHole(null);
        placeCardModal();
      },
      onNext: go(desvN),
    });

    [
      { n: desvN, kind: 'desviaciones', progress: prefix + ' · desviaciones' },
      { n: paraN, kind: 'paracaidistas', progress: prefix + ' · sin planificar' },
      { n: ausN, kind: 'ausencias', progress: prefix + ' · ausencias' },
    ].forEach(function (sec) {
      out.push({
        when: band(sec.n),
        manualTarget: true,
        title: AUDIT_SECTION_COPY[sec.kind].title,
        body: AUDIT_SECTION_COPY[sec.kind].body,
        progress: sec.progress,
        nextLabel: 'Siguiente →',
        onShow: function () { explainAuditSection(sec.kind); },
        onNext: go(sec.n + 1),
      });
    });

    out.push({
      when: band(histN),
      manualTarget: true,
      title: 'Histórico global',
      body: 'Aquí quedan las decisiones ya resueltas, como la de quien acabas de fichar. No hace falta pulsar ninguna fila ahora: si algún día quieres el detalle, el clic en la persona abre la actividad del día.',
      progress: prefix + ' · histórico',
      nextLabel: 'Siguiente →',
      onShow: function () {
        clearTargets();
        openAuditHistoricoSection();
        var toggle = qs('[data-tour="audit-historico-toggle"]');
        var root = qs('[data-tour="audit-historico"]');
        setTimeout(function () {
          var row = findHistoricoTourRow();
          var target = row || toggle || root;
          if (!target) {
            placeHole(null);
            placeCardModal();
            return;
          }
          if (row) row.classList.add('sp-tour-target', 'sp-tour-highlight-user');
          else target.classList.add('sp-tour-target');
          try { target.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch (e) {}
          placeHole(target);
          placeCardOutside(target);
        }, 280);
      },
      onNext: go(corrN),
    });

    out.push({
      when: band(corrN),
      manualTarget: true,
      title: 'Registrar / corregir marca',
      body: 'Arriba a la derecha, <strong>Registrar / corregir marca</strong> sirve para añadir o cambiar un fichaje a mano (hora, obra, persona). No hace falta usarlo ahora: solo recuérdalo.',
      progress: prefix + ' · corregir',
      nextLabel: 'Completar tutorial →',
      onShow: function () {
        clearTargets();
        var btn = qs('[data-tour="audit-corregir-marca"]');
        if (btn) {
          try { btn.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch (e) {}
          btn.classList.add('sp-tour-target');
          placeHole(btn);
          placeCardNear(btn);
        } else {
          placeHole(null);
          placeCardModal();
        }
      },
      onNext: go(doneN),
    });

    out.push({
      when: function () {
        var st = loadState() || {};
        return extraWhen(st) && (st.step || 0) >= doneN;
      },
      title: '',
      body: '',
      onShow: function () { onFinish(); },
    });

    return out;
  }

  function fillCredsHint(kind) {
    var st = loadState() || {};
    // Academia fichajes: textos cortos (no “acabas de crear”)
    if (st.chapter === 'fichajes') {
      if (kind === 'dni') {
        return st.createdDni
          ? (t('Introduce el') + ' <strong>DNI</strong>: <strong>' + st.createdDni + '</strong>.')
          : t('Introduce el <strong>DNI</strong>.');
      }
      if (kind === 'pin') {
        return st.createdPin
          ? (t('Introduce el') + ' <strong>PIN</strong>: <strong>' + st.createdPin + '</strong>.')
          : t('Introduce el <strong>PIN</strong>.');
      }
      return '';
    }
    var dni = (st.createdDni || '').trim();
    var pin = (st.createdPin || '').trim();
    var name = (st.createdWorkerName || '').trim();
    var who = name ? (' ' + t('de') + ' <strong>' + name + '</strong>') : (' ' + t('del operario que acabas de crear'));
    if (kind === 'dni') {
      return dni
        ? (t('Introduce el DNI') + who + ' (<strong>' + dni + '</strong>).')
        : (t('Introduce el DNI') + who + '.');
    }
    if (kind === 'pin') {
      return pin
        ? (t('Introduce el PIN') + who + ' (<strong>' + pin + '</strong>).')
        : (t('Introduce el PIN') + who + ' ' + t('(el que pusiste al crearlo).'));
    }
    return '';
  }

  function prefillLoginField(kind) {
    var st = loadState() || {};
    if (kind === 'dni') {
      var dniEl = qs('[data-tour="fichar-dni"]') || qs('#dni') || qs('#login');
      if (dniEl && st.createdDni) {
        dniEl.value = st.createdDni;
        try { dniEl.focus(); dniEl.select(); } catch (e) {}
      }
      return dniEl;
    }
    if (kind === 'pin') {
      var pinEl = qs('[data-tour="fichar-pin"]') || qs('#pin') || qs('#secret');
      if (pinEl && st.createdPin) {
        pinEl.value = st.createdPin;
        try { pinEl.type = 'text'; } catch (e2) {}
        try { pinEl.focus(); pinEl.select(); } catch (e3) {}
      } else if (pinEl) {
        try { pinEl.focus(); } catch (e4) {}
      }
      return pinEl;
    }
    return null;
  }

  function isAuthLoginTour() {
    var q = window.location.search || '';
    return pathIs(/\/auth\/login/) && (/[?&]tour=mi(?:&|$)/.test(q) || /[?&]chapter=/.test(q));
  }

  function isMiEntrar() {
    return isAuthLoginTour();
  }

  function isMiFichar() {
    var p = (window.location.pathname || '').replace(/\/$/, '') || '';
    return pathIs(/\/fichaje\/fichar/);
  }

  function fichajeEstado() {
    var root = qs('.fichaje');
    return root ? (root.getAttribute('data-estado') || '') : '';
  }

  function stepsTrabajadores() {
    return [
      // 0 — ¿Fichar? (omitir si ya se decidió en el hub / demo / sesión)
      {
        when: function () {
          if (isInicioTrack()) return false;
          if (window.__ONB_FICHAJE_ASKED__ || window.__ONB_FICHAJE_ACTIVO__) {
            return false;
          }
          var st = loadState();
          return !st || st.wantFichaje === null || typeof st.wantFichaje === 'undefined';
        },
        title: '¿Van a fichar tus operarios?',
        body: 'Si dices que sí, activamos el fichaje móvil ahora. Si no, solo planificáis (podrás activarlo después en Configuración).',
        progress: 'Inicio · 1',
        modal: true,
        choices: [
          {
            label: 'Sí, activar fichaje',
            onPick: function () {
              var st = loadState() || {};
              st.wantFichaje = true;
              st.step = 1;
              st.active = true;
              st.chapter = 'trabajadores';
              saveState(st);
              window.__ONB_FICHAJE_ASKED__ = true;
              window.__ONB_FICHAJE_ACTIVO__ = true;
              setFichaje(true).finally(function () { run(); });
            },
          },
          {
            label: 'No, solo planificar',
            onPick: function () {
              var st = loadState() || {};
              st.wantFichaje = false;
              st.step = 1;
              st.active = true;
              st.chapter = 'trabajadores';
              saveState(st);
              window.__ONB_FICHAJE_ASKED__ = true;
              window.__ONB_FICHAJE_ACTIVO__ = false;
              setFichaje(false).finally(function () { run(); });
            },
          },
        ],
      },
      // 1 — Sidebar Trabajadores
      {
        when: function () { return !pathIs(/\/admin\/personal/) && !pathIs(/\/admin\/create_user/) && !pathIs(/\/admin\/import_users/); },
        selector: '[data-tour="nav-trabajadores"]',
        title: 'Ve a Trabajadores',
        body: 'Pulsa <strong>Trabajadores</strong> en el menú de la izquierda. Desde esta sección gestionarás a tu personal: operarios internos y externos (subcontratas).',
        progress: 'Plantilla · menú',
        waitClick: true,
        advanceTo: 2,
        ifMissing: 'wait',
      },
      // 2 — Nuevo / Importar
      {
        when: function () { return pathIs(/\/admin\/personal/); },
        selector: '[data-tour="personal-actions"]',
        title: '¿Nuevo o importar?',
        body: function () {
          if (isInicioTrack()) {
            return 'Pulsa <strong>Nuevo</strong> para crear a una persona tuya (no se borra al quitar los datos de ejemplo). También puedes <strong>Importar</strong> un Excel o CSV.';
          }
          return 'Si tienes Excel, Importar internos. Si no, Nuevo y te guiamos. Casi cualquier Excel vale con nombre, apellidos y DNI.';
        },
        progress: 'Plantilla · elegir',
        waitClick: true,
        onShow: function () {
          highlightGroup('[data-tour="personal-actions"]');
          var nuevo = qs('[data-tour="personal-nuevo"]');
          var imp = qs('[data-tour="personal-import"]');
          if (nuevo) {
            nuevo.addEventListener('click', function () {
              var st = loadState();
              if (st) { st.step = 3; st.branch = 'nuevo'; saveState(st); }
            }, { once: true });
          }
          if (imp) {
            imp.addEventListener('click', function () {
              var st = loadState();
              if (st) { st.step = 20; st.branch = 'import'; saveState(st); }
            }, { once: true });
          }
        },
      },
      // 3 — Nombre
      {
        when: function () { return pathIs(/\/admin\/create_user/); },
        selector: 'input[name="name"]',
        title: 'Nombre',
        body: 'Escribe el nombre.',
        progress: 'Alta · nombre',
        onShow: function (el) { if (el) el.focus(); },
      },
      // 4 — Apellidos
      {
        when: function () { return pathIs(/\/admin\/create_user/); },
        selector: 'input[name="lastname"]',
        title: 'Apellidos',
        body: 'Apellidos del trabajador.',
        progress: 'Alta · apellidos',
        onShow: function (el) { if (el) el.focus(); },
      },
      // 5 — DNI
      {
        when: function () { return pathIs(/\/admin\/create_user/); },
        selector: 'input[name="dni"]',
        title: 'DNI / NIE',
        body: 'Con el DNI y el PIN entrará en la aplicación y podrá fichar.',
        progress: 'Alta · DNI',
        onShow: function (el) { if (el) el.focus(); },
      },
      // 6 — Acceso completo (radios + PIN)
      {
        when: function () { return pathIs(/\/admin\/create_user/); },
        selector: '[data-tour="user-acceso"]',
        title: 'Acceso del operario',
        body: function () {
          if (isInicioTrack()) {
            return 'Pon el PIN ahora (por ejemplo 2345). Lo usarás en el siguiente capítulo para fichar como esta persona. No hace falta enviar el enlace.';
          }
          return 'Elige si estableces el PIN ahora (p. ej. 2345 para probar) o envías un enlace por correo para que lo defina él. Si envías enlace, hace falta el email.';
        },
        progress: 'Alta · acceso',
        nextLabel: 'Siguiente',
        onShow: function () {
          highlightGroup('[data-tour="user-acceso"]');
        },
      },
      // 7 — Guardar
      {
        when: function () { return pathIs(/\/admin\/create_user/); },
        selector: '[data-tour="user-guardar"]',
        title: 'Guardar usuario',
        body: 'Pulsa Crear usuario. Volverás al listado para verlo creado.',
        progress: 'Alta · guardar',
        waitClick: true,
        onShow: function () {
          var form = qs('#userCreateForm') || qs('form');
          if (!form) return;
          form.addEventListener('submit', function () {
            var dni = (qs('input[name="dni"]') || {}).value || '';
            var pin = (qs('#pinInput') || qs('input[name="pin"]') || {}).value || '';
            var name = ((qs('input[name="name"]') || {}).value || '').trim();
            var last = ((qs('input[name="lastname"]') || {}).value || '').trim();
            var st = loadState();
            if (st) {
              st.createdDni = (dni || '').toUpperCase();
              if (pin) st.createdPin = String(pin);
              st.createdWorkerName = (name + ' ' + last).trim();
              st.step = 8;
              saveState(st);
            }
          }, { once: true });
        },
      },
      // 8 — Listado (persona creada)
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/admin\/personal/) && st && st.createdDni;
        },
        modal: true,
        hero: true,
        hideSkip: true,
        noSkipSection: true,
        noProgress: true,
        choicesLayout: 'stack',
        title: 'Has creado tu primera persona',
        body: function () {
          var st = loadState() || {};
          if (st.mode === 'solo') {
            return 'Ya está en plantilla. Te devolvemos a Primeros pasos para que sigas con el material o elijas el siguiente tutorial.';
          }
          if (isInicioTrack(st)) {
            return 'Has completado tu primera persona. Ahora vamos a fichar con él: entrarás en la aplicación con su DNI y PIN, ficharás en tu obra y verás el resultado en el tablero.';
          }
          return 'Ya está en plantilla. Siguiente: una obra.';
        },
        onShow: function () {
          var st = loadState() || {};
          highlightRowByDni(st.createdDni);
        },
        choices: [
          {
            label: function () {
              var st = loadState() || {};
              if (st.mode === 'solo') return 'Volver a Primeros pasos';
              if (isInicioTrack(st)) return 'Vamos a fichar';
              return 'Continuar a obras';
            },
            onPick: function () {
              var st = loadState() || {};
              if (st.mode === 'solo') {
                finishSoloAndReturn('Persona creada. Sigue reuniendo material o abre el siguiente tutorial.');
                return;
              }
              if (isInicioTrack(st)) {
                st.wantFichaje = true;
                st.ficharOficina = false;
                st.chapter = 'fichaje';
                st.step = 1;
                st.active = true;
                saveState(st);
                goFicharProbar({ chapter: 'fichaje', oficina: 0 });
                return;
              }
              saveState(copyTourFields(st, { chapter: 'obra', step: 0, active: true }));
              run();
            },
          },
        ],
      },
      { when: function () { return false; }, title: '', body: '', onShow: function () {} },
      // Import branch
      {
        when: function () {
          var st = loadState();
          return st && (st.step || 0) >= 20 && pathIs(/\/admin\/import_users/);
        },
        selector: 'main',
        title: 'Importar personal',
        body: 'Sube un Excel o CSV (nombre, apellidos, DNI). En el siguiente paso mapeas las columnas y confirmas. Estas personas se quedan aunque quites los datos de ejemplo.',
        progress: 'Importar',
        nextLabel: 'Continuar a fichar',
        onNext: function () {
          var st = loadState() || {};
          if (st.mode === 'solo') {
            finishSoloAndReturn('Personal importado. Sigue reuniendo material o abre el siguiente tutorial.');
            return;
          }
          if (isInicioTrack(st)) {
            st.wantFichaje = true;
            st.ficharOficina = false;
            st.chapter = 'fichaje';
            st.step = 1;
            st.active = true;
            saveState(st);
            goFicharProbar({ chapter: 'fichaje', oficina: 0 });
            return;
          }
          saveState(copyTourFields(st, { chapter: 'obra', step: 0, active: true }));
          run();
        },
      },
    ];
  }

  function stepsObra() {
    return [
      // 0 — Sidebar Directorio
      {
        when: function () {
          return !pathIs(/\/admin\/obras(\/|$|\?)/) &&
            !pathIs(/\/admin\/create_obra/) &&
            !pathIs(/\/admin\/import_obras/);
        },
        selector: '[data-tour="nav-directorio"]',
        title: 'Ve a Obras',
        body: 'Pulsa <strong>Obras</strong> en el menú. Ahí crearás una obra tuya, junto a las de ejemplo.',
        progress: 'Obra · menú',
        waitClick: true,
        advanceTo: 1,
        ifMissing: 'wait',
      },
      // 1 — Nueva / Importar
      {
        when: function () { return pathIs(/\/admin\/obras(\/|$|\?)/); },
        selector: '[data-tour="obra-actions"]',
        title: 'Nueva obra',
        body: function () {
          if (isInicioTrack()) {
            return 'Pulsa <strong>Nueva</strong> para crear una obra tuya (no se borra al quitar los datos de ejemplo). También puedes <strong>Importar</strong> un Excel o CSV si ya tienes el listado.';
          }
          return 'Pulsa Nueva para crear una a mano, o Importar si ya tienes listado de obras.';
        },
        progress: 'Obra · elegir',
        waitClick: true,
        onShow: function () {
          highlightGroup('[data-tour="obra-actions"]');
          var neu = qs('[data-tour="obra-nueva"]');
          var imp = qs('[data-tour="obra-import"]');
          if (neu) {
            neu.addEventListener('click', function () {
              var st = loadState();
              if (st) { st.step = 2; saveState(st); }
            }, { once: true });
          }
          if (imp) {
            imp.addEventListener('click', function () {
              var st = loadState();
              if (st) { st.step = 10; saveState(st); }
            }, { once: true });
          }
        },
      },
      // 2 — Nombre
      {
        when: function () { return pathIs(/\/admin\/create_obra/); },
        selector: '[data-tour="obra-nombre"], input[name="nombre"]',
        title: 'Nombre de la obra',
        body: 'Pon un nombre claro (tajo real o «Obra demo»).',
        progress: 'Obra · nombre',
        onShow: function () {
          var input = qs('input[name="nombre"]');
          if (input) input.focus();
        },
      },
      // 3 — Fechas (inicio + fin visibles)
      {
        when: function () { return pathIs(/\/admin\/create_obra/); },
        selector: '[data-tour="obra-inicio"]',
        title: 'Fechas',
        body: 'Inicio por defecto hoy; fin a un año vista. Puedes cambiarlas.',
        progress: 'Obra · fechas',
        onShow: function () {
          var a = qs('[data-tour="obra-inicio"]');
          var b = qs('[data-tour="obra-fin"]');
          if (a && b) {
            var top = Math.min(a.getBoundingClientRect().top, b.getBoundingClientRect().top);
            var left = Math.min(a.getBoundingClientRect().left, b.getBoundingClientRect().left);
            var right = Math.max(a.getBoundingClientRect().right, b.getBoundingClientRect().right);
            var bottom = Math.max(a.getBoundingClientRect().bottom, b.getBoundingClientRect().bottom);
            var fake = {
              getBoundingClientRect: function () {
                return { top: top, left: left, width: right - left, height: bottom - top, right: right, bottom: bottom };
              },
            };
            clearTargets();
            a.classList.add('sp-tour-target');
            b.classList.add('sp-tour-target');
            placeHole(fake);
            placeCardNear(fake);
          }
        },
      },
      // 4 — Jefe
      {
        when: function () { return pathIs(/\/admin\/create_obra/); },
        selector: '[data-tour="obra-jefe"]',
        title: 'Jefe de esta obra',
        body: 'Elige quién responde de la obra. En esta guía dejamos tu usuario admin marcado por defecto; puedes cambiarlo.',
        progress: 'Obra · jefe',
      },
      // 5 — Guardar
      {
        when: function () { return pathIs(/\/admin\/create_obra/); },
        selector: '[data-tour="obra-guardar"]',
        title: 'Crear obra',
        body: function () {
          if (isInicioTrack()) {
            return 'Pulsa Crear obra. Después darás de alta a una persona y ficharéis en esta obra.';
          }
          return 'Pulsa Crear obra. Si activaste fichaje, después probaremos a fichar como el operario.';
        },
        progress: 'Obra · guardar',
        waitClick: true,
        onShow: function () {
          var form = qs('#createObraForm');
          if (!form) return;
          form.addEventListener('submit', function () {
            var st = loadState();
            if (st) {
              st.createdObraNombre = ((qs('input[name="nombre"]') || {}).value || '').trim();
              st.pendingComplete = true;
              st.step = 6;
              saveState(st);
            }
          }, { once: true });
        },
      },
      // 6 — Felicitación / handoff
      {
        when: function () {
          var st = loadState();
          if (!st || !st.pendingComplete) return false;
          if (st.mode === 'solo') {
            st.pendingComplete = false;
            saveState(st);
            finishSoloAndReturn('Obra creada. Sigue reuniendo material o abre el siguiente tutorial.');
            return false;
          }
          return true;
        },
        modal: true,
        hero: true,
        hideSkip: true,
        noSkipSection: true,
        noProgress: true,
        choicesLayout: 'stack',
        title: 'Felicidades',
        body: 'Ya has creado tu primera obra. Se queda aunque quites los datos de ejemplo.',
        onShow: function () {
          var st = loadState() || {};
          var oid = (new URLSearchParams(window.location.search || '')).get('obra');
          if (oid) st.createdObraId = oid;
          saveState(st);
        },
        choices: [
          {
            label: 'Ver en el tablero',
            onPick: function () {
              var st = loadState() || {};
              st.pendingComplete = false;
              st.obraCelebrate = true;
              saveState(st);
              if (pathIs(/obras_detailed/)) {
                run();
                return;
              }
              var oid = st.createdObraId ? ('&obra=' + encodeURIComponent(st.createdObraId)) : '';
              window.location.href = '/admin/obras_detailed?tour=obra' + oid;
            },
          },
          {
            label: 'Continuar el siguiente tutorial',
            kind: 'ghost',
            onPick: function () {
              var st = loadState() || {};
              st.pendingComplete = false;
              st.obraCelebrate = false;
              saveState(st);
              if (isInicioTrack(st)) {
                goToInicioChapter('trabajadores', st, { stay: true });
                return;
              }
              if (st.wantFichaje) {
                st.chapter = 'fichaje';
                st.step = 0;
                st.active = true;
                saveState(st);
                run();
                return;
              }
              askFleetOrPause();
            },
          },
        ],
      },
      {
        when: function () {
          var st = loadState() || {};
          return !!(st.obraCelebrate && pathIs(/obras_detailed/));
        },
        manualTarget: true,
        title: 'Tu obra en el tablero',
        body: 'Esta es la obra que acabas de crear. Cuando quieras, continúa con el siguiente tutorial.',
        progress: 'Obra · tablero',
        nextLabel: 'Continuar el siguiente tutorial →',
        noSkipSection: true,
        onShow: function () {
          var st = loadState() || {};
          var id = st.createdObraId || (new URLSearchParams(window.location.search || '')).get('obra');
          var col = id ? qs('.kanban-col[data-obra-id="' + id + '"], .obra-card[data-obra-id="' + id + '"]') : null;
          clearTargets();
          if (col) {
            col.classList.add('sp-tour-target');
            try { col.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch (e) {}
            placeHole(col);
            placeCardDockBottom();
          } else {
            placeHole(null);
            placeCardModal();
          }
        },
        onNext: function () {
          var st = loadState() || {};
          st.obraCelebrate = false;
          saveState(st);
          if (isInicioTrack(st)) {
            goToInicioChapter('trabajadores', st, { stay: true });
            return;
          }
          if (st.wantFichaje) {
            st.chapter = 'fichaje';
            st.step = 0;
            st.active = true;
            saveState(st);
            run();
            return;
          }
          askFleetOrPause();
        },
      },
      // Import obras (asistente actual, no el tutorial antiguo)
      {
        when: function () {
          var st = loadState();
          return st && (st.step || 0) >= 10 && pathIs(/\/admin\/import_obras/) &&
            !pathIs(/\/preview/) && !qs('#import-confirm-form') && !qs('[data-tour="import-results"]');
        },
        selector: '[data-tour="import-file-zone"], [data-tour="import-file"], input[type="file"]',
        title: 'Importar desde Excel o CSV',
        body: 'Sube un Excel (.xlsx) o un CSV con tus obras. Obligatorio: una columna de <strong>Nombre</strong>. Si no trae fechas, se pone hoy y un año vista. En el siguiente paso mapeas las columnas.',
        progress: 'Obra · importar',
        noSkipSection: true,
        waitClick: true,
        ifMissing: 'wait',
        nextLabel: 'Ya lo subí →',
        onShow: function (el) {
          var help = qs('[data-tour="import-help"], [data-tour="import-intro"]');
          if (help) help.classList.add('sp-tour-target');
          if (el) {
            el.classList.add('sp-tour-target');
            placeHole(el);
            placeCardOutside(el);
          }
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 11;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return st && (st.step || 0) >= 10 && pathIs(/\/admin\/import_obras/) &&
            !!(qs('#import-confirm-form') || qs('[data-tour="import-preview-table"]') || pathIs(/\/preview/));
        },
        selector: '[data-tour="import-preview-table"], #import-confirm-form, main',
        title: 'Revisa el mapeo',
        body: 'Comprueba que cada columna del archivo encaja (Nombre, código, fechas…). Si algo está cruzado, cámbialo aquí. Luego confirma la importación.',
        progress: 'Obra · mapeo',
        noSkipSection: true,
        waitClick: true,
        nextLabel: 'Ya confirmé →',
        onShow: function (el) {
          if (el) {
            el.classList.add('sp-tour-target');
            placeHoleForList(el);
            placeCardDockBottom();
          }
        },
      },
      {
        when: function () {
          var st = loadState();
          return st && (st.step || 0) >= 10 && pathIs(/\/admin\/import_obras/) && !!qs('[data-tour="import-results"]');
        },
        modal: true,
        hero: true,
        hideSkip: true,
        noSkipSection: true,
        title: 'Felicidades',
        body: 'Tus obras ya están cargadas. Se quedan aunque quites los datos de ejemplo.',
        choicesLayout: 'stack',
        choices: [
          {
            label: 'Ver en el tablero',
            onPick: function () {
              var st = loadState() || {};
              st.pendingComplete = false;
              st.obraCelebrate = true;
              saveState(st);
              window.location.href = '/admin/obras_detailed?tour=obra';
            },
          },
          {
            label: 'Continuar el siguiente tutorial',
            kind: 'ghost',
            onPick: function () {
              var st = loadState() || {};
              st.pendingComplete = false;
              saveState(st);
              if (isInicioTrack(st)) {
                goToInicioChapter('trabajadores', st, { stay: true });
                return;
              }
              askFleetOrPause();
            },
          },
        ],
      },
    ];
  }

  function stepsFichaje() {
    return [
      // 0 — Intro en admin
      {
        when: function () {
          return !isMiEntrar() && !isMiFichar() && !pathIs(/\/sync\/auditoria/) &&
            !(((loadState() || {}).step || 0) >= 7 && pathIs(/obras_detailed/));
        },
        modal: true,
        title: 'Ahora vamos a fichar',
        body: function () {
          if (usesOwnObraFichaje()) {
            return 'Has completado tu primera persona. Ahora vamos a fichar con él: entrarás en la aplicación con su DNI y PIN, ficharás en tu obra y verás el resultado en el tablero.';
          }
          return 'Vas a entrar en la aplicación con el DNI y el PIN. Ficharás en <strong>Oficina</strong> y luego veremos auditoría.';
        },
        progress: 'Fichaje · empezar',
        primaryHref: '/admin/tour/fichaje-probar?chapter=fichaje&oficina=0',
        primaryLabel: 'Ir a fichar como operario',
        onBeforeGo: function () {
          var st = loadState() || {};
          st.chapter = 'fichaje';
          st.step = 1;
          st.active = true;
          st.wantFichaje = true;
          st.ficharOficina = !usesOwnObraFichaje(st);
          saveState(st);
          return setFichaje(true);
        },
      },
      // 1 — DNI
      {
        when: function () { return isMiEntrar(); },
        selector: '[data-tour="fichar-dni"], #dni',
        title: 'DNI del operario',
        body: 'Introduce el DNI del usuario que acabas de crear.',
        progress: 'Fichaje · DNI',
        nextLabel: 'Siguiente',
        cardPlacement: 'left-of',
        onShow: function () {
          prefillLoginField('dni');
          if (ui.card) {
            var p = ui.card.querySelector('p');
            if (p) p.innerHTML = fillCredsHint('dni');
          }
        },
      },
      // 2 — PIN
      {
        when: function () { return isMiEntrar(); },
        selector: '[data-tour="fichar-pin"], #pin',
        title: 'PIN de fichaje',
        body: 'Introduce el PIN del usuario que acabas de crear.',
        progress: 'Fichaje · PIN',
        nextLabel: 'Siguiente',
        cardPlacement: 'left-of',
        onShow: function () {
          prefillLoginField('pin');
          if (ui.card) {
            var p = ui.card.querySelector('p');
            if (p) p.innerHTML = fillCredsHint('pin');
          }
        },
      },
      // 3 — Entrar
      {
        when: function () { return isMiEntrar(); },
        selector: '[data-tour="fichar-submit"]',
        title: 'Entrar a fichar',
        body: 'Con DNI y PIN listos, pulsa Entrar para abrir la pantalla de fichaje.',
        progress: 'Fichaje · acceso',
        waitClick: true,
        nextLabel: 'Ya entré →',
        advanceTo: 4,
        cardPlacement: 'left-of',
        onShow: function () {
          // Asegurar credenciales antes de enviar
          prefillLoginField('dni');
          prefillLoginField('pin');
          var form = qs('[data-tour="fichar-login"]') || qs('form');
          if (!form) return;
          form.addEventListener('submit', function () {
            var cur = loadState();
            if (cur) { cur.step = 4; cur.chapter = 'fichaje'; saveState(cur); }
          }, { once: true });
        },
      },
      // 4 — Elegir obra (tutorial: Oficina sí o sí)
      {
        when: function () { return isMiFichar() && fichajeEstado() === 'fuera'; },
        selector: '[data-tour="fichar-obra"], #obra',
        title: 'Dónde fichas',
        body: function () {
          if (usesOwnObraFichaje()) {
            var st = loadState() || {};
            var nombre = st.createdObraNombre || t('tu obra');
            return 'Elige <strong>' + nombre + '</strong>, la obra que acabas de crear. Al fichar, SignaPlan te asigna ahí y te verás en el tablero.';
          }
          return 'En el día a día aquí sale por defecto la obra en la que estás <strong>planificado</strong>. En este tutorial usamos <strong>Oficina</strong> para generar un desvío y verlo luego en auditoría.';
        },
        progress: 'Fichaje · obra',
        cardPlacement: 'left-of',
        onShow: function (el) {
          if (usesOwnObraFichaje()) {
            ensureCreatedObraSelected(8);
            selectObraInFichajeSelect(el || qs('[data-tour="fichar-obra"], #obra'), (loadState() || {}).createdObraNombre || '');
            setTimeout(function () { ensureCreatedObraSelected(4); }, 200);
            return;
          }
          ensureOficinaSelected(8);
          selectOficinaInFichajeSelect(el || qs('[data-tour="fichar-obra"], #obra'));
          if (ui.card) {
            var p = ui.card.querySelector('p');
            if (p) {
              p.innerHTML = t('Normalmente eliges (o te sale) la obra donde estás. Aquí, para el tutorial, dejamos <strong>Oficina</strong>.');
            }
          }
          setTimeout(function () { ensureOficinaSelected(4); }, 200);
        },
      },
      // 5 — Botón entrada
      {
        when: function () { return isMiFichar() && fichajeEstado() === 'fuera'; },
        selector: '[data-tour="fichar-entrada"], [data-tipo="entrada"]',
        title: 'Fichar entrada',
        body: 'Pulsa Entrar. Queda anotado en el libro de fichajes de la empresa.',
        progress: 'Fichaje · entrada',
        waitClick: true,
        advanceTo: 6,
        cardPlacement: 'left-of',
        onShow: function (el) {
          if (usesOwnObraFichaje()) {
            ensureCreatedObraSelected(8);
            selectObraInFichajeSelect(qs('[data-tour="fichar-obra"], #obra') || el, (loadState() || {}).createdObraNombre || '');
          } else {
            ensureOficinaSelected(8);
            selectOficinaInFichajeSelect(qs('[data-tour="fichar-obra"], #obra') || el);
          }
          if (!el) el = qs('[data-tour="fichar-entrada"], [data-tipo="entrada"]');
          if (!el) return;
          el.addEventListener('click', function () {
            if (usesOwnObraFichaje()) {
              ensureCreatedObraSelected(2);
              selectObraInFichajeSelect(null, (loadState() || {}).createdObraNombre || '');
            } else {
              ensureOficinaSelected(2);
              selectOficinaInFichajeSelect();
            }
            var st = loadState();
            if (st) { st.step = 6; saveState(st); }
          }, true);
        },
      },
      // 6 — Éxito → volver al tablero
      {
        when: function () { return isMiFichar() && fichajeEstado() === 'dentro'; },
        modal: true,
        title: '¡Fichaje hecho!',
        body: function () {
          if (usesOwnObraFichaje()) {
            return 'Volvemos al tablero: esa persona ya está en tu obra (fichar también la asigna).';
          }
          return 'Volvemos al tablero para ver el resultado del fichaje.';
        },
        progress: 'Fichaje · listo',
        primaryHref: '/auth/tour-volver-admin',
        primaryLabel: 'Ver en el tablero',
        onBeforeGo: function () {
          var st = loadState() || {};
          st.step = 7;
          st.chapter = 'fichaje';
          st.active = true;
          saveState(st);
        },
        onShow: function () {
          if (ui.card) {
            var p = ui.card.querySelector('p');
            if (p) {
              if (usesOwnObraFichaje()) {
                p.innerHTML = t('Has fichado en tu obra. En el tablero verás el chip de esa persona dentro de la tarjeta.');
              } else {
                p.innerHTML = t('Has fichado en <strong>Oficina</strong>. En el tablero verás la marca según encaje o no con el plan; en auditoría resolvemos el desvío.');
              }
            }
          }
        },
      },
      // 7 — Tablero: chip en la obra + pelota
      {
        when: function () {
          var st = loadState() || {};
          if ((st.step || 0) >= 8) return false;
          return !pathIs(/\/sync\/auditoria/) && (
            pathIs(/\/admin\/obras_detailed/) ||
            (new URLSearchParams(window.location.search || '')).get('tour') === 'fichaje_done'
          );
        },
        manualTarget: true,
        title: 'La pelotita de fichaje',
        body: function () {
          return 'Ahí está la persona que has creado, en tu obra. La <strong>pelotita roja</strong> avisa: fichó sin estar planificado de antemano. Eso se revisa en Auditoría de fichajes.';
        },
        progress: 'Fichaje · tablero',
        nextLabel: 'Ir a auditoría →',
        onShow: function () {
          highlightWorkerChip();
          if (ui.card) {
            var p = ui.card.querySelector('p');
            if (p) {
              var focus = qs('.sp-tour-highlight-user') || qs('.worker-chip.sp-tour-target');
              var red = focus && focus.querySelector('.dot-danger');
              var green = focus && focus.querySelector('.dot-success, .dot-auto');
              if (!red && !green) {
                red = qs('.kanban-col .worker-chip .dot-danger');
                green = qs('.kanban-col .worker-chip .dot-success, .kanban-col .worker-chip .dot-auto');
              }
              if (red) {
                p.innerHTML = t('La pelotita <strong>roja</strong> indica que fichó sin estar en el cuadrante (o hay un desvío). En Auditoría de fichajes ves esos casos y decides qué hacer.');
              } else if (green) {
                p.innerHTML = t('La pelotita está en <strong>verde</strong>: el fichaje encaja con la planificación. Aun así te enseño Auditoría de fichajes, que es donde se revisan las marcas.');
              } else {
                p.innerHTML = t('Mira el punto de color junto al nombre: <strong>rojo</strong> = revisar en auditoría; <strong>verde</strong> = correcto.');
              }
            }
          }
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 8;
          saveState(st);
          run();
        },
      },
      // 8 — Menú: el usuario pulsa Auditoría fichajes
      {
        when: function () {
          var st = loadState() || {};
          if ((st.step || 0) < 8) return false;
          return !pathIs(/\/sync\/auditoria/) && (
            pathIs(/\/admin\/obras_detailed/) ||
            (new URLSearchParams(window.location.search || '')).get('tour') === 'fichaje_done'
          );
        },
        selector: '[data-tour="nav-auditoria-fichajes"]',
        title: 'Auditoría de fichajes',
        body: 'Pulsa <strong>Auditoría fichajes</strong> en el menú (sección Jornada). Ahí revisas fichajes sin planificar, desviaciones y ausencias.',
        progress: 'Fichaje · menú',
        waitClick: true,
        advanceTo: 9,
        ifMissing: 'wait',
        onShow: function (el) {
          if (el) {
            try { el.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch (e) {}
          }
        },
      },
      // 9 — Sección de auditoría (desviación o sin planificar)
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/sync\/auditoria/) && !(st && (st.step || 0) >= 10);
        },
        manualTarget: true,
        title: 'Qué es la auditoría',
        body: 'Aquí caen las marcas que hay que mirar: fichaje sin planificar (pelotita roja) o en una obra distinta a la del cuadrante. No es un castigo: es el sitio para aceptar, mover o ignorar.',
        progress: 'Fichaje · auditoría',
        nextLabel: 'Siguiente →',
        cardPlacement: 'away',
        onShow: function () {
          highlightAuditSection();
          var root = qs('[data-tour="audit-paracaidistas"], #collapseParacaidistas, main');
          if (root) placeCardOutside(root);
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 10;
          saveState(st);
          run();
        },
      },
    ].concat(makeAuditWalkthroughSteps({
      startStep: 10,
      progressPrefix: 'Fichaje',
      includeResolve: true,
      extraWhen: function (st) {
        return !st || st.chapter === 'fichaje' || isInicioTrack(st);
      },
      onFinish: function () {
        var st = loadState() || {};
        if (isInicioTrack(st)) {
          finishInicioTrack();
          return;
        }
        if (st.mode === 'solo') {
          markAcademiaDone('fichaje');
          finishSoloAndReturn('Fichaje y auditoría listos.');
          return;
        }
        pauseAtChapterEnd();
      },
    }));
  }

  function isImportPage() {
    return pathIs(/\/admin\/import_(obras|users|companies)/);
  }

  function isImportUploadPage() {
    return isImportPage()
      && !pathIs(/\/preview/)
      && !pathIs(/\/confirm/)
      && !pathIs(/\/results/)
      && !qs('#import-confirm-form')
      && !qs('[data-tour="import-results"]');
  }

  function isPrimerosPasos() {
    return pathIs(/\/admin\/primeros-pasos/);
  }

  function stepsImport() {
    function ensureImportEntity() {
      var st = loadState() || {};
      if (st.importEntity) return st.importEntity;
      if (pathIs(/import_users/)) st.importEntity = 'users';
      else if (pathIs(/import_companies/)) st.importEntity = 'companies';
      else if (pathIs(/import_obras/)) st.importEntity = 'obras';
      else return '';
      saveState(st);
      return st.importEntity;
    }
    function stepNum(st) {
      return Number((st && st.step) || 0);
    }
    function isImportPreviewPage() {
      if (!isImportPage()) return false;
      if (pathIs(/\/preview/)) return true;
      // Fallback: UI de preview aunque la URL no traiga /preview
      return !!(qs('#import-confirm-form') || qs('[data-tour="import-confirm"]') || qs('[data-tour="import-preview-table"]'));
    }
    function isImportResultsPage() {
      if (!isImportPage()) return false;
      if (pathIs(/\/confirm/) || pathIs(/\/results/)) return true;
      return !!qs('[data-tour="import-results"]');
    }
    function importDestinationHref() {
      ensureImportEntity();
      var st = loadState() || {};
      var ent = st.importEntity || '';
      if (ent === 'users') return '/admin/personal';
      if (ent === 'companies') return '/admin/companies';
      return '/admin/obras';
    }
    function importDestinationLabel() {
      ensureImportEntity();
      var st = loadState() || {};
      var ent = st.importEntity || '';
      if (ent === 'users') return t('Trabajadores');
      if (ent === 'companies') return t('Empresas');
      return t('Directorio');
    }
    function importNavSelector() {
      ensureImportEntity();
      var st = loadState() || {};
      var ent = st.importEntity || '';
      if (ent === 'users') return '[data-tour="nav-trabajadores"]';
      if (ent === 'companies') return '[data-tour="nav-empresas"]';
      return '[data-tour="nav-directorio"]';
    }
    function isImportDestinationPage() {
      ensureImportEntity();
      var st = loadState() || {};
      var ent = st.importEntity || 'obras';
      if (ent === 'users') return pathIs(/\/admin\/personal/);
      if (ent === 'companies') return pathIs(/\/admin\/companies/);
      return pathIs(/\/admin\/obras(\/|$|\?)/) && !pathIs(/obras_detailed/);
    }
    function importDoneMap() {
      var fromWindow = window.__ONB_IMPORT_DONE__ || {};
      var fromStorage = {};
      try {
        fromStorage = JSON.parse(sessionStorage.getItem('signaplan_import_done') || '{}') || {};
      } catch (e) {
        fromStorage = {};
      }
      return {
        obras: !!(fromWindow.obras || fromStorage.obras),
        users_internos: !!(fromWindow.users_internos || fromStorage.users_internos),
        users_externos: !!(fromWindow.users_externos || fromStorage.users_externos),
        companies: !!(fromWindow.companies || fromStorage.companies),
      };
    }
    function currentImportDoneKey() {
      ensureImportEntity();
      var st = loadState() || {};
      if (st.importEntity === 'companies') return 'companies';
      if (st.importEntity === 'users') {
        return st.importMode === 'externos' ? 'users_externos' : 'users_internos';
      }
      return 'obras';
    }
    function markImportDoneClient(key) {
      if (!key) key = currentImportDoneKey();
      var m = importDoneMap();
      m[key] = true;
      window.__ONB_IMPORT_DONE__ = m;
      try { sessionStorage.setItem('signaplan_import_done', JSON.stringify(m)); } catch (e) {}
    }
    function importListExplainTitle() {
      ensureImportEntity();
      var st = loadState() || {};
      var ent = st.importEntity || 'obras';
      if (ent === 'users') return t('Personal importado');
      if (ent === 'companies') return t('Empresas importadas');
      return t('Obras importadas');
    }
    function importListExplainBody() {
      ensureImportEntity();
      var st = loadState() || {};
      var ent = st.importEntity || 'obras';
      if (ent === 'users') {
        return t('Este es el listado de personal que acabas de importar. Cada fila es una persona.');
      }
      if (ent === 'companies') {
        return t('Este es el listado de empresas/subcontratas que acabas de importar. Cada fila es una empresa.');
      }
      return t('Este es el listado de obras que acabas de importar. Cada fila es una obra.');
    }

    return [
      {
        when: function () { return !isImportPage() && !isImportDestinationPage(); },
        modal: true,
        choicesLayout: 'stack',
        noSkipSection: true,
        title: 'Importar desde Excel',
        body: 'Elige qué listado quieres subir. Los que ya hayas importado aparecen con un tick.',
        progress: 'Importar · empezar',
        choices: [
          {
            label: 'Obras',
            done: !!importDoneMap().obras,
            onPick: function () {
              var st = loadState() || {};
              st.step = 1;
              st.chapter = 'import';
              st.active = true;
              st.importEntity = 'obras';
              st.importMode = null;
              saveState(st);
              window.location.href = '/admin/import_obras?desde=primeros-pasos';
            },
          },
          {
            label: 'Personal interno',
            done: !!importDoneMap().users_internos,
            onPick: function () {
              var st = loadState() || {};
              st.step = 1;
              st.importEntity = 'users';
              st.importMode = 'internos';
              saveState(st);
              window.location.href = '/admin/import_users?modo=internos&desde=primeros-pasos';
            },
          },
          {
            label: 'Personal externo',
            done: !!importDoneMap().users_externos,
            onPick: function () {
              var st = loadState() || {};
              st.step = 1;
              st.importEntity = 'users';
              st.importMode = 'externos';
              saveState(st);
              window.location.href = '/admin/import_users?modo=externos&desde=primeros-pasos';
            },
          },
          {
            label: 'Subcontratas / empresas externas',
            done: !!importDoneMap().companies,
            onPick: function () {
              var st = loadState() || {};
              st.step = 1;
              st.importEntity = 'companies';
              st.importMode = null;
              saveState(st);
              window.location.href = '/admin/import_companies?desde=primeros-pasos';
            },
          },
        ],
      },
      // 1 — Título + explicación juntos (lo que hay que leer)
      {
        when: function () {
          var st = loadState();
          return isImportUploadPage() && st && stepNum(st) <= 1;
        },
        selector: '[data-tour="import-intro"]',
        noSkipSection: true,
        title: 'Lee la explicación de la página',
        body: 'En la zona resaltada está qué hace esta importación y qué columnas hacen falta. Léelo ahí. Luego pulsa el botón azul <strong>Siguiente</strong>.',
        progress: 'Importar · explicación',
        ifMissing: 'wait',
        nextLabel: 'Siguiente',
        onNext: function () {
          var st = loadState() || {};
          st.step = 2;
          saveState(st);
          run();
        },
      },
      // 2 — Archivo
      {
        when: function () {
          var st = loadState();
          return isImportUploadPage() && st && stepNum(st) === 2;
        },
        selector: '[data-tour="import-file-zone"]',
        noSkipSection: true,
        title: 'Elige el archivo',
        body: 'Selecciona el Excel o CSV. Al elegirlo, te llevamos al botón Continuar.',
        progress: 'Importar · archivo',
        ifMissing: 'wait',
        nextLabel: 'Ya lo elegí →',
        onShow: function () {
          var input = qs('[data-tour="import-file"]') || qs('#file');
          if (!input) return;
          input.addEventListener('change', function () {
            if (!input.files || !input.files.length) return;
            var st = loadState() || {};
            st.step = 3;
            saveState(st);
            setTimeout(function () { run(); }, 200);
          }, { once: true });
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 3;
          saveState(st);
          run();
        },
      },
      // 3 — Continuar
      {
        when: function () {
          var st = loadState();
          return isImportUploadPage() && st && stepNum(st) >= 3 && stepNum(st) < 4;
        },
        selector: '[data-tour="import-submit"]',
        noSkipSection: true,
        title: 'Continuar',
        body: 'Pulsa <strong>Continuar</strong> para mapear columnas y ver la vista previa.',
        progress: 'Importar · subir',
        waitClick: true,
        advanceTo: 4,
        ifMissing: 'wait',
        nextLabel: 'Ya continué →',
        onShow: function (el) {
          if (!el) return;
          el.addEventListener('click', function () {
            var st = loadState();
            if (st) { st.step = 4; saveState(st); }
          }, { once: true });
        },
      },
      // 4 — Preview: Revisar (banner)
      {
        when: function () {
          var st = loadState();
          return isImportPreviewPage() && st && stepNum(st) === 4;
        },
        modal: true,
        reviewMode: true,
        noSkipSection: true,
        title: 'Revisa el listado',
        body: 'Pulsa <strong>Revisar</strong> para quitar este cartel y trabajar con la tabla. Puedes desticar filas que no quieras importar. Quedará una barra arriba; cuando acabes, <strong>Volver a la guía</strong>.',
        progress: 'Importar · asistente',
        reviewLabel: 'Revisar →',
        nextLabel: 'Terminar guía →',
        bannerTitle: 'Guía en pausa',
        bannerBody: 'Revisa el mapeo, destica lo que no quieras y, cuando estés listo, vuelve a la guía para confirmar.',
        onResumeFromBanner: function () {
          var st = loadState() || {};
          st.step = 5;
          saveState(st);
          run();
        },
        onNext: function () {
          hideTourBanner();
          pauseAtChapterEnd();
        },
      },
      // 5 — Confirmar importación (spotlight en el botón + mensaje siempre a la vista)
      {
        when: function () {
          var st = loadState();
          if (!(st && stepNum(st) === 5)) return false;
          return isImportPreviewPage()
            || !!qs('[data-tour="import-confirm"]')
            || !!qs('#import-confirm-form');
        },
        selector: '[data-tour="import-confirm"]',
        manualTarget: true,
        noSkipSection: true,
        title: 'Confirma la importación',
        body: 'Pulsa el botón resaltado <strong>Confirmar importación</strong> (solo las filas ticadas). Si prefieres no confirmar ahora, usa <strong>Saltar</strong>.',
        progress: 'Importar · confirmar',
        waitClick: true,
        advanceTo: 6,
        ifMissing: 'wait',
        nextLabel: 'Saltar →',
        onShow: function () {
          var btn = qs('[data-tour="import-confirm"]');
          spotlightWithCard(btn);
          if (btn) bindNavClick(btn, 6);
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 7;
          saveState(st);
          run();
        },
      },
      // 6 — Resumen (tras confirmar de verdad)
      {
        when: function () {
          var st = loadState();
          return isImportResultsPage() && st && stepNum(st) === 6;
        },
        selector: '[data-tour="import-results"]',
        noSkipSection: true,
        title: 'Resumen de lo importado',
        body: 'Aquí tienes el resultado: creados, duplicados u omitidos. Pulsa <strong>Siguiente</strong> para ir al listado en el menú.',
        progress: 'Importar · resumen',
        ifMissing: 'wait',
        nextLabel: 'Siguiente',
        onShow: function (el) {
          markImportDoneClient();
          if (el) spotlightWithCard(el);
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 7;
          saveState(st);
          run();
        },
      },
      // 7 — Navbar: Directorio / Trabajadores / Empresas
      {
        when: function () {
          var st = loadState();
          if (!(st && stepNum(st) === 7)) return false;
          if (isImportDestinationPage()) return false;
          return isImportResultsPage() || isImportPreviewPage() || isImportPage()
            || !!qs('[data-tour="import-confirm"]') || !!qs('[data-tour="import-results"]');
        },
        selector: '[data-tour="nav-directorio"]',
        manualTarget: true,
        noSkipSection: true,
        title: function () { return t('Ve a') + ' ' + importDestinationLabel(); },
        body: function () {
          return t('En el menú de la <strong>izquierda</strong>, pulsa') + ' <strong>' +
            importDestinationLabel() +
            '</strong> ' + t('para ver el listado.');
        },
        progress: 'Importar · menú',
        waitClick: true,
        advanceTo: 8,
        ifMissing: 'wait',
        nextLabel: 'Ya estoy →',
        onShow: function () {
          var el = qs(importNavSelector()) || qs('[data-tour="nav-directorio"]');
          spotlightWithCard(el);
          if (el) bindNavClick(el, 8);
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 8;
          saveState(st);
          window.location.href = importDestinationHref();
        },
      },
      // 8 — Explicación del listado (mensaje SIEMPRE visible + listado resaltado)
      {
        when: function () {
          var st = loadState();
          return !!(st && stepNum(st) === 8 && isImportDestinationPage());
        },
        selector: '[data-tour="import-list-dest"], #obrasTable, main .admin-data-table, main',
        manualTarget: true,
        noSkipSection: true,
        title: function () { return importListExplainTitle(); },
        body: function () { return importListExplainBody(); },
        progress: 'Importar · listado',
        ifMissing: 'wait',
        nextLabel: 'Volver a primeros pasos →',
        onShow: function () {
          markImportDoneClient();
          // Preferir la tabla real: el wrapper .admin-table-scroll suele ser mucho más alto
          var el = qs('#obrasTable')
            || qs('[data-tour="import-list-dest"] table')
            || qs('main .admin-data-table')
            || qs('[data-tour="import-list-dest"]')
            || qs('main');
          ensureUi();
          if (ui.card) ui.card.style.display = '';
          if (el) {
            el.classList.add('sp-tour-target');
            try { el.scrollIntoView({ block: 'nearest', behavior: 'auto' }); } catch (e) {}
            placeHoleForList(el);
          } else {
            placeHole(null);
          }
          // Mensaje centrado, por encima del listado
          ui.card.classList.remove('is-modal');
          ui.card.style.transform = 'translateX(-50%)';
          ui.card.style.top = '18%';
          ui.card.style.left = '50%';
          ui.card.style.width = Math.min(380, window.innerWidth - 32) + 'px';
          ui.card.style.zIndex = '12060';
        },
        onNext: function () {
          markImportDoneClient();
          var st = loadState() || {};
          st.step = 0;
          st.chapter = 'import';
          st.active = true;
          saveState(st);
          window.location.href = '/admin/primeros-pasos?tour=import';
        },
      },
    ];
  }

  function stepsTableroLeer() {
    return [
      {
        when: function () { return !pathIs(/\/admin\/obras_detailed/) && !pathIs(/\/jefe\/obras_detailed/); },
        selector: '[data-tour="nav-tablero"], a[href*="obras_detailed"]',
        title: 'Ve al Tablero',
        body: 'Pulsa <strong>Tablero</strong> en el menú. Ahí ves el día: quién está libre y quién está en cada obra.',
        progress: function () { return inicioProgressLabel('tablero_leer', t('menú')); },
        waitClick: true,
        advanceTo: 1,
        ifMissing: 'wait',
      },
      {
        when: function () {
          var st = loadState() || {};
          return isInicioTrack(st) && pathIs(/obras_detailed/) && !st.welcomeDone;
        },
        modal: true,
        hero: true,
        hideSkip: true,
        noSkipSection: true,
        noProgress: true,
        choicesLayout: 'stack',
        title: 'Vamos a hacer un recorrido guiado',
        body: function () {
          var base = 'Te iremos indicando qué pulsar, paso a paso: tablero, asignar gente, crear una obra y una persona tuyas, y probar el fichaje.';
          if (window.__DEMO_DATA_ACTIVA__) {
            return base + '<br><br>Hemos cargado <strong>datos de ejemplo</strong> (obras, personas y vehículos) para que puedas trastear. Cuando quieras los quitas: se borran los ejemplos y se queda lo que hayas creado tú.';
          }
          return base;
        },
        choices: [
          {
            label: 'Iniciar el tutorial',
            onPick: function () {
              var st = loadState() || {};
              st.welcomeDone = true;
              st.active = true;
              saveState(st);
              run();
            },
          },
          {
            label: 'Saltar sin tutorial',
            kind: 'ghost',
            onPick: function () { skipEntireInicio(); },
          },
        ],
      },
      {
        when: function () {
          var st = loadState() || {};
          return pathIs(/obras_detailed/) && (!isInicioTrack(st) || !!st.welcomeDone) && (st.step || 0) < 3;
        },
        selector: '[data-tour="tablero-fecha"], .timeline-header-wrapper',
        title: 'El día que estás viendo',
        body: 'Arriba eliges la fecha: te posicionas en el día cuyos datos quieres ver. Usa las cápsulas o el selector; el tablero se actualiza con ese día.',
        progress: function () { return inicioProgressLabel('tablero_leer', t('fecha')); },
        nextLabel: 'Siguiente →',
        noScroll: true,
        onNext: function () {
          var st = loadState() || {};
          st.step = 3;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState() || {};
          return pathIs(/obras_detailed/) && (st.step || 0) >= 3 && (st.step || 0) < 4;
        },
        selector: '[data-tour="tablero-libres"], .kanban-libres-panel',
        title: 'Operarios libres',
        body: 'Aquí están las personas sin obra ese día. Desde esta columna las arrastras para asignarlas. (no es el único método para asignar personal)',
        progress: function () { return inicioProgressLabel('tablero_leer', t('libres')); },
        nextLabel: 'Siguiente →',
        noScroll: true,
        onShow: function (el) {
          if (!el) return;
          requestAnimationFrame(function () {
            placeHole(el);
            placeCardNear(el);
          });
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 4;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState() || {};
          return pathIs(/obras_detailed/) && (st.step || 0) >= 4 && (st.step || 0) < 5;
        },
        manualTarget: true,
        noScroll: true,
        title: 'Las obras del día',
        body: 'A la derecha están las obras en curso. Cada columna es una obra; dentro verás quién está asignado ese día.',
        progress: function () { return inicioProgressLabel('tablero_leer', t('obras')); },
        nextLabel: 'Siguiente →',
        onShow: function () {
          clearTargets();
          var wrap = qs('#kanbanWorksWrapper');
          var scrollLeft = wrap ? wrap.scrollLeft : 0;
          var scrollTop = wrap ? wrap.scrollTop : 0;
          var pageScroll = window.scrollY || document.documentElement.scrollTop || 0;
          var obras = Array.prototype.slice.call(
            document.querySelectorAll('#kanbanWorksWrapper > .kanban-col-wrapper, #kanbanWorksWrapper > .obra-card, #kanbanWorksWrapper > .kanban-col'),
            0,
            3
          );
          placeHoleUnion(obras, { clampViewport: true, minTop: 72 });
          placeCardDockBottom();
          if (wrap) {
            wrap.scrollLeft = scrollLeft;
            wrap.scrollTop = scrollTop;
          }
          try { window.scrollTo(0, pageScroll); } catch (e) { /* ignore */ }
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 5;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState() || {};
          return pathIs(/obras_detailed/) && (st.step || 0) >= 5;
        },
        title: '',
        body: '',
        onShow: function () { pauseAtChapterEnd(); },
      },
    ];
  }

  function stepsTableroAsignar() {
    return [
      {
        when: function () { return !pathIs(/\/admin\/obras_detailed/) && !pathIs(/\/jefe\/obras_detailed/); },
        selector: '[data-tour="nav-tablero"], a[href*="obras_detailed"]',
        title: 'Ve al Tablero',
        body: 'Pulsa <strong>Tablero</strong> para asignar arrastrando.',
        progress: function () { return inicioProgressLabel('tablero_asignar', t('menú')); },
        waitClick: true,
        advanceTo: 1,
        ifMissing: 'wait',
      },
      {
        when: function () {
          var st = loadState() || {};
          return pathIs(/obras_detailed/) && !st.assignedOk && (st.step || 0) < 2;
        },
        manualTarget: true,
        title: 'Asigna arrastrando',
        body: 'Coge un operario de <strong>libres</strong> y suéltalo en el cuerpo de una tarjeta de obra. Queda asignado a ese día, sin calendario.',
        progress: function () { return inicioProgressLabel('tablero_asignar', t('arrastrar')); },
        nextLabel: 'Ya lo asigné →',
        requireGate: function () {
          return !!(loadState() || {}).assignedOk;
        },
        gateRetry: true,
        gateFail: 'Aún no hay asignación. Arrastra un chip de libres al cuerpo de una obra.',
        onShow: function () {
          clearTargets();
          var chip = qs('#list-libres-body .worker-chip');
          var obraCol = qs('#kanbanWorksWrapper .kanban-col, #kanbanWorksWrapper .obra-card');
          var drop = obraCol
            ? (obraCol.querySelector('.worker-list-body') || obraCol)
            : null;
          if (chip) chip.classList.add('sp-tour-target');
          if (drop) drop.classList.add('sp-tour-target');
          if (chip || drop) {
            placeHoleUnion([chip, drop || obraCol]);
          } else {
            placeHole(qs('#kanbanContainer') || qs('main'));
          }
          placeCardClearOfKanban();
          var advanced = false;
          function goNext() {
            if (advanced) return;
            advanced = true;
            try {
              if (window.jQuery) {
                window.jQuery(document).off('sp-kanban-assigned.spTourAsignar');
              }
            } catch (e) { /* ignore */ }
            var st = loadState() || {};
            st.assignedOk = true;
            st.step = 2;
            saveState(st);
            run();
          }
          try {
            if (window.jQuery) {
              window.jQuery(document).off('sp-kanban-assigned.spTourAsignar');
              window.jQuery(document).on('sp-kanban-assigned.spTourAsignar', goNext);
            }
          } catch (e2) { /* ignore */ }
        },
        onNext: function () {
          try {
            if (window.jQuery) {
              window.jQuery(document).off('sp-kanban-assigned.spTourAsignar');
            }
          } catch (e) { /* ignore */ }
          var st = loadState() || {};
          st.step = 2;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState() || {};
          return pathIs(/obras_detailed/) && (st.assignedOk || (st.step || 0) >= 2) && (st.step || 0) < 3 && !st.sawCalendario && !assignmentModalOpen();
        },
        selector: '[data-tour="obra-calendar"], .btn-obra-calendar',
        title: 'Calendario de la obra',
        body: 'Ahora abre el calendario de una obra (el icono). Ahí asignas un rango de días, no solo el día del tablero.',
        progress: function () { return inicioProgressLabel('tablero_asignar', t('calendario')); },
        hideNext: true,
        noSkipSection: true,
        noScroll: true,
        ifMissing: 'wait',
        onShow: function (el) {
          if (el) {
            el.classList.add('sp-tour-target');
            placeHole(el);
            placeCardNear(el);
          }
          var started = false;
          function goCal() {
            if (started) return;
            started = true;
            if (window.__spTourCalOpenPoll) {
              clearInterval(window.__spTourCalOpenPoll);
              window.__spTourCalOpenPoll = null;
            }
            startCalendarioFromBoard();
          }
          document.querySelectorAll('.btn-obra-calendar, [data-tour="obra-calendar"]').forEach(function (btn) {
            btn.addEventListener('click', function () {
              setTimeout(goCal, 80);
            });
          });
          if (window.__spTourCalOpenPoll) clearInterval(window.__spTourCalOpenPoll);
          window.__spTourCalOpenPoll = setInterval(function () {
            if (assignmentModalOpen()) {
              clearInterval(window.__spTourCalOpenPoll);
              window.__spTourCalOpenPoll = null;
              goCal();
            }
          }, 200);
        },
      },
      {
        when: function () {
          var st = loadState() || {};
          return pathIs(/obras_detailed/) && !st.sawCalendario && assignmentModalOpen();
        },
        title: '',
        body: '',
        onShow: function () { startCalendarioFromBoard(); },
      },
      {
        when: function () {
          var st = loadState() || {};
          return pathIs(/obras_detailed/) && (st.step || 0) >= 3;
        },
        title: '',
        body: '',
        onShow: function () { pauseAtChapterEnd(); },
      },
    ];
  }

  function stepsCalendario() {
    function advanceCal(to) {
      var st = loadState() || {};
      st.step = to;
      saveState(st);
      run();
    }
    return [
      {
        when: function () {
          var st = loadState() || {};
          return pathIs(/obras_detailed/) && !assignmentModalOpen() && (st.step || 0) < 8;
        },
        selector: '[data-tour="obra-calendar"], .btn-obra-calendar',
        title: 'Abre el calendario',
        body: 'Pulsa el icono de calendario de una obra. Se abre vacío: tú eliges persona y fechas.',
        progress: 'Calendario · abrir',
        waitClick: true,
        hideNext: true,
        noSkipSection: true,
        ifMissing: 'wait',
        onShow: function (el) {
          function go() {
            if (assignmentModalOpen()) advanceCal(1);
          }
          document.querySelectorAll('.btn-obra-calendar, [data-tour="obra-calendar"]').forEach(function (btn) {
            btn.addEventListener('click', function () {
              setTimeout(go, 80);
            });
          });
          if (window.__spTourCalOpenPoll) clearInterval(window.__spTourCalOpenPoll);
          window.__spTourCalOpenPoll = setInterval(function () {
            if (assignmentModalOpen()) {
              clearInterval(window.__spTourCalOpenPoll);
              window.__spTourCalOpenPoll = null;
              go();
            }
          }, 200);
        },
      },
      {
        when: function () {
          var st = loadState() || {};
          return assignmentModalOpen() && (st.step || 0) < 2 && !assignmentConflictOpen();
        },
        selector: '#modal-calendar-container, #assignmentModal.show .fc',
        title: 'Rango a partir de hoy',
        body: function () {
          var d = new Date();
          var dd = ('0' + d.getDate()).slice(-2);
          var mm = ('0' + (d.getMonth() + 1)).slice(-2);
          return 'Pulsa un día o arrastra varios <strong>a partir de hoy</strong> (' + dd + '/' + mm +
            '). Los días pasados no se pueden asignar: por eso parece que no va si arrastras el 13 estando a día 17. Prueba hoy y un par de días hacia adelante.';
        },
        progress: 'Calendario · días',
        noScroll: true,
        noSkipSection: true,
        hideNext: true,
        cardPlacement: 'away',
        requireGate: calendarGhostPresent,
        gateRetry: true,
        gateFail: 'Selecciona un día o arrastra un rango a partir de hoy.',
        onShow: function (el) {
          if (el) {
            el.classList.add('sp-tour-target');
            placeHole(el);
            placeCardOutside(el);
          }
          var tries = 0;
          var timer = setInterval(function () {
            tries += 1;
            if (calendarGhostPresent()) {
              clearInterval(timer);
              advanceCal(2);
            } else if (tries > 80 || !assignmentModalOpen()) {
              clearInterval(timer);
            }
          }, 400);
        },
      },
      {
        when: function () {
          var st = loadState() || {};
          return assignmentModalOpen() && (st.step || 0) >= 2 && (st.step || 0) < 3 && !assignmentConflictOpen();
        },
        manualTarget: true,
        title: 'Este es el bloque que acabas de crear',
        body: 'Ese bloque del calendario es la <strong>nueva asignación</strong>. Abajo, en Nueva Asignación, tienes las mismas fechas.',
        progress: 'Calendario · bloque',
        noScroll: true,
        noSkipSection: true,
        cardPlacement: 'away',
        nextLabel: 'Siguiente →',
        onShow: function () {
          clearTargets();
          var cal = qs('#assignmentModal #modal-calendar-container, #modal-calendar-container');
          var ghost = qs('#assignmentModal .fc-ghost-event, .fc-ghost-event');
          if (ghost) {
            ghost.classList.add('sp-tour-target');
            placeHole(ghost);
            placeCardOutside(cal || ghost);
          } else if (cal) {
            cal.classList.add('sp-tour-target');
            placeHole(cal);
            placeCardOutside(cal);
          } else {
            placeHole(null);
            placeCardModal();
          }
        },
        onNext: function () { advanceCal(3); },
      },
      {
        when: function () {
          var st = loadState() || {};
          return assignmentModalOpen() && (st.step || 0) >= 3 && (st.step || 0) < 4 && !assignmentConflictOpen();
        },
        selector: '#assignmentModal.show .univ-calendar-panel, .univ-calendar-panel',
        title: 'También desde Nueva Asignación',
        body: 'Abajo, en <strong>Nueva Asignación</strong>, puedes marcar el mismo rango con las fechas de inicio y fin, sin arrastrar en el calendario.',
        progress: 'Calendario · panel',
        noScroll: true,
        noSkipSection: true,
        cardPlacement: 'away',
        ifMissing: 'wait',
        nextLabel: 'Siguiente →',
        onShow: function (el) {
          var panel = el || qs('#assignmentModal.show .univ-calendar-panel') || qs('.univ-calendar-panel');
          var dates = panel && panel.querySelector('[id$="-start"]');
          var target = (dates && dates.closest('.row')) || dates || panel;
          if (target) {
            target.classList.add('sp-tour-target');
            placeHole(target);
            placeCardOutside(panel || target);
          }
        },
        onNext: function () { advanceCal(4); },
      },
      {
        when: function () {
          var st = loadState() || {};
          return assignmentModalOpen() && (st.step || 0) >= 4 && (st.step || 0) < 5 && !assignmentConflictOpen();
        },
        selector: '#assignmentModal.show .univ-worker-select, .univ-worker-select',
        title: 'Elige a la persona',
        body: 'En el desplegable busca un trabajador por nombre y asígnalo a esos días.',
        progress: 'Calendario · persona',
        noScroll: true,
        noSkipSection: true,
        hideNext: true,
        cardPlacement: 'away',
        ifMissing: 'wait',
        requireGate: calendarWorkerSelected,
        gateRetry: true,
        gateFail: 'Elige un trabajador en el desplegable.',
        onShow: function (el) {
          if (el) {
            try { el.closest('.univ-worker-row, .modal-body').classList.add('sp-tour-target'); } catch (e) {}
            el.classList.add('sp-tour-target');
            placeHole(el.closest('.univ-worker-row') || el);
            placeCardOutside(el.closest('.univ-calendar-panel') || el);
          }
          try {
            if (window.jQuery) {
              window.jQuery(document).off('change.spTourCalWorker');
              window.jQuery(document).on('change.spTourCalWorker', '#assignmentModal .univ-worker-select', function () {
                if (calendarWorkerSelected()) {
                  window.jQuery(document).off('change.spTourCalWorker');
                  advanceCal(5);
                }
              });
            }
          } catch (e2) { /* ignore */ }
        },
      },
      {
        when: function () {
          var st = loadState() || {};
          return assignmentModalOpen() && (st.step || 0) >= 5 && (st.step || 0) < 6 && !assignmentConflictOpen();
        },
        selector: '#assignmentModal.show .univ-vehicle-toggle, .univ-vehicle-toggle',
        title: 'Añade un vehículo',
        body: 'Activa <strong>Asignar vehículo</strong>. Luego te pediré que elijas el coche.',
        progress: 'Calendario · flota',
        noScroll: true,
        noSkipSection: true,
        hideNext: true,
        cardPlacement: 'away',
        ifMissing: 'wait',
        requireGate: calendarVehicleToggleOn,
        gateRetry: true,
        gateFail: 'Activa «Asignar vehículo».',
        onShow: function (el) {
          var row = el && el.closest ? el.closest('.univ-worker-row-vehicle, .custom-control') : null;
          var target = row || el;
          if (target) {
            target.classList.add('sp-tour-target');
            placeHole(target);
            placeCardOutside(target);
          }
          if (calendarVehicleToggleOn()) {
            advanceCal(6);
            return;
          }
          try {
            if (window.jQuery) {
              window.jQuery(document).off('change.spTourCalVehTog');
              window.jQuery(document).on(
                'change.spTourCalVehTog',
                '#assignmentModal .univ-vehicle-toggle',
                function () {
                  if (calendarVehicleToggleOn()) {
                    window.jQuery(document).off('change.spTourCalVehTog');
                    setTimeout(function () { advanceCal(6); }, 120);
                  }
                }
              );
            }
          } catch (e2) { /* ignore */ }
        },
      },
      {
        when: function () {
          var st = loadState() || {};
          return assignmentModalOpen() && (st.step || 0) >= 6 && (st.step || 0) < 7 && !assignmentConflictOpen();
        },
        selector: '#assignmentModal.show .univ-vehicle-select, .univ-vehicle-select',
        title: 'Elige el coche',
        body: 'En el desplegable elige un vehículo de la flota. Así el bloque lleva persona y coche.',
        progress: 'Calendario · coche',
        noScroll: true,
        noSkipSection: true,
        hideNext: true,
        cardPlacement: 'away',
        ifMissing: 'wait',
        requireGate: calendarVehicleSelected,
        gateRetry: true,
        gateFail: 'Elige un coche de la flota.',
        onShow: function (el) {
          var wrap = el && el.closest ? el.closest('.univ-vehicle-wrap, .univ-worker-row-vehicle') : null;
          var target = wrap || el;
          if (target) {
            target.classList.add('sp-tour-target');
            placeHole(target);
            placeCardOutside(target);
          }
          if (calendarVehicleSelected()) {
            advanceCal(7);
            return;
          }
          try {
            if (window.jQuery) {
              window.jQuery(document).off('change.spTourCalVeh');
              window.jQuery(document).on(
                'change.spTourCalVeh',
                '#assignmentModal .univ-vehicle-select',
                function () {
                  if (calendarVehicleSelected()) {
                    window.jQuery(document).off('change.spTourCalVeh');
                    advanceCal(7);
                  }
                }
              );
            }
          } catch (e2) { /* ignore */ }
        },
      },
      {
        when: function () {
          var st = loadState() || {};
          return assignmentModalOpen() && (st.step || 0) >= 7 && (st.step || 0) < 8 && !assignmentConflictOpen();
        },
        selector: '#assignmentModal.show [id$="-save"]',
        title: 'Guarda la asignación',
        body: 'Pulsa el botón con el tic (abajo, junto a las fechas) para aceptar la asignación.',
        progress: 'Calendario · guardar',
        waitClick: true,
        hideNext: true,
        noSkipSection: true,
        noScroll: true,
        cardPlacement: 'away',
        ifMissing: 'wait',
        onShow: function (el) {
          if (el) {
            el.classList.add('sp-tour-target');
            placeHole(el);
            placeCardOutside(el.closest('.univ-calendar-panel') || el);
          }
          try {
            if (window.jQuery) {
              window.jQuery(document).off('sp-calendar-assigned.spTourCal');
              window.jQuery(document).on('sp-calendar-assigned.spTourCal', function () {
                window.jQuery(document).off('sp-calendar-assigned.spTourCal');
                var st = loadState() || {};
                st.step = 8;
                st.sawCalendario = true;
                saveState(st);
                setTimeout(function () { run(); }, 400);
              });
            }
          } catch (e2) { /* ignore */ }
          if (window.__spTourSaveConflictPoll) clearInterval(window.__spTourSaveConflictPoll);
          window.__spTourSaveConflictPoll = setInterval(function () {
            if (assignmentConflictOpen()) {
              if (ui.card) ui.card.style.display = 'none';
              if (ui.backdrop) ui.backdrop.style.display = 'none';
              placeHole(null);
            } else if (!assignmentModalOpen()) {
              clearInterval(window.__spTourSaveConflictPoll);
              window.__spTourSaveConflictPoll = null;
            } else if (ui.card && ui.card.style.display === 'none') {
              ui.card.style.display = '';
              if (ui.backdrop) ui.backdrop.style.display = '';
              run();
            }
          }, 280);
        },
      },
      {
        when: function () {
          var st = loadState() || {};
          return isInicioTrack(st) && (st.step || 0) >= 8;
        },
        modal: true,
        hero: true,
        hideSkip: true,
        noSkipSection: true,
        noProgress: true,
        choicesLayout: 'stack',
        title: 'Muy bien',
        body: 'Has completado tus dos primeras asignaciones (arrastrar un día y asignar un rango en el calendario). Ahora te voy a explicar lo que es Obras.',
        choices: [
          {
            label: 'Iniciar',
            onPick: function () {
              var st = loadState() || {};
              st.sawCalendario = true;
              st.assignedOk = true;
              st.chainResume = null;
              saveState(st);
              goToInicioChapter('obra', st, { stay: true });
            },
          },
        ],
      },
      {
        when: function () {
          var st = loadState() || {};
          return !isInicioTrack(st) && (st.step || 0) >= 8;
        },
        title: '',
        body: '',
        onShow: function () { pauseAtChapterEnd(); },
      },
    ];
  }

  function stepsTableroBasico() {
    return [
      {
        when: function () { return !pathIs(/\/admin\/obras_detailed/) && !pathIs(/\/jefe\/obras_detailed/); },
        selector: '[data-tour="nav-tablero"], a[href*="obras_detailed"]',
        title: 'Ve al Tablero',
        body: 'Pulsa <strong>Tablero</strong> en el menú. Ahí ves obras y gente día a día.',
        progress: 'Tablero · menú',
        waitClick: true,
        advanceTo: 1,
        ifMissing: 'wait',
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/obras_detailed/) && (st.step || 0) < 2;
        },
        selector: '[data-tour="tablero-fecha"], .timeline-header-wrapper',
        title: 'El día que estás viendo',
        body: 'Arriba eliges la fecha: te posicionas en el día cuyos datos quieres ver. Usa las cápsulas o el selector; el tablero se actualiza con ese día.',
        progress: 'Tablero · fecha',
        nextLabel: 'Siguiente →',
        noScroll: true,
        onNext: function () {
          var st = loadState() || {};
          st.step = 2;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/obras_detailed/) && (st.step || 0) >= 2 && (st.step || 0) < 3;
        },
        selector: '[data-tour="tablero-libres"], .kanban-libres-panel',
        title: 'Operarios libres',
        body: 'Aquí están las personas sin obra ese día. Desde esta columna las arrastras para asignarlas. (no es el único método para asignar personal)',
        progress: 'Tablero · libres',
        nextLabel: 'Siguiente →',
        noScroll: true,
        onShow: function (el) {
          if (!el) return;
          // No tocar sticky: solo agujero + tip a la derecha
          requestAnimationFrame(function () {
            placeHole(el);
            placeCardNear(el);
          });
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 3;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/obras_detailed/) && (st.step || 0) >= 3 && (st.step || 0) < 4;
        },
        manualTarget: true,
        noScroll: true,
        title: 'Las obras del día',
        body: 'A la derecha están las obras en curso. Cada columna es una obra; dentro verás quién está asignado ese día.',
        progress: 'Tablero · obras',
        nextLabel: 'Siguiente →',
        onShow: function () {
          clearTargets();
          var wrap = qs('#kanbanWorksWrapper');
          var scrollLeft = wrap ? wrap.scrollLeft : 0;
          var scrollTop = wrap ? wrap.scrollTop : 0;
          var pageScroll = window.scrollY || document.documentElement.scrollTop || 0;
          var obras = Array.prototype.slice.call(
            document.querySelectorAll('#kanbanWorksWrapper > .kanban-col-wrapper, #kanbanWorksWrapper > .obra-card, #kanbanWorksWrapper > .kanban-col'),
            0,
            3
          );
          // Solo las 3 primeras obras visibles; sin libres ni scroll
          placeHoleUnion(obras, { clampViewport: true, minTop: 72 });
          placeCardDockBottom();
          if (wrap) {
            wrap.scrollLeft = scrollLeft;
            wrap.scrollTop = scrollTop;
          }
          try { window.scrollTo(0, pageScroll); } catch (e) { /* ignore */ }
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 4;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/obras_detailed/) && (st.step || 0) >= 4 && (st.step || 0) < 5;
        },
        manualTarget: true,
        title: 'Asigna arrastrando',
        body: 'Arrastra un operario libre hasta una obra. Al soltarlo se abre el calendario de asignación.',
        progress: 'Tablero · arrastrar',
        nextLabel: 'Ya lo arrastré →',
        requireGate: function () {
          var modal = qs('#assignmentModal');
          return !!(modal && modal.classList.contains('show'));
        },
        gateRetry: true,
        gateFail: 'Aún no se ha abierto el calendario. Arrastra un operario libre hasta una obra y suéltalo ahí.',
        onShow: function () {
          clearTargets();
          var chip = qs('#list-libres-body .worker-chip');
          var obraCol = qs('#kanbanWorksWrapper .kanban-col, #kanbanWorksWrapper .obra-card');
          var drop = obraCol
            ? (obraCol.querySelector('.worker-list-body') || obraCol)
            : null;
          if (chip) chip.classList.add('sp-tour-target');
          if (drop) drop.classList.add('sp-tour-target');
          if (chip || drop) {
            placeHoleUnion([chip, drop || obraCol]);
          } else {
            placeHole(qs('#kanbanContainer') || qs('main'));
          }
          // Tip fuera de la obra destino para no tapar el drop
          placeCardClearOfKanban();
          var advanced = false;
          function goNext() {
            if (advanced) return;
            advanced = true;
            try {
              if (window.jQuery) {
                window.jQuery(document).off('shown.bs.modal.spTourTablero');
              }
            } catch (e) { /* ignore */ }
            var st = loadState() || {};
            st.step = 5;
            saveState(st);
            run();
          }
          try {
            if (window.jQuery) {
              window.jQuery(document).off('shown.bs.modal.spTourTablero');
              window.jQuery(document).on(
                'shown.bs.modal.spTourTablero',
                '#assignmentModal',
                goNext
              );
            }
          } catch (e2) { /* ignore */ }
        },
        onNext: function () {
          try {
            if (window.jQuery) {
              window.jQuery(document).off('shown.bs.modal.spTourTablero');
            }
          } catch (e) { /* ignore */ }
          var st = loadState() || {};
          st.step = 5;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/obras_detailed/) && (st.step || 0) >= 5 && (st.step || 0) < 6;
        },
        selector: '#assignmentModal.show #modal-calendar-container, #modal-calendar-container',
        title: 'Calendario de la obra',
        body: 'Se abre el <strong>calendario de la obra</strong>: ves al resto de gente ya asignada a esa obra y en qué días. Así encajas la nueva asignación sin pisar a nadie.',
        progress: 'Tablero · calendario',
        nextLabel: 'Siguiente →',
        noScroll: true,
        requireGate: function () {
          var modal = qs('#assignmentModal');
          return !!(modal && modal.classList.contains('show'));
        },
        gateFail: 'El calendario ya no está abierto. Sin verlo la guía no puede continuar.',
        onShow: function (el) {
          var modal = qs('#assignmentModal');
          if (modal && modal.classList.contains('show') && el) {
            el.classList.add('sp-tour-target');
            placeHole(el);
            placeCardNear(el);
          } else {
            placeHole(null);
            placeCardNear(null);
          }
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 6;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/obras_detailed/) && (st.step || 0) >= 6 && (st.step || 0) < 7;
        },
        manualTarget: true,
        title: 'Bloque «Nueva asignación»',
        body: 'Ese bloque es lo que acabas de crear. Si quieres, arrástralo a otro día o <strong>estira un borde</strong> para cubrir varios días. Si te vale el día actual, pulsa Siguiente.',
        progress: 'Tablero · bloque',
        nextLabel: 'Siguiente →',
        onShow: function () {
          clearTargets();
          window.__spTourGhostAdjusted = false;
          var cal = qs('#assignmentModal #modal-calendar-container, #modal-calendar-container');
          var ghost = qs('#assignmentModal .fc-ghost-event, .fc-ghost-event');
          var startInput = qs('#assignmentModal [id$="-start"], .univ-calendar-panel [id$="-start"]');
          var endInput = qs('#assignmentModal [id$="-end"], .univ-calendar-panel [id$="-end"]');
          var initial = {
            s: startInput ? startInput.value : '',
            e: endInput ? endInput.value : '',
            w: ghost ? ghost.getBoundingClientRect().width : 0,
            l: ghost ? ghost.getBoundingClientRect().left : 0,
          };
          if (ghost) {
            ghost.classList.add('sp-tour-target');
            placeHole(ghost);
          } else if (cal) {
            placeHole(cal);
          } else {
            placeHole(null);
          }
          // Comentario fuera del calendario (no tapa el bloque ni el grid)
          placeCardOutside(cal || ghost);

          function expandToCalendar() {
            if (cal) {
              clearTargets();
              cal.classList.add('sp-tour-target');
              placeHole(cal);
              placeCardOutside(cal);
            }
          }
          if (cal) {
            cal.addEventListener('mousedown', function (ev) {
              if (ev.target && ev.target.closest &&
                  ev.target.closest('.fc-ghost-event, .fc-event-resizer, .fc-event')) {
                expandToCalendar();
              }
            }, { once: false });
          }

          var advanced = false;
          function goNext() {
            if (advanced) return;
            advanced = true;
            window.__spTourGhostAdjusted = true;
            if (window.__spTourGhostPoll) {
              clearInterval(window.__spTourGhostPoll);
              window.__spTourGhostPoll = null;
            }
            var st = loadState() || {};
            st.step = 7;
            saveState(st);
            run();
          }
          if (window.__spTourGhostPoll) clearInterval(window.__spTourGhostPoll);
          window.__spTourGhostPoll = setInterval(function () {
            var g = qs('#assignmentModal .fc-ghost-event, .fc-ghost-event');
            var sEl = qs('#assignmentModal [id$="-start"], .univ-calendar-panel [id$="-start"]');
            var eEl = qs('#assignmentModal [id$="-end"], .univ-calendar-panel [id$="-end"]');
            var changed = false;
            if (sEl && sEl.value !== initial.s) changed = true;
            if (eEl && eEl.value !== initial.e) changed = true;
            if (g && initial.w) {
              var r = g.getBoundingClientRect();
              if (Math.abs(r.width - initial.w) > 12 || Math.abs(r.left - initial.l) > 12) {
                changed = true;
                expandToCalendar();
              }
            }
            if (changed) goNext();
          }, 280);
        },
        onNext: function () {
          if (window.__spTourGhostPoll) {
            clearInterval(window.__spTourGhostPoll);
            window.__spTourGhostPoll = null;
          }
          var st = loadState() || {};
          st.step = 7;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/obras_detailed/) && (st.step || 0) >= 7 && (st.step || 0) < 8;
        },
        manualTarget: true,
        noScroll: true,
        title: 'Panel Nueva asignación',
        body: 'Abajo tienes el panel de la nueva asignación: fechas, destino y opciones. Si quieres, puedes <strong>añadir más trabajadores</strong> (compañeros) a esta misma asignación. Si el rango incluye sábado o domingo, activa <strong>Asignar fines de semana</strong>.',
        progress: 'Tablero · panel',
        nextLabel: 'Siguiente →',
        requireGate: function () {
          var modal = qs('#assignmentModal');
          return !!(modal && modal.classList.contains('show'));
        },
        gateFail: 'El calendario ya no está abierto. Sin el panel la guía no puede continuar.',
        onShow: function () {
          clearTargets();
          var panel = qs('#assignmentModal .univ-calendar-panel, .univ-calendar-panel');
          if (panel) {
            panel.style.display = 'block';
            panel.classList.add('sp-tour-target');
            placeHole(panel);
            placeCardNear(panel);
          } else {
            placeHole(null);
            placeCardNear(null);
          }
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 8;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/obras_detailed/) && (st.step || 0) >= 8 && (st.step || 0) < 9;
        },
        manualTarget: true,
        noScroll: true,
        title: 'Guarda con el tic',
        body: 'Pulsa el <strong>tic verde</strong> <i class="fas fa-check"></i> para guardar. Sin ese clic la asignación no se aplica.',
        progress: 'Tablero · guardar',
        nextLabel: 'Ya guardé →',
        waitClick: true,
        requireGate: function () {
          var modal = qs('#assignmentModal');
          return !!(modal && modal.classList.contains('show')) || !!window.__spTourTableroSaved;
        },
        gateFail: 'Todavía no has guardado. Pulsa el tic verde; si no, la guía se corta aquí.',
        onShow: function () {
          clearTargets();
          window.__spTourTableroSaved = false;
          var panel = qs('#assignmentModal .univ-calendar-panel, .univ-calendar-panel');
          var save = qs('#assignmentModal [id$="-save"], .univ-calendar-panel [id$="-save"]');
          if (panel) panel.style.display = 'block';
          if (save) {
            save.classList.add('sp-tour-target');
            placeHole(save);
            placeCardNear(panel || save);
            save.addEventListener('click', function () {
              window.__spTourTableroSaved = true;
              var st = loadState() || {};
              st.step = 9;
              saveState(st);
              setTimeout(function () { run(); }, 400);
            }, { once: true });
          } else if (panel) {
            panel.classList.add('sp-tour-target');
            placeHole(panel);
            placeCardNear(panel);
          } else {
            placeHole(null);
            placeCardNear(null);
          }
        },
        onNext: function () {
          var save = qs('#assignmentModal [id$="-save"], .univ-calendar-panel [id$="-save"]');
          if (save) {
            try { save.click(); } catch (e) { /* ignore */ }
            window.__spTourTableroSaved = true;
          }
          var st = loadState() || {};
          st.step = 9;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return !!(st && (st.step || 0) >= 9);
        },
        title: '',
        body: '',
        onShow: function () { pauseAtChapterEnd(); },
      },
    ];
  }

  function findTourPlanifBarEl(opts) {
    opts = opts || {};
    var doFocus = !!opts.focus;
    var id = window.__spTourPlanifItemId;
    var sel = window.currentSelectedItem;
    if (id == null && sel && sel.id != null) id = sel.id;

    function isRealAssignment(item) {
      if (!item) return false;
      var wid = String(item.worker_id || '');
      if (!wid || wid === 'NEW' || wid === 'SYSTEM' || wid === 'REQUEST') return false;
      if (item.type === 'background') return false;
      return true;
    }

    // Solo la barra que el usuario acaba de abrir — nunca “la última” de esa persona
    var item = null;
    if (id != null && window.AppItems && window.AppItems.get) {
      try { item = window.AppItems.get(id); } catch (e) { item = null; }
    }
    if (!isRealAssignment(item) && sel && isRealAssignment(sel)) {
      item = sel;
      id = sel.id;
    }
    if (!isRealAssignment(item)) return null;

    var byId = document.querySelector('.vis-item[data-id="' + item.id + '"]');
    if (doFocus && byId) {
      try {
        byId.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'auto' });
      } catch (e2) { /* ignore */ }
      try {
        if (window.AppTimeline && item.start && typeof window.AppTimeline.moveTo === 'function') {
          var mid = new Date(
            (new Date(item.start).getTime() + new Date(item.end || item.start).getTime()) / 2
          );
          window.AppTimeline.moveTo(mid, { animation: false });
        }
      } catch (e3) { /* ignore */ }
      byId = document.querySelector('.vis-item[data-id="' + item.id + '"]') || byId;
    }
    return byId;
  }

  // Compat: el nombre antiguo se usaba en varios sitios
  function findLastPlanifAssignmentEl(opts) {
    return findTourPlanifBarEl(opts);
  }

  function planifQuickCalOpen() {
    var modal = qs('#quickCalendarModal');
    return !!(modal && (modal.classList.contains('show') || modal.style.display === 'block'));
  }

  function planifPhantomExists() {
    if (document.querySelector('.vis-item.phantom-item, .phantom-item')) return true;
    try {
      if (window.AppItems && window.AppItems.get && window.AppItems.get('phantom_new')) return true;
    } catch (e) { /* ignore */ }
    return false;
  }

  function stepsPlanificadorMulti() {
    return [
      {
        when: function () { return !pathIs(/\/admin\/planificador/); },
        selector: '[data-tour="nav-planificador"], a[href*="planificador"]',
        title: 'Abre el Planificador',
        body: 'Pulsa <strong>Planificador</strong>. Es la vista de varias personas y varios días.',
        progress: 'Planificador · menú',
        waitClick: true,
        advanceTo: 1,
        ifMissing: 'wait',
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/admin\/planificador/) && (st.step || 0) < 2;
        },
        selector: '[data-tour="planif-filtros"], .planificador-filters',
        title: 'Filtros de arriba',
        body: 'Puedes filtrar por <strong>empresas</strong>, por <strong>jefe de obra</strong> (solo verás las obras de ese jefe) o por obras concretas. Así acotas el mapa antes de planificar.',
        progress: 'Planificador · filtros',
        nextLabel: 'Siguiente →',
        onNext: function () {
          var st = loadState() || {};
          st.step = 2;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/admin\/planificador/) && (st.step || 0) >= 2 && (st.step || 0) < 3;
        },
        manualTarget: true,
        title: 'Cómo se lee el cuadrante',
        body: 'A la <strong>izquierda</strong> van las obras (eje vertical). Arriba van las <strong>fechas</strong> (eje horizontal). En el centro aparecen las asignaciones: si alguien está en una obra un día, su barra está en esa celda.',
        progress: 'Planificador · ejes',
        nextLabel: 'Siguiente →',
        onShow: function () {
          clearTargets();
          var root = qs('[data-tour="planif-grid"], #planificador-calendar');
          // No añadir sp-tour-target a .vis-panel (rompe position:absolute de vis.js)
          // No scroll: el usuario debe conservar el contexto del cuadrante
          if (root) {
            placeHole(root);
            placeCardNear(root);
          } else {
            placeHole(null);
            placeCardNear(null);
          }
          try {
            if (window.AppTimeline && typeof window.AppTimeline.redraw === 'function') {
              setTimeout(function () { window.AppTimeline.redraw(); }, 50);
            }
          } catch (e2) { /* ignore */ }
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 3;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/admin\/planificador/) && (st.step || 0) >= 3 && (st.step || 0) < 4;
        },
        manualTarget: true,
        title: 'Abre una asignación',
        body: 'Haz <strong>clic</strong> en una barra de color del cuadrante (una persona en una obra). Se abrirá su ficha rápida.',
        progress: 'Planificador · clic',
        nextLabel: 'Ya hice clic →',
        requireGate: function () {
          var pop = qs('#worker-popover');
          return !!(pop && !pop.classList.contains('d-none'));
        },
        gateFail: 'No se ha abierto la ficha del trabajador. Haz clic en una barra del cuadrante; si no, la guía se corta aquí.',
        onShow: function () {
          clearTargets();
          var item = qs('.vis-item.vis-range:not(.vis-item-visible-frame), .vis-item.vis-range, .vis-item');
          if (item) {
            try { item.scrollIntoView({ block: 'center', behavior: 'auto' }); } catch (e) {}
            placeHole(item);
            placeCardNear(item);
          } else {
            var root = qs('#planificador-calendar');
            placeHole(root);
            placeCardNear(root);
          }
          var advanced = false;
          function goNext() {
            if (advanced) return;
            var pop = qs('#worker-popover');
            if (pop && pop.classList.contains('d-none')) return;
            // Solo avanzamos con asignación real de persona (no solicitudes / sistema)
            var sel = window.currentSelectedItem;
            var wid = sel ? String(sel.worker_id || '') : '';
            if (!sel || !wid || wid === 'NEW' || wid === 'SYSTEM' || wid === 'REQUEST') {
              return;
            }
            advanced = true;
            try {
              window.__spTourPlanifItemId = sel.id;
            } catch (eId) { /* ignore */ }
            try {
              if (window.jQuery) window.jQuery(document).off('click.spTourPlanif');
            } catch (e) { /* ignore */ }
            var st = loadState() || {};
            st.step = 4;
            saveState(st);
            run();
          }
          try {
            if (window.jQuery) {
              window.jQuery(document).off('click.spTourPlanif');
              window.jQuery(document).on('click.spTourPlanif', '.vis-item', function () {
                var id = this.getAttribute && this.getAttribute('data-id');
                if (id) window.__spTourPlanifItemId = id;
                setTimeout(goNext, 150);
              });
            }
          } catch (e2) { /* ignore */ }
          // Poll por si el popover se abre sin el handler
          var tries = 0;
          var timer = setInterval(function () {
            tries += 1;
            var pop = qs('#worker-popover');
            if (pop && !pop.classList.contains('d-none')) {
              goNext();
              if (advanced) clearInterval(timer);
            }
            if (tries > 80) clearInterval(timer);
          }, 250);
        },
        onNext: function () {
          try {
            if (window.jQuery) window.jQuery(document).off('click.spTourPlanif');
          } catch (e) { /* ignore */ }
          var st = loadState() || {};
          st.step = 4;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/admin\/planificador/) && (st.step || 0) >= 4 && (st.step || 0) < 5;
        },
        selector: '#worker-popover:not(.d-none), #worker-popover, .planificador-worker-popover',
        title: 'Ficha de la persona',
        body: 'Aquí ves quién es, su empresa y acciones rápidas (calendario, desasignar, etc.).',
        progress: 'Planificador · ficha',
        nextLabel: 'Siguiente →',
        onShow: function (el) {
          var pop = qs('#worker-popover');
          if (pop && !pop.classList.contains('d-none')) {
            pop.classList.add('sp-tour-target');
            placeHole(pop);
            placeCardNear(pop);
          } else if (el) {
            el.classList.add('sp-tour-target');
            placeHole(el);
            placeCardNear(el);
          }
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 5;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/admin\/planificador/) && (st.step || 0) >= 5 && (st.step || 0) < 6;
        },
        manualTarget: true,
        noScroll: true,
        title: 'Ampliar arrastrando',
        body: 'Cierra la ficha si molesta. Estira el <strong>borde</strong> de esa barra (o muévela de día). Solo al soltar, tras haberla cambiado, pasamos al siguiente paso.',
        progress: 'Planificador · arrastre',
        nextLabel: 'Ya lo moví →',
        requireGate: function () { return !!window.__spTourPlanifDragged; },
        gateFail: 'Todavía no has movido ni estirado la barra. Hazlo en el cuadrante; si no, la guía se corta aquí.',
        onShow: function () {
          clearTargets();
          window.__spTourPlanifDragged = false;
          var item = findLastPlanifAssignmentEl({ focus: true });
          var itemId = null;
          try {
            if (item && item.getAttribute) itemId = item.getAttribute('data-id');
            if (!itemId && window.__spTourPlanifItemId != null) itemId = String(window.__spTourPlanifItemId);
          } catch (e0) { /* ignore */ }

          function highlightItem(el) {
            if (!el) {
              placeHole(qs('#planificador-calendar'));
              placeCardNear(qs('#planificador-calendar'));
              return;
            }
            // Franja horizontal completa a la altura de la barra (borde arrastrable)
            placeHolePlanifItemStrip(el);
            placeCardNear(el);
          }
          highlightItem(item);

          var startSnap = null;
          var armed = false;
          var advanced = false;
          var dragging = false;
          var downPt = null;

          function readSnap(el) {
            var data = null;
            try {
              if (itemId && window.AppItems && window.AppItems.get) {
                data = window.AppItems.get(itemId);
              }
            } catch (e) { /* ignore */ }
            var r = el ? el.getBoundingClientRect() : null;
            return {
              s: data && data.start ? new Date(data.start).getTime() : 0,
              e: data && data.end ? new Date(data.end).getTime() : 0,
              w: r ? r.width : 0,
              l: r ? r.left : 0,
            };
          }

          function changedEnough(a, b) {
            if (!a || !b) return false;
            if (a.s && b.s && Math.abs(a.s - b.s) > 1000) return true;
            if (a.e && b.e && Math.abs(a.e - b.e) > 1000) return true;
            if (a.w && Math.abs(b.w - a.w) > 14) return true;
            if (a.l && Math.abs(b.l - a.l) > 14) return true;
            return false;
          }

          function advanceToDoubleClick() {
            var st = loadState() || {};
            st.step = 6;
            saveState(st);
            run();
          }

          function goNext() {
            if (advanced) return;
            advanced = true;
            window.__spTourPlanifDragged = true;
            if (window.__spTourPlanifDragPoll) {
              clearInterval(window.__spTourPlanifDragPoll);
              window.__spTourPlanifDragPoll = null;
            }
            if (window.__spTourPlanifDragSettle) {
              clearTimeout(window.__spTourPlanifDragSettle);
              window.__spTourPlanifDragSettle = null;
            }
            try {
              document.removeEventListener('pointerdown', onPointerDown, true);
              document.removeEventListener('pointermove', onPointerMove, true);
              document.removeEventListener('pointerup', onPointerUp, true);
            } catch (e) { /* ignore */ }

            // Zoom breve a la señal de arriba (cambios / sin cambios), luego doble clic
            var tries = 0;
            function focusToastThenNext() {
              var toast = findPlanifFeedbackToast();
              if (toast) {
                clearTargets();
                placeHole(toast);
                placeCardNear(toast);
                if (ui.card) {
                  var h = ui.card.querySelector('h3');
                  var p = ui.card.querySelector('p');
                  if (h) h.textContent = t('Señal de guardado');
                  if (p) {
                    p.innerHTML = t('Arriba te confirma si hubo cambios o no. En el siguiente paso asignamos con <strong>doble clic</strong>.');
                  }
                }
                setTimeout(advanceToDoubleClick, 1600);
                return;
              }
              tries += 1;
              if (tries < 8) {
                setTimeout(focusToastThenNext, 180);
                return;
              }
              advanceToDoubleClick();
            }
            setTimeout(focusToastThenNext, 250);
          }

          function onPointerDown(ev) {
            var hit = ev.target && ev.target.closest && ev.target.closest('.vis-item');
            if (!hit) {
              armed = false;
              downPt = null;
              return;
            }
            // Solo la barra objetivo (evita saltar al clic en otra)
            if (itemId && hit.getAttribute('data-id') && String(hit.getAttribute('data-id')) !== String(itemId)) {
              armed = false;
              downPt = null;
              return;
            }
            armed = true;
            dragging = false;
            downPt = { x: ev.clientX, y: ev.clientY };
            startSnap = readSnap(hit);
            highlightItem(hit);
          }
          function onPointerMove(ev) {
            if (!armed || !downPt) return;
            // Mantener la franja (no abrir overlay a pantalla completa: se pierde el zoom)
            if (Math.abs(ev.clientX - downPt.x) > 10 || Math.abs(ev.clientY - downPt.y) > 10) {
              dragging = true;
              var el = itemId
                ? document.querySelector('.vis-item[data-id="' + itemId + '"]')
                : null;
              if (el) placeHolePlanifItemStrip(el);
            }
          }
          function onPointerUp() {
            if (!armed) return;
            var el = itemId
              ? document.querySelector('.vis-item[data-id="' + itemId + '"]')
              : findLastPlanifAssignmentEl({ focus: false });
            var now = readSnap(el);
            var ok = dragging && changedEnough(startSnap, now);
            armed = false;
            dragging = false;
            downPt = null;
            if (ok) {
              goNext();
              return;
            }
            // Clic simple o sin cambio real: volver a enfocar la franja
            highlightItem(el || item);
          }

          document.addEventListener('pointerdown', onPointerDown, true);
          document.addEventListener('pointermove', onPointerMove, true);
          document.addEventListener('pointerup', onPointerUp, true);

          if (window.__spTourPlanifDragSettle) clearTimeout(window.__spTourPlanifDragSettle);
          window.__spTourPlanifDragSettle = setTimeout(function () {
            item = findLastPlanifAssignmentEl({ focus: false }) || item;
            if (item && item.getAttribute) itemId = item.getAttribute('data-id') || itemId;
            highlightItem(item);
            startSnap = readSnap(item);
          }, 350);
        },
        onNext: function () {
          if (window.__spTourPlanifDragPoll) {
            clearInterval(window.__spTourPlanifDragPoll);
            window.__spTourPlanifDragPoll = null;
          }
          if (window.__spTourPlanifDragSettle) {
            clearTimeout(window.__spTourPlanifDragSettle);
            window.__spTourPlanifDragSettle = null;
          }
          var st = loadState() || {};
          st.step = 6;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/admin\/planificador/) && (st.step || 0) >= 6 && (st.step || 0) < 7;
        },
        manualTarget: true,
        noScroll: true,
        title: 'Asignar con doble clic',
        body: 'Desde aquí también se asigna gente. Haz <strong>doble clic</strong> en una celda vacía de una obra, en un día <strong>a partir de hoy</strong>. Aparecerá un bloque nuevo.',
        progress: 'Planificador · crear',
        nextLabel: 'Ya creé el bloque →',
        requireGate: function () { return planifPhantomExists(); },
        gateFail: 'No hay un bloque nuevo. Haz doble clic en una celda vacía; si no, la guía se corta aquí.',
        onShow: function () {
          clearTargets();
          var grid = planifClickableGridEl();
          if (grid) {
            placeHole(grid);
            placeCardNear(grid);
          } else {
            placeHole(qs('#planificador-calendar'));
            placeCardNear(qs('#planificador-calendar'));
          }
          var advanced = false;
          function goNext() {
            if (advanced) return;
            advanced = true;
            if (window.__spTourPhantomPoll) {
              clearInterval(window.__spTourPhantomPoll);
              window.__spTourPhantomPoll = null;
            }
            var st = loadState() || {};
            st.step = 7;
            saveState(st);
            run();
          }
          if (window.__spTourPhantomPoll) clearInterval(window.__spTourPhantomPoll);
          window.__spTourPhantomPoll = setInterval(function () {
            if (planifPhantomExists()) goNext();
          }, 300);
        },
        onNext: function () {
          if (window.__spTourPhantomPoll) {
            clearInterval(window.__spTourPhantomPoll);
            window.__spTourPhantomPoll = null;
          }
          var st = loadState() || {};
          st.step = 7;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/admin\/planificador/) && (st.step || 0) >= 7 && (st.step || 0) < 8;
        },
        manualTarget: true,
        noScroll: true,
        title: 'Abre el bloque',
        body: 'Haz <strong>doble clic</strong> en ese bloque nuevo para abrir el calendario de asignación. También puedes <strong>moverlo o arrastrarlo</strong> al día que quieras (y luego abrir el calendario para afinar detalles).',
        progress: 'Planificador · abrir',
        nextLabel: 'Ya abrí el calendario →',
        requireGate: function () { return planifQuickCalOpen(); },
        gateFail: 'El calendario de asignación no se ha abierto. Haz doble clic en el bloque nuevo; si no, la guía se corta aquí.',
        onShow: function () {
          clearTargets();
          function phantomEl() {
            return qs('.vis-item.phantom-item, .vis-item[data-id="phantom_new"], .phantom-item');
          }
          function focusPhantom() {
            var phantom = phantomEl();
            if (phantom) {
              placeHole(phantom);
              placeCardNear(phantom);
            } else {
              placeHole(planifClickableGridEl() || qs('#planificador-calendar'));
              placeCardNear(null);
            }
          }
          focusPhantom();

          var advanced = false;
          function goNext() {
            if (advanced) return;
            if (!planifQuickCalOpen()) return;
            advanced = true;
            try {
              if (window.jQuery) {
                window.jQuery(document).off('shown.bs.modal.spTourPlanifCal');
              }
            } catch (e) { /* ignore */ }
            if (window.__spTourPlanifCalPoll) {
              clearInterval(window.__spTourPlanifCalPoll);
              window.__spTourPlanifCalPoll = null;
            }
            try {
              document.removeEventListener('pointerdown', onPhDown, true);
              document.removeEventListener('pointermove', onPhMove, true);
              document.removeEventListener('pointerup', onPhUp, true);
            } catch (e2) { /* ignore */ }
            var st = loadState() || {};
            st.step = 8;
            saveState(st);
            run();
          }

          var phArmed = false;
          var phDragging = false;
          function onPhDown(ev) {
            var hit = ev.target && ev.target.closest &&
              ev.target.closest('.vis-item.phantom-item, .vis-item[data-id="phantom_new"], .phantom-item');
            phArmed = !!hit;
            phDragging = false;
          }
          function onPhMove() {
            if (!phArmed) return;
            phDragging = true;
            revealTourDesktop();
          }
          function onPhUp() {
            if (!phArmed) return;
            phArmed = false;
            // Tras soltar el arrastre, volver a enfocar el bloque para el doble clic
            setTimeout(focusPhantom, 80);
            phDragging = false;
          }
          document.addEventListener('pointerdown', onPhDown, true);
          document.addEventListener('pointermove', onPhMove, true);
          document.addEventListener('pointerup', onPhUp, true);

          try {
            if (window.jQuery) {
              window.jQuery(document).off('shown.bs.modal.spTourPlanifCal');
              window.jQuery(document).on(
                'shown.bs.modal.spTourPlanifCal',
                '#quickCalendarModal',
                goNext
              );
            }
          } catch (e2) { /* ignore */ }
          if (window.__spTourPlanifCalPoll) clearInterval(window.__spTourPlanifCalPoll);
          window.__spTourPlanifCalPoll = setInterval(function () {
            if (planifQuickCalOpen()) goNext();
          }, 300);
        },
        onNext: function () {
          try {
            if (window.jQuery) {
              window.jQuery(document).off('shown.bs.modal.spTourPlanifCal');
            }
          } catch (e) { /* ignore */ }
          if (window.__spTourPlanifCalPoll) {
            clearInterval(window.__spTourPlanifCalPoll);
            window.__spTourPlanifCalPoll = null;
          }
          var st = loadState() || {};
          st.step = 8;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/admin\/planificador/) && (st.step || 0) >= 8 && (st.step || 0) < 9;
        },
        manualTarget: true,
        noScroll: true,
        title: 'Bloque de la nueva asignación',
        body: 'En el calendario ves el bloque de la asignación que acabas de crear sobre la obra.',
        progress: 'Planificador · bloque',
        nextLabel: 'Siguiente →',
        requireGate: function () { return planifQuickCalOpen(); },
        gateFail: 'El calendario ya no está abierto. Sin ver el bloque la guía no puede continuar.',
        onShow: function () {
          clearTargets();
          var ghost = qs('#quickCalendarModal .fc-ghost-event, .fc-ghost-event');
          var cal = qs('#quickCalendarModal #modal-calendar-container, #modal-calendar-container');
          if (ghost) {
            ghost.classList.add('sp-tour-target');
            placeHole(ghost);
            placeCardNear(cal || ghost);
          } else if (cal) {
            cal.classList.add('sp-tour-target');
            placeHole(cal);
            placeCardNear(cal);
          } else {
            placeHole(null);
            placeCardNear(null);
          }
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 9;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/admin\/planificador/) && (st.step || 0) >= 9 && (st.step || 0) < 10;
        },
        manualTarget: true,
        noScroll: true,
        title: 'Ajustar fechas (opcional)',
        body: 'Si quieres, puedes <strong>estirar</strong> o mover el bloque para cubrir más días. No es obligatorio: con «Siguiente» seguimos.',
        progress: 'Planificador · fechas',
        nextLabel: 'Siguiente →',
        requireGate: function () { return planifQuickCalOpen(); },
        gateFail: 'El calendario ya no está abierto. Sin él la guía no puede continuar.',
        onShow: function () {
          clearTargets();
          var cal = qs('#quickCalendarModal #modal-calendar-container, #modal-calendar-container');
          var ghost = qs('#quickCalendarModal .fc-ghost-event, .fc-ghost-event');
          if (cal) {
            placeHole(cal);
            placeCardNear(cal);
          } else if (ghost) {
            placeHole(ghost);
            placeCardNear(ghost);
          } else {
            placeHole(null);
            placeCardNear(null);
          }
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 10;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/admin\/planificador/) && (st.step || 0) >= 10 && (st.step || 0) < 11;
        },
        manualTarget: true,
        noScroll: true,
        title: 'Elige a la persona',
        body: 'Abajo, en el panel, <strong>elige el trabajador</strong> (o trabajadores) que quieres asignar a esa obra. Ajusta fechas si hace falta.',
        progress: 'Planificador · persona',
        nextLabel: 'Siguiente →',
        requireGate: function () { return planifQuickCalOpen(); },
        gateFail: 'El calendario ya no está abierto. Sin el panel la guía no puede continuar.',
        onShow: function () {
          clearTargets();
          var panel = qs('#quickCalendarModal .univ-calendar-panel, .univ-calendar-panel');
          var dest = qs('#quickCalendarModal [id$="-selector-container"], .univ-calendar-panel [id$="-selector-container"]');
          if (panel) panel.style.display = 'block';
          var focus = dest || panel;
          if (focus) {
            try { focus.scrollIntoView({ block: 'nearest', behavior: 'auto' }); } catch (e) {}
            if (panel) panel.classList.add('sp-tour-target');
            placeHole(panel || focus);
            placeCardNear(panel || focus);
          } else {
            placeHole(null);
            placeCardNear(null);
          }
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 11;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/admin\/planificador/) && (st.step || 0) >= 11 && (st.step || 0) < 12;
        },
        manualTarget: true,
        noScroll: true,
        title: 'Guarda con el tic',
        body: 'Pulsa el <strong>tic verde</strong> <i class="fas fa-check"></i> para guardar. Sin ese clic la asignación no se aplica.',
        progress: 'Planificador · guardar',
        nextLabel: 'Ya guardé →',
        waitClick: true,
        requireGate: function () { return planifQuickCalOpen() || !!window.__spTourPlanifSaved; },
        gateFail: 'Todavía no has guardado. Pulsa el tic verde; si no, la guía se corta aquí.',
        onShow: function () {
          clearTargets();
          window.__spTourPlanifSaved = false;
          var panel = qs('#quickCalendarModal .univ-calendar-panel, .univ-calendar-panel');
          var save = qs('#quickCalendarModal [id$="-save"], .univ-calendar-panel [id$="-save"]');
          if (panel) panel.style.display = 'block';
          if (save) {
            save.classList.add('sp-tour-target');
            placeHole(save);
            placeCardNear(panel || save);
            save.addEventListener('click', function () {
              window.__spTourPlanifSaved = true;
              var st = loadState() || {};
              st.step = 12;
              saveState(st);
              setTimeout(function () { run(); }, 400);
            }, { once: true });
          } else if (panel) {
            panel.classList.add('sp-tour-target');
            placeHole(panel);
            placeCardNear(panel);
          } else {
            placeHole(null);
            placeCardNear(null);
          }
        },
        onNext: function () {
          var save = qs('#quickCalendarModal [id$="-save"], .univ-calendar-panel [id$="-save"]');
          if (save && planifQuickCalOpen()) {
            try { save.click(); } catch (e) { /* ignore */ }
            window.__spTourPlanifSaved = true;
          }
          var st = loadState() || {};
          st.step = 12;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return !!(st && (st.step || 0) >= 12);
        },
        title: '',
        body: '',
        onShow: function () { pauseAtChapterEnd(); },
      },
    ];
  }

  function stepsAuditoriaFichajesTour() {
    return [
      {
        when: function () { return !pathIs(/\/sync\/auditoria/); },
        selector: '[data-tour="nav-auditoria-fichajes"]',
        title: 'Auditoría de fichajes',
        body: 'Pulsa <strong>Auditoría fichajes</strong>. Ahí llegan las pelotas rojas del día a día.',
        progress: 'Auditoría · menú',
        waitClick: true,
        advanceTo: 1,
        ifMissing: 'wait',
      },
      {
        when: function () { return pathIs(/\/sync\/auditoria/); },
        selector: '[data-tour="audit-paracaidistas"], .auditoria-section, main',
        title: 'Secciones de alerta',
        body: 'Sin planificar, desvíos y ausencias. Abre una sección para ver filas concretas.',
        progress: 'Auditoría · mapa',
        nextLabel: 'Seguir →',
        onShow: function () { highlightAuditSection(); },
        onNext: function () {
          var st = loadState() || {};
          st.step = 2;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/sync\/auditoria/) && !!(st && (st.step || 0) >= 2) && (st.step || 0) < 3;
        },
        modal: true,
        title: 'Aceptar o ignorar',
        body: 'Cada fila se resuelve: <strong>Aceptar</strong> valida el fichaje en esa obra; <strong>Ignorar</strong> oculta la alerta sin cambiar el cuadrante.',
        progress: 'Auditoría · resolver',
        nextLabel: 'Entendido →',
        onNext: function () {
          var st = loadState() || {};
          st.step = 3;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return !!(st && (st.step || 0) >= 3);
        },
        title: '',
        body: '',
        onShow: function () { pauseAtChapterEnd(); },
      },
    ];
  }

  function stepsRegistroJornada() {
    return [
      {
        when: function () { return !pathIs(/\/admin\/registro[-_]jornada/); },
        selector: '[data-tour="nav-registro-jornada"], a[href*="registro"]',
        title: 'Registro de jornada',
        body: 'Pulsa <strong>Registro jornada</strong>. Es el informe listo para inspección.',
        progress: 'Jornada · menú',
        waitClick: true,
        advanceTo: 1,
        ifMissing: 'wait',
      },
      {
        when: function () { return pathIs(/\/admin\/registro[-_]jornada/); },
        selector: '.page-toolbar, main',
        title: 'Tu kit de inspección',
        body: 'Desde aquí filtras fechas, imprimes o exportas. Guárdalo mentalmente: es lo que te pedirán en una visita.',
        progress: 'Jornada · informe',
        nextLabel: 'Listo →',
        onNext: function () {
          var st = loadState() || {};
          st.step = 2;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return !!(st && (st.step || 0) >= 2);
        },
        title: '',
        body: '',
        onShow: function () { pauseAtChapterEnd(); },
      },
    ];
  }

  function stepsFlota() {
    return [
      {
        when: function () {
          return !pathIs(/\/admin\/vehiculos/) || pathIs(/\/admin\/vehiculos\/nuevo/) ||
            pathIs(/\/admin\/vehiculos\/\d+\/editar/) ||
            pathIs(/\/admin\/vehiculos_libres/) || pathIs(/\/admin\/vehiculos\/libres/);
        },
        selector: '[data-tour="nav-vehiculos"], a[href*="/admin/vehiculos"]:not([href*="libres"]):not([href*="nuevo"])',
        title: 'Ve a Flota',
        body: 'Pulsa <strong>Flota</strong> en el menú. Ahí gestionas los vehículos de la empresa.',
        progress: 'Flota · menú',
        waitClick: true,
        advanceTo: 1,
        ifMissing: 'wait',
      },
      {
        when: function () {
          return pathIs(/\/admin\/vehiculos\/?(\?|$)/) && !pathIs(/nuevo/) && !pathIs(/editar/) && !pathIs(/libres/);
        },
        selector: '[data-tour="veh-nuevo"]',
        title: 'Nuevo vehículo',
        body: 'Pulsa <strong>Nuevo vehículo</strong> para abrir el formulario de alta (igual que en personal u obras).',
        progress: 'Flota · elegir',
        waitClick: true,
        advanceTo: 2,
      },
      {
        when: function () { return pathIs(/\/admin\/vehiculos\/nuevo/); },
        selector: '[data-tour="veh-nombre"], input[name="nombre"]',
        title: 'Nombre del vehículo',
        body: 'Pon un nombre claro (p. ej. Furgoneta 1).',
        progress: 'Alta · nombre',
        onShow: function (el) { if (el) el.focus(); },
      },
      {
        when: function () { return pathIs(/\/admin\/vehiculos\/nuevo/); },
        selector: '[data-tour="veh-matricula"], input[name="matricula"]',
        title: 'Matrícula',
        body: 'Opcional pero útil. Marca y modelo están en opciones avanzadas si los quieres.',
        progress: 'Alta · matrícula',
        onShow: function (el) { if (el) el.focus(); },
      },
      {
        when: function () { return pathIs(/\/admin\/vehiculos\/nuevo/); },
        selector: '[data-tour="veh-guardar"]',
        title: 'Crear vehículo',
        body: 'Pulsa Crear vehículo. Volverás al listado de flota.',
        progress: 'Alta · guardar',
        waitClick: true,
        onShow: function () {
          var form = qs('#vehiculoForm') || qs('form');
          if (!form) return;
          form.addEventListener('submit', function () {
            var st = loadState();
            if (st) {
              st.createdVehiculoNombre = ((qs('input[name="nombre"]') || {}).value || '').trim();
              st.step = 5;
              saveState(st);
            }
          }, { once: true });
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/admin\/vehiculos\/?(\?|$)/) && !pathIs(/nuevo/) && st && (st.step || 0) >= 5;
        },
        manualTarget: true,
        title: '¡Vehículo creado!',
        body: function () {
          var st = loadState() || {};
          if (st.mode === 'solo') {
            return 'Ya está en flota. Te devolvemos a Primeros pasos.';
          }
          return 'Ya está en flota. Puedes asignarlo por día desde el tablero o su ficha.';
        },
        progress: 'Flota · listo',
        nextLabel: function () {
          var st = loadState() || {};
          return st.mode === 'solo' ? 'Volver a Primeros pasos →' : 'Entendido →';
        },
        onShow: function () {
          var st = loadState() || {};
          var name = (st.createdVehiculoNombre || '').toLowerCase();
          if (!name) return;
          document.querySelectorAll('#vehiclesTable .data-row').forEach(function (tr) {
            if ((tr.textContent || '').toLowerCase().indexOf(name) >= 0) {
              tr.classList.add('sp-tour-target');
              placeHole(tr);
              placeCardNear(tr);
            }
          });
        },
        onNext: function () {
          var st = loadState() || {};
          if (st.fromGuide) {
            markAcademiaDone('flota');
            finishGuideToHub('Vehículo creado. Tutorial guiado completado.');
            return;
          }
          if (st.mode === 'solo') {
            finishSoloAndReturn('Vehículo creado. Sigue cuando quieras con el resto de tutoriales.');
            return;
          }
          pauseAtChapterEnd();
        },
      },
    ];
  }

  function stepsFichajes() {
    return [
      {
        when: function () {
          return !pathIs(/\/admin\/personal/) && !pathIs(/\/admin\/edit_operario/) &&
            !pathIs(/\/admin\/create_user/) && !isMiEntrar() && !isMiFichar() &&
            !pathIs(/\/sync\/auditoria/) && !pathIs(/\/admin\/registro/);
        },
        selector: '[data-tour="nav-trabajadores"], a[href*="/admin/personal"]',
        title: 'Abre Trabajadores',
        body: 'Desde aquí, pulsa <strong>Trabajadores</strong> en el menú (misma pestaña). Ahí gestionas el acceso de las personas.',
        progress: 'Fichajes · menú',
        waitClick: true,
        advanceTo: 1,
        ifMissing: 'wait',
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/admin\/personal/) && (st.step || 0) < 2;
        },
        manualTarget: true,
        title: 'Abre un operario',
        body: 'Abre la ficha de un <strong>operario</strong> (lápiz de editar). Ahí verás el rol y el bloque de PIN de fichaje.',
        progress: 'Fichajes · persona',
        waitClick: true,
        nextLabel: 'Ya abrí la ficha →',
        onShow: function () {
          clearTargets();
          // Preferir Internos: ahí está el lápiz de editar de los operarios de ejemplo
          try {
            var tabInt = qs('#internos-tab');
            if (tabInt && window.jQuery) window.jQuery(tabInt).tab('show');
            else if (tabInt) tabInt.click();
          } catch (eTab) { /* ignore */ }

          function pickOperarioEdit() {
            var scopes = ['#internos', '#operarios', ''];
            for (var s = 0; s < scopes.length; s++) {
              var root = scopes[s] ? qs(scopes[s]) : document;
              if (!root) continue;
              var rows = Array.prototype.slice.call(
                root.querySelectorAll('[data-tour-user-row], tr[data-dni]')
              );
              if (!rows.length) {
                rows = Array.prototype.slice.call(root.querySelectorAll('tbody tr')).filter(function (tr) {
                  var badge = (tr.textContent || '').toLowerCase();
                  return badge.indexOf('operario') >= 0;
                });
              }
              for (var i = 0; i < rows.length; i++) {
                var a = rows[i].querySelector('a[href*="edit_operario"]');
                if (a) return a;
              }
              var any = root.querySelector('a[href*="edit_operario"]');
              if (any) return any;
            }
            return qs('a[href*="edit_operario"]');
          }

          // Esperar un instante a que la pestaña Internos pinte filas
          function tryHighlight(attempt) {
            var edit = pickOperarioEdit();
            if (edit) {
              try {
                var tabPane = edit.closest('.tab-pane');
                if (tabPane && tabPane.id === 'operarios') {
                  var tabExt = qs('#operarios-tab');
                  if (tabExt && window.jQuery) window.jQuery(tabExt).tab('show');
                  else if (tabExt) tabExt.click();
                }
              } catch (eSw) { /* ignore */ }
              edit.classList.add('sp-tour-target');
              placeHole(edit);
              placeCardNear(edit);
              bindNavClick(edit, 2);
              edit.addEventListener('click', function () {
                var st = loadState() || {};
                var row = edit.closest('tr');
                if (row && row.getAttribute('data-dni')) {
                  st.createdDni = row.getAttribute('data-dni');
                }
                st.step = 2;
                saveState(st);
              }, { once: true });
              return;
            }
            if ((attempt || 0) < 6) {
              setTimeout(function () { tryHighlight((attempt || 0) + 1); }, 120);
              return;
            }
            placeHole(qs('main'));
            placeCardNear(null);
          }
          setTimeout(function () { tryHighlight(0); }, 80);
        },
        onNext: function () {
          var edit = qs('#internos a[href*="edit_operario"]') ||
            qs('#operarios a[href*="edit_operario"]') ||
            qs('a[href*="edit_operario"]');
          var st = loadState() || {};
          st.step = 2;
          saveState(st);
          if (edit && edit.href) {
            window.location.href = edit.href;
            return;
          }
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/admin\/edit_operario|\/admin\/create_user/) && (st.step || 0) >= 2 && (st.step || 0) < 3;
        },
        manualTarget: true,
        title: 'Rol del sistema',
        body: 'El <strong>rol</strong> define cómo entra cada persona. Un <strong>operario</strong> entra con DNI + PIN (mismo login que el resto) y ficha desde el menú Fichaje. Los demás roles usan correo y contraseña.',
        progress: 'Fichajes · rol',
        nextLabel: 'Siguiente: PIN →',
        onShow: function () {
          clearTargets();
          var role = qs('#roleSelect');
          var wrap = role ? (role.closest('.form-group') || role) : null;
          if (wrap) {
            try { wrap.scrollIntoView({ block: 'center', behavior: 'auto' }); } catch (e) {}
            wrap.classList.add('sp-tour-target');
            placeHole(wrap);
            placeCardNear(wrap);
          } else {
            placeHole(qs('main'));
            placeCardNear(null);
          }
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 3;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/admin\/edit_operario|\/admin\/create_user/) && (st.step || 0) >= 3 && (st.step || 0) < 4;
        },
        manualTarget: true,
        title: 'PIN de fichaje',
        body: 'Elige <strong>Guardar PIN</strong> tú o <strong>Enviar enlace</strong> por correo (solo una). Al guardar o enviar, seguimos solos.',
        progress: 'Fichajes · PIN',
        nextLabel: 'PIN listo →',
        onShow: function () {
          clearTargets();
          var pin = qs('#pinEditSection, [data-tour="user-pin-edit"]');
          var office = qs('#officeAccessBlock, [data-tour="user-acceso-office"]');
          var focus = pin || office;
          var advanced = false;

          function refocusPin() {
            var el = qs('#pinEditSection, [data-tour="user-pin-edit"]') || focus;
            if (!el) return;
            try { el.scrollIntoView({ block: 'center', behavior: 'auto' }); } catch (e) {}
            el.classList.add('sp-tour-target');
            // Tras cambiar a “Enviar enlace” el bloque crece: recalcular agujero
            placeHole(el);
            placeCardNear(el);
          }

          if (focus) {
            refocusPin();
          } else {
            placeHole(qs('main'));
            placeCardNear(null);
          }
          if (ui.card) {
            var p = ui.card.querySelector('p');
            if (p) {
              if (pin) {
                p.innerHTML = t('Bloque de <strong>PIN de fichaje</strong>: guarda uno tú o envía enlace. Al hacerlo avanzamos al siguiente paso.');
              } else if (office) {
                p.innerHTML = t('Este perfil no usa PIN. Cambia el rol a <strong>operario</strong> o vuelve a Personal y abre uno.');
              }
            }
          }

          function advanceAfterPin() {
            if (advanced) return;
            advanced = true;
            var st = loadState() || {};
            st.step = 4;
            st.wantFichaje = true;
            st.pinDone = true;
            saveState(st);
          }

          document.querySelectorAll(
            '#pinEditSection form, #pinEditManualBlock form, #pinEditEmailBlock form, ' +
            'form[action*="reset_pin"], form[action*="enviar_acceso"]'
          ).forEach(function (form) {
            form.addEventListener('submit', advanceAfterPin, { once: true });
          });

          ['pinEditModeManual', 'pinEditModeEmail', 'pinModeManual', 'pinModeEmail'].forEach(function (id) {
            var radio = document.getElementById(id);
            if (!radio) return;
            radio.addEventListener('change', function () {
              setTimeout(refocusPin, 40);
              setTimeout(refocusPin, 200);
            });
          });
          document.addEventListener('sp-pin-mode-changed', function onPinMode() {
            setTimeout(refocusPin, 40);
            setTimeout(refocusPin, 200);
          });

          // Si ya se guardó PIN en esta visita (reload tras submit)
          var stNow = loadState() || {};
          if (stNow.pinDone) {
            setTimeout(function () {
              if (advanced) return;
              advanced = true;
              stNow.step = 4;
              saveState(stNow);
              run();
            }, 200);
          }
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 4;
          st.wantFichaje = true;
          st.pinDone = true;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return (st.step || 0) >= 4 && (st.step || 0) < 5 &&
            !isMiEntrar() && !isMiFichar() && !pathIs(/\/sync\/auditoria/) && !pathIs(/\/admin\/registro/);
        },
        modal: true,
        title: 'Prueba a fichar',
        body: 'Vas a entrar en la aplicación con el DNI y el PIN. Ficharás en <strong>Oficina</strong> (la activamos para el tutorial): así el fichaje no está planificado y luego lo revisas en auditoría.',
        progress: 'Fichajes · probar',
        primaryHref: '/admin/tour/fichaje-probar?chapter=fichajes',
        primaryLabel: 'Ir a fichar como operario',
        onBeforeGo: function () {
          var st = loadState() || {};
          st.chapter = 'fichajes';
          st.step = 5;
          st.active = true;
          st.wantFichaje = true;
          st.ficharOficina = true;
          saveState(st);
          return setFichaje(true);
        },
      },
      {
        when: function () { return isMiEntrar() && (loadState() || {}).chapter === 'fichajes'; },
        selector: '[data-tour="fichar-dni"], #dni',
        title: 'DNI',
        body: 'Introduce el DNI.',
        progress: 'Fichajes · DNI',
        nextLabel: 'Siguiente',
        cardPlacement: 'left-of',
        onShow: function () {
          prefillLoginField('dni');
          if (ui.card) {
            var p = ui.card.querySelector('p');
            if (p) p.innerHTML = fillCredsHint('dni');
          }
        },
      },
      {
        when: function () { return isMiEntrar() && (loadState() || {}).chapter === 'fichajes'; },
        selector: '[data-tour="fichar-pin"], #pin',
        title: 'PIN',
        body: 'Introduce el PIN.',
        progress: 'Fichajes · PIN acceso',
        nextLabel: 'Siguiente',
        cardPlacement: 'left-of',
        onShow: function () {
          prefillLoginField('pin');
          if (ui.card) {
            var p = ui.card.querySelector('p');
            if (p) p.innerHTML = fillCredsHint('pin');
          }
        },
      },
      {
        when: function () { return isMiEntrar() && (loadState() || {}).chapter === 'fichajes'; },
        selector: '[data-tour="fichar-submit"]',
        title: 'Entrar a fichar',
        body: 'Con DNI y PIN, pulsa Entrar.',
        progress: 'Fichajes · acceso',
        waitClick: true,
        nextLabel: 'Ya entré →',
        advanceTo: 8,
        cardPlacement: 'left-of',
        onShow: function () {
          prefillLoginField('dni');
          prefillLoginField('pin');
          var form = qs('[data-tour="fichar-login"]') || qs('form');
          if (!form) return;
          form.addEventListener('submit', function () {
            var cur = loadState();
            if (cur) { cur.step = 8; cur.chapter = 'fichajes'; saveState(cur); }
          }, { once: true });
        },
      },
      {
        when: function () {
          return isMiFichar() && fichajeEstado() === 'fuera' && (loadState() || {}).chapter === 'fichajes';
        },
        selector: '[data-tour="fichar-obra"], #obra',
        title: 'Dónde fichas',
        body: 'En el día a día aquí sale por defecto la obra en la que estás <strong>planificado</strong>. En este tutorial usamos <strong>Oficina</strong> para generar un desvío y verlo luego en auditoría.',
        progress: 'Fichajes · obra',
        nextLabel: 'Siguiente',
        cardPlacement: 'left-of',
        onShow: function (el) {
          ensureOficinaSelected(8);
          selectOficinaInFichajeSelect(el || qs('[data-tour="fichar-obra"], #obra'));
          if (ui.card) {
            var p = ui.card.querySelector('p');
            if (p) {
              p.innerHTML = t('Normalmente eliges (o te sale) la obra donde estás. Aquí, para el tutorial, dejamos <strong>Oficina</strong>.');
            }
          }
          setTimeout(function () { ensureOficinaSelected(4); }, 200);
          setTimeout(function () { ensureOficinaSelected(2); }, 600);
        },
      },
      {
        when: function () {
          return isMiFichar() && fichajeEstado() === 'fuera' && (loadState() || {}).chapter === 'fichajes';
        },
        selector: '[data-tour="fichar-entrada"], [data-tipo="entrada"], button[data-tipo="entrada"]',
        title: 'Ficha entrada',
        body: 'Pulsa <strong>Entrada</strong> para registrar el fichaje en Oficina.',
        progress: 'Fichajes · entrada',
        waitClick: true,
        nextLabel: 'Ya fiché →',
        cardPlacement: 'left-of',
        onShow: function () {
          ensureOficinaSelected(6);
          var btn = qs('[data-tour="fichar-entrada"], [data-tipo="entrada"]');
          if (!btn) return;
          btn.addEventListener('click', function () {
            ensureOficinaSelected(2);
            selectOficinaInFichajeSelect();
            var st = loadState() || {};
            st.step = 10;
            st.fichoOficina = true;
            saveState(st);
          }, true);
        },
        onNext: function () {
          ensureOficinaSelected(2);
          selectOficinaInFichajeSelect();
          var st = loadState() || {};
          st.step = 10;
          st.fichoOficina = true;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          return isMiFichar() && (fichajeEstado() === 'dentro' || (loadState() || {}).step >= 10) &&
            (loadState() || {}).chapter === 'fichajes' && (loadState() || {}).step < 11;
        },
        modal: true,
        title: 'Fichaje hecho',
        body: 'Has fichado en <strong>Oficina</strong>. Primero lo miramos en el <strong>tablero</strong> y después en auditoría.',
        progress: 'Fichajes · puente',
        primaryHref: '/auth/tour-volver-admin?next=' +
          encodeURIComponent('/admin/obras_detailed?tour=fichajes&mode=solo'),
        primaryLabel: 'Ver en el tablero →',
        onBeforeGo: function () {
          var st = loadState() || {};
          st.chapter = 'fichajes';
          st.step = 11;
          st.active = true;
          saveState(st);
        },
      },
      {
        when: function () {
          var st = loadState();
          return (st.chapter === 'fichajes') && (st.step || 0) >= 11 && (st.step || 0) < 12 &&
            !pathIs(/\/sync\/auditoria/) &&
            (pathIs(/\/admin\/obras_detailed/) ||
              (new URLSearchParams(window.location.search || '')).get('tour') === 'fichajes');
        },
        manualTarget: true,
        title: 'En el tablero',
        body: 'El operario ya no está en libres: está en la obra del fichaje. Mira el color de la marca.',
        progress: 'Fichajes · tablero',
        nextLabel: 'Siguiente →',
        onShow: function () {
          highlightWorkerChip();
          if (ui.card) {
            var p = ui.card.querySelector('p');
            if (p) {
              var focus = qs('.sp-tour-highlight-user') || qs('.worker-chip.sp-tour-target');
              var red = focus && focus.querySelector('.dot-danger');
              var green = focus && focus.querySelector('.dot-success, .dot-auto');
              if (!red && !green) {
                red = qs('.kanban-col .worker-chip .dot-danger');
                green = qs('.kanban-col .worker-chip .dot-success, .kanban-col .worker-chip .dot-auto');
              }
              if (red) {
                p.innerHTML = t('Marca en <strong>rojo</strong>: el fichaje no encaja con el plan (desvío o conflicto). Ahora lo resolvemos en auditoría.');
              } else if (green) {
                p.innerHTML = t('Marca en <strong>verde</strong>: el fichaje encaja con el plan. Aun así, en auditoría verás el rastro si hubo resolución.');
              } else {
                p.innerHTML = t('Mira la marca del operario en la obra. <strong>Rojo</strong> = revisar en auditoría; <strong>verde</strong> = correcto.');
              }
            }
          }
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 12;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return (st.chapter === 'fichajes') && (st.step || 0) >= 12 && (st.step || 0) < 13 &&
            !pathIs(/\/sync\/auditoria/);
        },
        selector: '[data-tour="nav-auditoria-fichajes"]',
        title: 'Auditoría de fichajes',
        body: 'Pulsa <strong>Auditoría fichajes</strong> en el menú (sección Jornada). Ahí resolvemos el desvío.',
        progress: 'Fichajes · menú',
        waitClick: true,
        advanceTo: 13,
        ifMissing: 'wait',
        onShow: function (el) {
          if (el) {
            try { el.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch (e) {}
          }
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/sync\/auditoria/) && (st.chapter === 'fichajes') &&
            (st.step || 0) >= 13 && (st.step || 0) < 14;
        },
        selector: '[data-tour="audit-desviaciones"], [data-tour="audit-paracaidistas"], .auditoria-section, main',
        title: 'Tu fichaje en auditoría',
        body: 'Abrimos la sección donde ha caído tu fichaje de Oficina (desviación o sin planificar) y te explicamos cuál es.',
        progress: 'Fichajes · auditoría',
        nextLabel: 'Siguiente →',
        onShow: function () { highlightAuditSection(); },
        onNext: function () {
          var st = loadState() || {};
          st.step = 14;
          saveState(st);
          run();
        },
      },
    ].concat(makeAuditWalkthroughSteps({
      startStep: 14,
      progressPrefix: 'Fichajes',
      includeResolve: true,
      extraWhen: function (st) {
        return !st || st.chapter === 'fichajes' || st.chapter === 'auditoria_fichajes';
      },
      onFinish: function () {
        var st = loadState() || {};
        if (st.mode === 'solo' || st.fromGuide) {
          markAcademiaDone('fichajes');
          finishSoloAndReturn('Auditoría de fichajes lista.');
          return;
        }
        pauseAtChapterEnd();
      },
    }));
  }

  function stepsCochesLibres() {
    function onCochesLibresPage() {
      return pathIs(/\/admin\/vehiculos\/libres/) || pathIs(/\/admin\/vehiculos_libres/);
    }
    return [
      {
        when: function () { return !onCochesLibresPage(); },
        selector: '[data-tour="nav-coches-libres"], a[href*="vehiculos/libres"], a[href*="vehiculos_libres"]',
        title: 'Coches libres',
        body: 'Pulsa <strong>Coches libres</strong> para ver disponibilidad.',
        progress: 'Libres · menú',
        waitClick: true,
        advanceTo: 1,
        ifMissing: 'wait',
        onShow: function (el) {
          if (!el) {
            // Fallback: botón en Flota
            var fallback = qs('a[href*="vehiculos/libres"]');
            if (fallback) {
              fallback.classList.add('sp-tour-target');
              placeHole(fallback);
              placeCardNear(fallback);
              bindNavClick(fallback, 1);
            }
          }
        },
      },
      {
        when: function () { return onCochesLibresPage(); },
        selector: '.vl-kpis, .page-toolbar, main',
        title: 'Quién está libre',
        body: 'Los KPI y la tabla te dicen qué coches no están asignados en el periodo. Úsalo antes de pedir uno más.',
        progress: 'Libres · lectura',
        nextLabel: 'Entendido →',
        onNext: function () {
          var st = loadState() || {};
          st.step = 2;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return !!(st && (st.step || 0) >= 2);
        },
        title: '',
        body: '',
        onShow: function () { pauseAtChapterEnd(); },
      },
    ];
  }

  function stepsAuditoriaVehiculos() {
    return [
      {
        when: function () { return !pathIs(/\/sync\/auditoria-vehiculos/) && !pathIs(/\/sync\/auditoria_vehiculos/); },
        selector: 'a[href*="auditoria-vehiculos"], a[href*="auditoria_vehiculos"]',
        title: 'Auditoría de vehículos',
        body: 'Pulsa la auditoría de vehículos para revisar odómetros y alertas.',
        progress: 'Flota · auditoría',
        waitClick: true,
        advanceTo: 1,
        ifMissing: 'wait',
      },
      {
        when: function () { return pathIs(/auditoria-vehiculos/) || pathIs(/auditoria_vehiculos/); },
        selector: 'main',
        title: 'Qué mirar',
        body: 'Secciones de saltos, desvíos o sin planificar. Resuelve lo urgente; el resto puede esperar.',
        progress: 'Flota · alertas',
        nextLabel: 'Listo →',
        onNext: function () {
          var st = loadState() || {};
          st.step = 2;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return !!(st && (st.step || 0) >= 2);
        },
        title: '',
        body: '',
        onShow: function () { pauseAtChapterEnd(); },
      },
    ];
  }

  // Fix import trabajadores "Continuar a obras" — step 20 next should hand off
  function fixImportAdvance() {
    // handled by rewriting step: use next that sets chapter
  }

  function currentSteps() {
    var state = loadState();
    if (!state || !state.active) return [];
    if (state.chapter === 'obra') return stepsObra();
    if (state.chapter === 'fichaje') return stepsFichaje();
    if (state.chapter === 'import') return stepsImport();
    if (state.chapter === 'tablero_leer') return stepsTableroLeer();
    if (state.chapter === 'tablero_asignar') return stepsTableroAsignar();
    if (state.chapter === 'calendario') return stepsCalendario();
    if (state.chapter === 'tablero_basico') return stepsTableroLeer();
    if (state.chapter === 'planificador_multi') return stepsPlanificadorMulti();
    if (state.chapter === 'fichajes') return stepsFichajes();
    if (state.chapter === 'auditoria_fichajes') return stepsFichajes();
    if (state.chapter === 'registro_jornada') return stepsFichajes();
    if (state.chapter === 'flota') return stepsFlota();
    if (state.chapter === 'coches_libres') return stepsCochesLibres();
    if (state.chapter === 'auditoria_vehiculos') return stepsAuditoriaVehiculos();
    return stepsTrabajadores();
  }

  function pickStep() {
    var state = loadState();
    if (!state || !state.active) return null;
    var steps = currentSteps();
    var idx = state.step || 0;

    // Special: trabajadores step 8 "Continuar" advances to 9 which hands off
    for (var i = idx; i < steps.length; i++) {
      var s = steps[i];
      if (s.when && !s.when()) continue;
      if (i !== idx) {
        state.step = i;
        saveState(state);
      }
      return s;
    }
    for (var j = 0; j < steps.length; j++) {
      if (steps[j].when && steps[j].when()) {
        state.step = j;
        saveState(state);
        return steps[j];
      }
    }
    return null;
  }

  function run() {
    var state = loadState();
    if (!state || state.chapter === 'blocked' || !state.active) {
      if (state && state.pendingComplete) pauseAtChapterEnd();
      return;
    }

    // En /fichaje/fichar solo corre fichaje (seed) o fichajes (academia). No pisar academia.
    if ((isMiEntrar() || isMiFichar()) &&
        state.chapter !== 'fichaje' && state.chapter !== 'fichajes') {
      state.chapter = 'fichaje';
      state.wantFichaje = true;
      if (isMiEntrar()) state.step = 1;
      else if (fichajeEstado() === 'dentro') state.step = 6;
      else state.step = 4;
      saveState(state);
    }

    // Import users: if step>=20 and user clicked Continuar, hand off on next advance
    // Patch step 20 to hand off via custom next
    var step = pickStep();
    if (!step) {
      if (state.chapter === 'demo') {
        saveState(null);
        teardown();
      }
      return;
    }

    if (step.onShow && !step.selector && !step.choices && step.title === '') {
      step.onShow();
      return;
    }
    // Hand-off empty step
    if (step.title === '' && step.onShow) {
      step.onShow();
      return;
    }
    renderStep(step);
  }

  function bindKanbanTourHooks() {
    if (window.__spTourKanbanBound) return;
    window.__spTourKanbanBound = true;
    try {
      if (!window.jQuery) return;
      var $d = window.jQuery(document);
      $d.on('sp-kanban-assigned.spTour', function () {
        var st = loadState() || {};
        if (!st.active || st.chapter !== 'tablero_asignar') return;
        st.assignedOk = true;
        saveState(st);
        run();
      });
      $d.on('sp-kanban-calendar-open.spTour', function () {
        var st = loadState() || {};
        if (!st.active || st.sawCalendario) return;
        if (st.chapter === 'tablero_asignar' || st.chapter === 'calendario') {
          startCalendarioFromBoard();
        }
      });
      $d.on('shown.bs.modal.spTourCal', '#assignmentModal', function () {
        var st = loadState() || {};
        if (!st.active || st.sawCalendario) return;
        if (st.chapter === 'tablero_asignar') {
          startCalendarioFromBoard();
        } else if (st.chapter === 'calendario' && (st.step || 0) < 2) {
          run();
        }
      });
    } catch (e) { /* ignore */ }
  }

  function bindLauncher() {
    document.querySelectorAll('[data-tour-start]').forEach(function (btn) {
      if (btn.getAttribute('data-tour-bound') === '1') return;
      btn.setAttribute('data-tour-bound', '1');
      btn.addEventListener('click', function (ev) {
        var chapter = btn.getAttribute('data-tour-start') || 'tablero_leer';
        if (tryResumePaused(chapter)) {
          ev.preventDefault();
          return;
        }
        var href = btn.getAttribute('href');
        if (btn.tagName === 'A' && href && href !== '#') {
          return;
        }
        ev.preventDefault();
        var mode = btn.getAttribute('data-tour-mode') || '';
        var track = btn.getAttribute('data-tour-track') || '';
        startTour(chapter, {
          mode: mode || (track === 'inicio' ? 'full' : 'solo'),
          track: track || undefined,
          keepCreds: true,
        });
      });
    });
  }

  function bootFromUrl() {
    var params = new URLSearchParams(window.location.search || '');
    var tour = params.get('tour');
    if (tour === 'fichaje_done') {
      var stDone = loadState() || { wantFichaje: true, createdDni: null };
      stDone.active = true;
      stDone.chapter = 'fichaje';
      stDone.step = 7;
      stDone.pendingComplete = false;
      saveState(stDone);
      run();
      return true;
    }
    if (tour === 'import') {
      startTour('import');
      return true;
    }
    if (tour === 'inicio') {
      var prevInicio = loadState();
      if (prevInicio && prevInicio.paused && prevInicio.track === 'inicio') {
        tryResumePaused(prevInicio.chapter);
        return true;
      }
      var midInicio = prevInicio && prevInicio.active && prevInicio.welcomeDone && prevInicio.track === 'inicio';
      if (midInicio) {
        document.body.classList.add('sp-tour-active');
        run();
      } else {
        startTour('tablero_leer', {
          track: 'inicio',
          mode: 'full',
          wantFichaje: true,
          resetWelcome: true,
        });
      }
      postTourStart('seed');
      postTourStart('tablero_leer');
      return true;
    }
    if (tour === 'tablero_leer' || tour === 'tablero_asignar' || tour === 'calendario' || tour === 'tablero_basico') {
      var chBoard = tour === 'tablero_basico' ? 'tablero_leer' : tour;
      var existingB = loadState();
      if (existingB && existingB.paused && tryResumePaused(chBoard)) return true;
      if (existingB && existingB.active && (existingB.chapter === chBoard ||
          (chBoard === 'tablero_asignar' && existingB.chapter === 'calendario') ||
          (chBoard === 'calendario' && existingB.chapter === 'tablero_asignar'))) {
        document.body.classList.add('sp-tour-active');
        run();
        return true;
      }
      var trackB = params.get('track') || (existingB && existingB.track) || null;
      var modeB = params.get('mode') || (trackB === 'inicio' ? 'full' : 'solo');
      startTour(chBoard, {
        mode: modeB,
        track: trackB || undefined,
        keepCreds: true,
      });
      return true;
    }
    // Continuar capítulo fichaje / fichajes en /fichaje (no reiniciar la guía)
    if (tour === 'mi' || tour === 'continuar') {
      var stMi = loadState() || {};
      var chUrl = (params.get('chapter') || '').trim();
      var chMi = 'fichaje';
      if (chUrl === 'fichaje' || chUrl === 'fichajes') chMi = chUrl;
      else if (stMi.chapter === 'fichaje' || stMi.chapter === 'fichajes') chMi = stMi.chapter;
      if (chMi === 'fichajes') {
        stMi.ficharOficina = true;
      } else {
        stMi.ficharOficina = false;
      }
      stMi.active = true;
      stMi.chapter = chMi;
      stMi.wantFichaje = true;
      if (chMi === 'fichajes') {
        if (isMiEntrar()) stMi.step = 5;
        else if (isMiFichar() && fichajeEstado() === 'dentro') stMi.step = 10;
        else if (isMiFichar()) stMi.step = 8;
        else if (typeof stMi.step !== 'number' || stMi.step < 5) stMi.step = 5;
      } else {
        if (isMiEntrar()) stMi.step = 1;
        else if (isMiFichar() && fichajeEstado() === 'dentro') stMi.step = 6;
        else if (isMiFichar()) stMi.step = 4;
        else if (typeof stMi.step !== 'number' || stMi.step < 1) stMi.step = 1;
      }
      saveState(stMi);
      run();
      return true;
    }
    if (tour === '1' || tour === 'start') {
      if (isMiEntrar() || isMiFichar()) {
        var stSafe = loadState() || {};
        stSafe.active = true;
        stSafe.chapter = 'fichaje';
        stSafe.wantFichaje = true;
        stSafe.step = isMiEntrar() ? 1 : (fichajeEstado() === 'dentro' ? 6 : 4);
        saveState(stSafe);
        run();
        return true;
      }
      startTour('tablero_leer', { track: 'inicio', mode: 'full', wantFichaje: true });
      postTourStart('seed');
      return true;
    }
    if (tour === 'trabajadores') {
      var existingT = loadState();
      if (existingT && existingT.paused && tryResumePaused('trabajadores')) return true;
      if (existingT && existingT.active && existingT.chapter === 'trabajadores' && (existingT.step || 0) > 0) {
        document.body.classList.add('sp-tour-active');
        run();
        return true;
      }
      startTour('trabajadores', {
        mode: params.get('mode') || ((existingT && existingT.track === 'inicio') ? 'full' : 'solo'),
        track: params.get('track') || (existingT && existingT.track) || undefined,
        keepCreds: true,
      });
      return true;
    }
    if (tour === 'obra') {
      var existingO = loadState();
      if (existingO && existingO.paused && tryResumePaused('obra')) return true;
      if (existingO && existingO.active && existingO.chapter === 'obra') {
        document.body.classList.add('sp-tour-active');
        run();
        return true;
      }
      startTour('obra', {
        mode: params.get('mode') || ((existingO && existingO.track === 'inicio') ? 'full' : 'full'),
        track: params.get('track') || (existingO && existingO.track) || undefined,
        keepCreds: true,
      });
      return true;
    }
    if (tour === 'fichaje') {
      var stF = loadState() || {};
      var cont = params.get('continue') === '1' || params.get('mode') !== 'solo';
      if (stF.active && stF.chapter === 'fichaje' && (stF.step || 0) > 0 &&
          (cont || params.get('continue') === '1' || (stF.step || 0) >= 7)) {
        stF.active = true;
        saveState(stF);
        document.body.classList.add('sp-tour-active');
        run();
        return true;
      }
      var modeF = params.get('mode') === 'solo' ? 'solo' : 'full';
      startTour('fichaje', {
        mode: modeF,
        fromGuide: modeF !== 'solo' && !isInicioTrack(stF),
        track: stF.track || params.get('track') || undefined,
        keepCreds: true,
        step: 0,
        ficharOficina: false,
      });
      return true;
    }
    var academiaTours = [
      'tablero_basico', 'planificador_multi', 'fichajes',
      'auditoria_fichajes', 'registro_jornada',
      'flota', 'coches_libres', 'auditoria_vehiculos',
    ];
    if (academiaTours.indexOf(tour) >= 0) {
      var ch = (tour === 'auditoria_fichajes' || tour === 'registro_jornada') ? 'fichajes' : tour;
      var existing = loadState();
      // Continuar capítulo a medias (p. ej. tras volver de fichaje al registro)
      if (existing && existing.active && existing.chapter === ch && (existing.step || 0) > 0) {
        document.body.classList.add('sp-tour-active');
        run();
        return true;
      }
      startTour(ch, { mode: params.get('mode') || 'solo' });
      return true;
    }
    return false;
  }

  function boot() {
    wrapAssignmentConflictForTour();
    bindLauncher();
    bindKanbanTourHooks();
    try {
      if (window.__SP_TOUR_CHAPTER__ === 'fichajes' || window.__SP_TOUR_CHAPTER__ === 'fichaje') {
        var stBoot = loadState() || {};
        stBoot.active = true;
        stBoot.chapter = window.__SP_TOUR_CHAPTER__;
        stBoot.wantFichaje = true;
        if (window.__SP_TOUR_FORCE_OFICINA__ || stBoot.chapter === 'fichajes') {
          stBoot.ficharOficina = true;
        }
        saveState(stBoot);
      }
      if (window.__SP_TOUR_FORCE_OFICINA__ || qs('.fichaje[data-tour-force-oficina]')) {
        ensureOficinaSelected(10);
        setTimeout(function () { ensureOficinaSelected(6); }, 50);
        setTimeout(function () { ensureOficinaSelected(4); }, 250);
      } else if (window.__SP_TOUR_CHAPTER__ === 'fichaje') {
        ensureCreatedObraSelected(8);
        setTimeout(function () { ensureCreatedObraSelected(4); }, 250);
      }
    } catch (eBoot) { /* ignore */ }
    if (bootFromUrl()) return;
    var state = loadState();
    if (state && state.active) {
      run();
    } else if (state && state.pendingComplete) {
      pauseAtChapterEnd();
    }
  }

  window.SignaPlanTour = {
    start: startTour,
    stop: stopTour,
    skipSection: skipSection,
    run: run,
    loadState: loadState,
    tryResumePaused: tryResumePaused,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

  window.addEventListener('resize', function () {
    var state = loadState();
    if (state && state.active && ui.hole) run();
  });
})(window, document);
