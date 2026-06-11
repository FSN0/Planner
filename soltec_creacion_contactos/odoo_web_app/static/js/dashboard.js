(function () {
  window.empleadosDisponibles = [];

  var isMobile = window.matchMedia('(max-width: 768px)').matches;

  function select2Base(placeholder) {
    return {
      placeholder: placeholder,
      width: '100%',
      dropdownAutoWidth: !isMobile,
      minimumResultsForSearch: isMobile ? 10 : 0,
    };
  }

  function initSelect2() {
    var empresaTemplate = function (state) {
      if (!state.id) return state.text;
      var parts = state.text.match(/^(.+?)(\s*\(.+\))?$/);
      var name = parts ? parts[1] : state.text;
      var vat = parts && parts[2] ? parts[2].replace(/[()]/g, '') : '';
      if (vat) {
        return $('<span><i class="fas fa-building text-muted mr-1"></i>' + name +
          ' <span class="alta-badge-vat">' + vat + '</span></span>');
      }
      return $('<span><i class="fas fa-building text-muted mr-1"></i>' + state.text + '</span>');
    };

    var empOpts = $.extend({}, select2Base('Buscar subcontrata…'), {
      templateResult: empresaTemplate,
      templateSelection: empresaTemplate,
    });
    $('#empresa_id_select').select2(empOpts);
    $('#empresa_contrato_id').select2($.extend({}, empOpts, { placeholder: 'Buscar empresa…' }));
    $('#obra_id_select').select2($.extend({}, select2Base('Buscar obra…'), {
      allowClear: true,
      templateResult: function (state) {
        if (!state.id) return state.text;
        return $('<span><i class="fas fa-hard-hat text-muted mr-1"></i>' + state.text + '</span>');
      },
    }));
  }

  function initFlatpickr() {
    if (typeof flatpickr === 'undefined') return;
    var fpOpts = {
      locale: 'es',
      dateFormat: 'Y-m-d',
      altInput: true,
      altFormat: 'd/m/Y',
      allowInput: true,
      disableMobile: true,
    };
    window.fpInicio = flatpickr('#fecha_inicio', fpOpts);
    window.fpFin = flatpickr('#fecha_fin', fpOpts);

    var today = new Date();
    window.fpInicio.setDate(today);
    var nextYear = new Date(today);
    nextYear.setFullYear(nextYear.getFullYear() + 1);
    window.fpFin.setDate(nextYear);
  }

  function setTab(active) {
    var isTrab = active === 'trabajador';
    $('#panelTrabajador').toggleClass('tab-pane-hidden', !isTrab);
    $('#panelContrato').toggleClass('tab-pane-hidden', isTrab);
    $('#tabTrabajador').toggleClass('is-active', isTrab);
    $('#tabContrato').toggleClass('is-active', !isTrab);
  }

  function setDatePreset(months) {
    var start = new Date();
    window.fpInicio.setDate(start);
    var end = new Date(start);
    end.setMonth(end.getMonth() + months);
    window.fpFin.setDate(end);
  }

  function renderOperariosEmpty(msg) {
    $('#lines_container').html(
      '<tr class="alta-operarios-empty"><td colspan="3"><i class="fas fa-info-circle"></i> ' + msg + '</td></tr>'
    );
  }

  function addOperarioRow() {
    if (!window.empleadosDisponibles.length) {
      alert('Selecciona primero una empresa con operarios registrados.');
      return;
    }
    $('.alta-operarios-empty').remove();
    var options = '<option value="" disabled selected>Elegir operario</option>';
    window.empleadosDisponibles.forEach(function (emp) {
      options += '<option value="' + emp.id + '">' + emp.name + '</option>';
    });
    var coste = $('#coste_hora').val() || '';
    var row = $(
      '<tr class="alta-operario-row">' +
      '<td><select name="operario_id[]" required class="form-control form-control-sm operario-select">' + options + '</select></td>' +
      '<td><div class="alta-input-euro"><input type="number" step="0.01" name="operario_coste[]" required class="form-control form-control-sm" value="' + coste + '" placeholder="0.00"><span>€/h</span></div></td>' +
      '<td class="text-right"><button type="button" class="btn btn-sm btn-outline-danger remove-line" title="Quitar"><i class="fas fa-times"></i></button></td>' +
      '</tr>'
    );
    $('#lines_container').append(row);
    row.find('.operario-select').select2({ width: '100%', placeholder: 'Operario…' });
    row.find('.remove-line').on('click', function () {
      row.remove();
      if (!$('#lines_container tr.alta-operario-row').length) {
        renderOperariosEmpty('Sin líneas. Pulsa «Añadir operario» si necesitas tarifas individuales.');
      }
    });
  }

  $(document).ready(function () {
    initSelect2();
    initFlatpickr();

    $('#tabTrabajador').on('click', function () { setTab('trabajador'); });
    $('#tabContrato').on('click', function () { setTab('contrato'); });

    $('#btnToggleEmpresa').on('click', function () {
      var box = $('#campos_nueva_empresa');
      if (!box.hasClass('is-visible')) {
        box.addClass('is-visible');
        $('#nombre_empresa_input').prop('required', true);
        $('#empresa_id_select').next('.select2-container').hide();
        $('#empresa_id_select').prop('required', false).val(null).trigger('change');
        $(this).html('<i class="fas fa-times"></i> Cancelar');
        $(this).addClass('btn-admin-danger').removeClass('btn-admin-outline');
      } else {
        box.removeClass('is-visible');
        $('#nombre_empresa_input, #cif_empresa_input').prop('required', false).val('');
        $('#empresa_id_select').next('.select2-container').show();
        $('#empresa_id_select').prop('required', true);
        $(this).html('<i class="fas fa-plus"></i> Nueva empresa');
        $(this).removeClass('btn-admin-danger').addClass('btn-admin-outline');
      }
    });

    $('[data-date-preset]').on('click', function () {
      setDatePreset(parseInt($(this).data('date-preset'), 10));
    });

    $('#empresa_contrato_id').on('change', async function () {
      var empId = $(this).val();
      if (!empId) return;
      renderOperariosEmpty('Cargando operarios…');
      $('#precio_hint').html('<i class="fas fa-spinner fa-spin"></i> Calculando tarifa media…');
      window.empleadosDisponibles = [];
      try {
        var res = await fetch('/api/empresa_data/' + empId);
        var data = await res.json();
        if (data.success) {
          if (data.precio_medio > 0) {
            $('#coste_hora').val(data.precio_medio);
            $('#precio_hint').html('<i class="fas fa-chart-line text-success"></i> Media histórica: <strong>' + data.precio_medio + ' €/h</strong>');
          } else {
            $('#coste_hora').val('');
            $('#precio_hint').html('<i class="fas fa-info-circle"></i> Sin historial. Introduce el precio manualmente.');
          }
          window.empleadosDisponibles = data.empleados || [];
          if (window.empleadosDisponibles.length) {
            renderOperariosEmpty('Sin líneas. Pulsa «Añadir operario» para tarifas individuales.');
          } else {
            renderOperariosEmpty('Esta empresa no tiene operarios en Odoo todavía.');
          }
        } else {
          renderOperariosEmpty('Error al cargar operarios.');
          $('#precio_hint').text('Error al cargar datos de la empresa.');
        }
      } catch (e) {
        renderOperariosEmpty('Error de conexión.');
        $('#precio_hint').text('Error de red al conectar con Odoo.');
      }
    });

    $('#btnAddLine').on('click', function (e) {
      e.preventDefault();
      addOperarioRow();
    });

    renderOperariosEmpty('Selecciona una empresa para ver sus operarios.');
  });
})();
