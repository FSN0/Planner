/**
 * Detalle clicable de KPIs del panel (fichajes / asignaciones / auditoría).
 * Incluye búsqueda global y cabeceras ordenables.
 */
(function (global) {
  'use strict';

  var state = {
    kind: null,
    fecha: null,
    apiUrl: '',
    today: '',
    auditUrl: '',
    canResolveAudit: false,
    labels: {},
    loading: false,
    columns: [],
    allRows: [],
    truncated: false,
    filterText: '',
    sortCol: null,
    sortDir: 'asc',
  };

  var COL_LABELS = {
    fecha: 'Fecha',
    nombre: 'Nombre',
    dni: 'DNI',
    obra: 'Obra',
    empresa: 'Empresa',
    obra_plan: 'Obra plan.',
    obra_real: 'Obra real',
    entrada: 'Entrada',
    salida: 'Salida',
    estado: 'Estado',
  };

  var KIND_TITLES = {
    fichajes: 'Fichajes',
    asignaciones: 'Hoy en obra',
    auditoria: 'Auditoría pendiente',
  };

  function byId(id) {
    return document.getElementById(id);
  }

  function esc(s) {
    if (s == null) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function label(key, fallback) {
    return (state.labels && state.labels[key]) || fallback || key;
  }

  function shiftDate(iso, days) {
    var parts = iso.split('-');
    var d = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
    d.setDate(d.getDate() + days);
    var y = d.getFullYear();
    var m = String(d.getMonth() + 1).padStart(2, '0');
    var day = String(d.getDate()).padStart(2, '0');
    return y + '-' + m + '-' + day;
  }

  function formatDateDisplay(iso) {
    if (!iso) return '';
    var parts = iso.split('-');
    if (parts.length !== 3) return iso;
    return parts[2] + '/' + parts[1] + '/' + parts[0];
  }

  function cellDisplay(col, row) {
    var val = row[col];
    if (col === 'fecha' && val) return formatDateDisplay(val);
    if (val == null || val === '') return '—';
    return String(val);
  }

  function rowSearchBlob(row, cols) {
    return cols
      .map(function (c) {
        return cellDisplay(c, row).toLowerCase();
      })
      .join(' ');
  }

  function filteredRows() {
    var cols = state.columns;
    var q = (state.filterText || '').trim().toLowerCase();
    var rows = state.allRows || [];
    if (q) {
      rows = rows.filter(function (row) {
        return rowSearchBlob(row, cols).indexOf(q) !== -1;
      });
    }
    if (state.sortCol) {
      var col = state.sortCol;
      var dir = state.sortDir === 'desc' ? -1 : 1;
      rows = rows.slice().sort(function (a, b) {
        var av = cellDisplay(col, a).toLowerCase();
        var bv = cellDisplay(col, b).toLowerCase();
        if (av < bv) return -1 * dir;
        if (av > bv) return 1 * dir;
        return 0;
      });
    }
    return rows;
  }

  function setLoading() {
    var body = byId('panelKpiDetailBody');
    if (body) {
      body.innerHTML =
        '<tr><td colspan="8" class="table-empty-state"><i class="fas fa-spinner fa-spin"></i> ' +
        esc(label('loading', 'Cargando…')) +
        '</td></tr>';
    }
  }

  function renderHead() {
    var head = byId('panelKpiDetailHead');
    if (!head) return;
    var cols = state.columns;
    head.innerHTML =
      '<tr class="header-row">' +
      cols
        .map(function (c) {
          var active = state.sortCol === c;
          var icon = 'fa-sort';
          if (active) {
            icon = state.sortDir === 'desc' ? 'fa-sort-down' : 'fa-sort-up';
          }
          return (
            '<th class="sortable-col' +
            (active ? ' is-sorted' : '') +
            '" data-sort-col="' +
            esc(c) +
            '" role="button" tabindex="0">' +
            '<span class="sortable-label">' +
            esc(label('col_' + c, COL_LABELS[c] || c)) +
            '</span>' +
            '<i class="fas ' +
            icon +
            ' sort-icon"></i>' +
            '</th>'
          );
        })
        .join('') +
      '</tr>';
  }

  function renderBody(rows) {
    var body = byId('panelKpiDetailBody');
    if (!body) return;
    var cols = state.columns;
    if (!rows.length) {
      body.innerHTML =
        '<tr><td colspan="' +
        Math.max(cols.length, 1) +
        '" class="table-empty-state"><i class="fas fa-inbox"></i>' +
        esc(
          state.filterText
            ? label('no_match', 'Ningún resultado para esa búsqueda.')
            : label('empty', 'Sin registros para esta consulta.')
        ) +
        '</td></tr>';
      return;
    }
    body.innerHTML = rows
      .map(function (row) {
        var attrs = '';
        if (row.user_id && row.fecha) {
          attrs =
            ' class="fila-fichaje-auditoria" style="cursor:pointer" data-user-id="' +
            esc(row.user_id) +
            '" data-fecha="' +
            esc(row.fecha) +
            '"';
        }
        var cells = cols
          .map(function (c) {
            return '<td>' + esc(cellDisplay(c, row)) + '</td>';
          })
          .join('');
        return '<tr' + attrs + '>' + cells + '</tr>';
      })
      .join('');
  }

  function updateMeta(visibleCount) {
    var countEl = byId('panelKpiDetailCount');
    var subtitle = byId('panelKpiDetailSubtitle');
    var title = byId('panelKpiDetailTitle');
    var auditLink = byId('panelKpiDetailAuditLink');

    var kindTitle = label('kind_' + state.kind, KIND_TITLES[state.kind] || state.kind);
    if (title) title.textContent = kindTitle;

    var fechaTxt = state.fecha
      ? formatDateDisplay(state.fecha)
      : label('all_pending', 'Todas las pendientes');
    if (subtitle) {
      var bits = [fechaTxt];
      if (state.kind === 'fichajes') {
        bits.push(label('physical_only', 'Solo entradas físicas'));
      }
      if (state.truncated) {
        bits.push(label('truncated', 'Mostrando las primeras filas'));
      }
      subtitle.textContent = bits.join(' · ');
    }
    if (countEl) {
      var total = state.allRows.length;
      if (state.filterText && visibleCount !== total) {
        countEl.textContent =
          visibleCount +
          ' / ' +
          total +
          ' ' +
          label('records', 'registros');
      } else {
        countEl.textContent = total + ' ' + label('records', 'registros');
      }
    }
    if (auditLink) {
      if (state.kind === 'auditoria' && state.auditUrl) {
        auditLink.href = state.auditUrl;
        auditLink.classList.remove('d-none');
      } else {
        auditLink.classList.add('d-none');
      }
    }
  }

  function applyView() {
    renderHead();
    var rows = filteredRows();
    updateMeta(rows.length);
    renderBody(rows);
  }

  function fetchDetail() {
    if (!state.kind || !state.apiUrl) return;
    state.loading = true;
    setLoading();

    var url = state.apiUrl + '?kind=' + encodeURIComponent(state.kind);
    if (state.fecha) {
      url += '&fecha=' + encodeURIComponent(state.fecha);
    } else if (state.kind !== 'auditoria') {
      url += '&fecha=' + encodeURIComponent(state.today);
    }

    fetch(url, { headers: { Accept: 'application/json' } })
      .then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok, data: data };
        });
      })
      .then(function (result) {
        state.loading = false;
        if (!result.ok || !result.data.success) {
          var body = byId('panelKpiDetailBody');
          if (body) {
            body.innerHTML =
              '<tr><td colspan="8" class="table-empty-state text-danger">' +
              esc(
                (result.data && result.data.message) ||
                  label('error', 'No se pudo cargar el detalle.')
              ) +
              '</td></tr>';
          }
          return;
        }
        if (result.data.fecha) {
          state.fecha = result.data.fecha;
          var input = byId('panelKpiDetailFecha');
          if (input) input.value = result.data.fecha;
        } else if (state.kind === 'auditoria' && !state.fecha) {
          var inputEmpty = byId('panelKpiDetailFecha');
          if (inputEmpty) inputEmpty.value = '';
        }
        state.columns = result.data.columns || [];
        state.allRows = result.data.rows || [];
        state.truncated = !!result.data.truncated;
        applyView();
      })
      .catch(function () {
        state.loading = false;
        var body = byId('panelKpiDetailBody');
        if (body) {
          body.innerHTML =
            '<tr><td colspan="8" class="table-empty-state text-danger">' +
            esc(label('error', 'No se pudo cargar el detalle.')) +
            '</td></tr>';
        }
      });
  }

  function open(kind, fecha) {
    state.kind = kind;
    state.fecha =
      fecha ||
      (kind === 'auditoria' ? '' : state.today) ||
      state.today;
    state.filterText = '';
    state.sortCol = null;
    state.sortDir = 'asc';
    state.allRows = [];
    state.columns = [];

    var input = byId('panelKpiDetailFecha');
    if (input) {
      input.value = state.fecha || '';
      input.required = kind !== 'auditoria';
    }
    var search = byId('panelKpiDetailSearch');
    if (search) search.value = '';

    var modal = byId('modalPanelKpiDetail');
    if (modal && window.jQuery) {
      window.jQuery(modal).modal('show');
    } else if (modal) {
      modal.classList.add('show');
      modal.style.display = 'block';
    }
    fetchDetail();
  }

  function onSortClick(col) {
    if (state.sortCol === col) {
      state.sortDir = state.sortDir === 'asc' ? 'desc' : 'asc';
    } else {
      state.sortCol = col;
      state.sortDir = 'asc';
    }
    applyView();
  }

  function bindControls() {
    var input = byId('panelKpiDetailFecha');
    if (input) {
      input.addEventListener('change', function () {
        state.fecha = input.value || (state.kind === 'auditoria' ? '' : state.today);
        fetchDetail();
      });
    }
    var prev = byId('panelKpiDetailPrev');
    if (prev) {
      prev.addEventListener('click', function () {
        var base = state.fecha || state.today;
        if (!base) return;
        state.fecha = shiftDate(base, -1);
        if (input) input.value = state.fecha;
        fetchDetail();
      });
    }
    var next = byId('panelKpiDetailNext');
    if (next) {
      next.addEventListener('click', function () {
        var base = state.fecha || state.today;
        if (!base) return;
        state.fecha = shiftDate(base, 1);
        if (input) input.value = state.fecha;
        fetchDetail();
      });
    }
    var todayBtn = byId('panelKpiDetailToday');
    if (todayBtn) {
      todayBtn.addEventListener('click', function () {
        state.fecha = state.today;
        if (input) input.value = state.fecha;
        fetchDetail();
      });
    }
    var search = byId('panelKpiDetailSearch');
    if (search) {
      search.addEventListener('input', function () {
        state.filterText = search.value || '';
        applyView();
      });
    }
    var head = byId('panelKpiDetailHead');
    if (head) {
      head.addEventListener('click', function (e) {
        var th = e.target.closest('th[data-sort-col]');
        if (!th) return;
        onSortClick(th.getAttribute('data-sort-col'));
      });
      head.addEventListener('keydown', function (e) {
        if (e.key !== 'Enter' && e.key !== ' ') return;
        var th = e.target.closest('th[data-sort-col]');
        if (!th) return;
        e.preventDefault();
        onSortClick(th.getAttribute('data-sort-col'));
      });
    }
    var body = byId('panelKpiDetailBody');
    if (body) {
      body.addEventListener('click', function (e) {
        var row = e.target.closest('tr[data-user-id][data-fecha]');
        if (!row) return;
        if (typeof global.PersonDayTimeline === 'undefined' || !global.PersonDayTimeline.openModal) {
          return;
        }
        global.PersonDayTimeline.openModal(
          row.getAttribute('data-user-id'),
          row.getAttribute('data-fecha'),
          {
            modalId: 'modalTimelineFichaje',
            apiBase: '/sync/timeline_dia',
            canResolveAudit: !!state.canResolveAudit,
            auditUrl: state.auditUrl,
          }
        );
      });
    }
  }

  function bindKpis() {
    document.querySelectorAll('[data-kpi-detail]').forEach(function (el) {
      el.addEventListener('click', function () {
        var kind = el.getAttribute('data-kpi-detail');
        var raw = el.getAttribute('data-kpi-fecha');
        open(kind, raw === null ? state.today : raw);
      });
      el.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          var kind = el.getAttribute('data-kpi-detail');
          var raw = el.getAttribute('data-kpi-fecha');
          open(kind, raw === null ? state.today : raw);
        }
      });
    });
  }

  function init(opts) {
    opts = opts || {};
    state.apiUrl = opts.apiUrl || '';
    state.today = opts.today || '';
    state.auditUrl = opts.auditUrl || '';
    state.canResolveAudit = !!opts.canResolveAudit;
    state.labels = opts.labels || {};
    bindControls();
    bindKpis();
  }

  global.PanelKpiDetail = {
    init: init,
    open: open,
  };
})(window);
