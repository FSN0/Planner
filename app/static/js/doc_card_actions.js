(function () {
  'use strict';

  function swalFire(opts) {
    if (typeof window.adminSwal === 'function') return window.adminSwal(opts);
    if (typeof Swal === 'undefined') return Promise.resolve({ isConfirmed: false });
    return Swal.fire(Object.assign({
      customClass: {
        popup: 'admin-swal-popup',
        title: 'admin-swal-title',
        htmlContainer: 'admin-swal-html',
        actions: 'admin-swal-actions',
        confirmButton: 'admin-swal-btn admin-swal-btn-primary',
        cancelButton: 'admin-swal-btn admin-swal-btn-ghost',
      },
      buttonsStyling: false,
    }, opts));
  }

  function findHistorialTpl(btn) {
    var el = btn.nextElementSibling;
    while (el) {
      if (el.classList && el.classList.contains('js-doc-historial-tpl')) return el;
      el = el.nextElementSibling;
    }
    var parent = btn.parentElement;
    if (parent) {
      var direct = parent.querySelector(':scope > .js-doc-historial-tpl');
      if (direct) return direct;
    }
    var card = btn.closest('.doc-card');
    return card ? card.querySelector('.js-doc-historial-tpl') : null;
  }

  function submitResubir(rform, file, caduca) {
    var post = document.createElement('form');
    post.method = 'post';
    post.enctype = 'multipart/form-data';
    post.action = rform.getAttribute('action') || window.location.href;
    post.style.display = 'none';

    Array.prototype.forEach.call(rform.querySelectorAll('input'), function (inp) {
      if (inp.type === 'file') return;
      if (inp.name === 'caduca_el') return;
      var clone = document.createElement('input');
      clone.type = 'hidden';
      clone.name = inp.name;
      clone.value = inp.value;
      post.appendChild(clone);
    });

    if (caduca != null) {
      var c = document.createElement('input');
      c.type = 'hidden';
      c.name = 'caduca_el';
      c.value = caduca;
      post.appendChild(c);
    }

    var fileSrc = rform.querySelector('input[type="file"]');
    var fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.name = fileSrc ? fileSrc.name : 'archivo';
    if (typeof DataTransfer !== 'undefined') {
      var dt = new DataTransfer();
      dt.items.add(file);
      fileInput.files = dt.files;
    }
    post.appendChild(fileInput);
    document.body.appendChild(post);
    if (!fileInput.files || !fileInput.files.length) {
      document.body.removeChild(post);
      return false;
    }
    post.submit();
    return true;
  }

  document.addEventListener('click', function (ev) {
    var validarBtn = ev.target.closest('.js-doc-validar');
    if (validarBtn) {
      ev.preventDefault();
      var vwrap = validarBtn.closest('.doc-toolbar');
      var vform = vwrap && vwrap.querySelector('.js-doc-validar-form');
      if (!vform) return;
      var hasCaduca = validarBtn.getAttribute('data-has-caduca') === '1';
      var needsInicio = validarBtn.getAttribute('data-needs-inicio') === '1';
      var caducaVal = validarBtn.getAttribute('data-caduca') || '';
      var caducaLabel = validarBtn.getAttribute('data-caduca-label') || 'Caduca el';
      var aceptarLabel = validarBtn.getAttribute('data-aceptar-label') || 'Aceptar caducado';
      var inicioLabel = validarBtn.getAttribute('data-inicio-label') || 'Inicio';
      var caducaRequired = validarBtn.getAttribute('data-caduca-required') || 'Indica la fecha de caducidad';

      if (!hasCaduca && !needsInicio) {
        vform.submit();
        return;
      }

      var html = '<div class="doc-swal-resubir">';
      if (hasCaduca) {
        html += '<label class="doc-caduca-field"><span>' + caducaLabel + '</span>'
          + '<input type="date" class="js-doc-swal-caduca" value="' + caducaVal + '" required></label>';
        html += '<label class="doc-inline-check" style="margin-top:4px;">'
          + '<input type="checkbox" class="js-doc-swal-aceptado">'
          + '<span>' + aceptarLabel + '</span></label>';
      }
      if (needsInicio) {
        html += '<label class="doc-caduca-field"><span>' + inicioLabel + '</span>'
          + '<input type="date" class="js-doc-swal-inicio"></label>';
      }
      html += '</div>';

      swalFire({
        title: validarBtn.getAttribute('data-title') || 'Validar',
        html: html,
        showCancelButton: true,
        focusConfirm: false,
        confirmButtonText: validarBtn.getAttribute('data-confirm') || 'Validar',
        cancelButtonText: validarBtn.getAttribute('data-cancel') || 'Cancelar',
        preConfirm: function () {
          var popup = typeof Swal !== 'undefined' && Swal.getPopup ? Swal.getPopup() : null;
          if (!popup) return false;
          var caducaEl = popup.querySelector('.js-doc-swal-caduca');
          var aceptadoEl = popup.querySelector('.js-doc-swal-aceptado');
          var inicioEl = popup.querySelector('.js-doc-swal-inicio');
          if (hasCaduca && (!caducaEl || !caducaEl.value)) {
            if (typeof Swal !== 'undefined' && Swal.showValidationMessage) {
              Swal.showValidationMessage(caducaRequired);
            }
            return false;
          }
          return {
            caduca: caducaEl ? caducaEl.value : '',
            aceptado: !!(aceptadoEl && aceptadoEl.checked),
            inicio: inicioEl ? inicioEl.value : '',
          };
        },
      }).then(function (result) {
        if (!result || !result.isConfirmed || !result.value) return;
        var caducaField = vform.querySelector('input[name="caduca_el"]');
        var aceptadoField = vform.querySelector('input[name="aceptado_caducado"]');
        var inicioField = vform.querySelector('input[name="fecha_inicio"]');
        if (caducaField) caducaField.value = result.value.caduca || '';
        if (aceptadoField) aceptadoField.value = result.value.aceptado ? 'on' : '';
        if (inicioField) inicioField.value = result.value.inicio || '';
        vform.submit();
      });
      return;
    }

    var rechazarBtn = ev.target.closest('.js-doc-rechazar');
    if (rechazarBtn) {
      ev.preventDefault();
      var wrap = rechazarBtn.closest('.doc-toolbar');
      var form = wrap && wrap.querySelector('.js-doc-rechazar-form');
      if (!form) return;
      swalFire({
        title: rechazarBtn.getAttribute('data-title') || 'Rechazar',
        input: 'textarea',
        inputPlaceholder: rechazarBtn.getAttribute('data-placeholder') || '',
        showCancelButton: true,
        focusCancel: true,
        confirmButtonText: rechazarBtn.getAttribute('data-confirm') || 'Rechazar',
        cancelButtonText: rechazarBtn.getAttribute('data-cancel') || 'Cancelar',
        customClass: {
          popup: 'admin-swal-popup',
          title: 'admin-swal-title',
          htmlContainer: 'admin-swal-html',
          actions: 'admin-swal-actions',
          confirmButton: 'admin-swal-btn admin-swal-btn-danger',
          cancelButton: 'admin-swal-btn admin-swal-btn-ghost',
        },
        buttonsStyling: false,
      }).then(function (result) {
        if (!result || !result.isConfirmed) return;
        var nota = form.querySelector('input[name="nota_oficina"]');
        if (nota) nota.value = (result.value || '').trim();
        form.submit();
      });
      return;
    }

    var histBtn = ev.target.closest('.js-doc-historial');
    if (histBtn) {
      ev.preventDefault();
      var tpl = findHistorialTpl(histBtn);
      swalFire({
        title: histBtn.getAttribute('data-title') || 'Historial',
        html: (tpl && tpl.innerHTML) || '<p>—</p>',
        showConfirmButton: true,
        confirmButtonText: 'OK',
        width: '32rem',
      });
      return;
    }

    var resubirBtn = ev.target.closest('.js-doc-resubir');
    if (resubirBtn) {
      ev.preventDefault();
      var toolbar = resubirBtn.closest('.doc-toolbar');
      var rform = toolbar && toolbar.querySelector('.js-doc-resubir-form');
      if (!rform) return;
      var hasCaducaR = resubirBtn.getAttribute('data-has-caduca') === '1';
      var caducaValR = resubirBtn.getAttribute('data-caduca') || '';
      var fileLabel = resubirBtn.getAttribute('data-file-label') || 'Archivo';
      var caducaLabelR = resubirBtn.getAttribute('data-caduca-label') || 'Caduca el';
      var htmlR = '<div class="doc-swal-resubir">'
        + '<label class="doc-swal-file"><span>' + fileLabel + '</span>'
        + '<input type="file" class="js-doc-swal-file" accept=".pdf,.png,.jpg,.jpeg,.webp,application/pdf,image/*"></label>';
      if (hasCaducaR) {
        htmlR += '<label class="doc-caduca-field"><span>' + caducaLabelR + '</span>'
          + '<input type="date" class="js-doc-swal-caduca" value="' + caducaValR + '"></label>';
      }
      htmlR += '</div>';
      swalFire({
        title: resubirBtn.getAttribute('data-title') || 'Resubir',
        html: htmlR,
        showCancelButton: true,
        focusConfirm: false,
        confirmButtonText: resubirBtn.getAttribute('data-confirm') || 'Subir',
        cancelButtonText: resubirBtn.getAttribute('data-cancel') || 'Cancelar',
        preConfirm: function () {
          var popup = typeof Swal !== 'undefined' && Swal.getPopup ? Swal.getPopup() : null;
          var fileInput = popup && popup.querySelector('.js-doc-swal-file');
          if (!fileInput || !fileInput.files || !fileInput.files.length) {
            if (typeof Swal !== 'undefined' && Swal.showValidationMessage) {
              Swal.showValidationMessage(fileLabel);
            }
            return false;
          }
          var caducaEl = popup.querySelector('.js-doc-swal-caduca');
          if (hasCaducaR && caducaEl && !caducaEl.value) {
            if (typeof Swal !== 'undefined' && Swal.showValidationMessage) {
              Swal.showValidationMessage(caducaLabelR);
            }
            return false;
          }
          return {
            file: fileInput.files[0],
            caduca: hasCaducaR && caducaEl ? caducaEl.value : '',
          };
        },
      }).then(function (result) {
        if (!result || !result.isConfirmed || !result.value) return;
        if (!submitResubir(rform, result.value.file, result.value.caduca)) {
          swalFire({
            icon: 'error',
            title: fileLabel,
            text: 'No se pudo adjuntar el archivo. Prueba de nuevo.',
          });
        }
      });
    }
  });

  function formHasFiles(form) {
    var inputs = form.querySelectorAll('input[type="file"]');
    for (var i = 0; i < inputs.length; i++) {
      if (inputs[i].files && inputs[i].files.length) return true;
    }
    return false;
  }

  function markFormReady(form) {
    if (!form) return;
    form.classList.toggle('is-ready', formHasFiles(form));
  }

  function updatePickLabel(input) {
    var label = input.parentElement && input.parentElement.querySelector('.doc-pick-text');
    if (!label) return;
    if (!label.getAttribute('data-default')) {
      label.setAttribute('data-default', label.textContent || 'Elegir');
    }
    var file = input.files && input.files[0];
    label.textContent = file ? file.name : label.getAttribute('data-default');
  }

  /* Persist selected files so Subir on one card does not wipe the others. */
  var PENDING_DB = 'signaplan-doc-pending';
  var PENDING_STORE = 'files';

  function openPendingDb() {
    return new Promise(function (resolve, reject) {
      if (!window.indexedDB) {
        reject(new Error('no-idb'));
        return;
      }
      var req = indexedDB.open(PENDING_DB, 1);
      req.onupgradeneeded = function () {
        var db = req.result;
        if (!db.objectStoreNames.contains(PENDING_STORE)) {
          db.createObjectStore(PENDING_STORE);
        }
      };
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = function () { reject(req.error); };
    });
  }

  function pendingInputKey(form, input) {
    var tipo = form.querySelector('input[name="tipo_id"]');
    var uid = form.querySelector('input[name="user_id"]');
    return [
      window.location.pathname,
      't' + (tipo ? tipo.value : ''),
      'u' + (uid ? uid.value : '0'),
      input.name || 'archivo',
    ].join('|');
  }

  function idbPut(key, value) {
    return openPendingDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(PENDING_STORE, 'readwrite');
        tx.oncomplete = function () { resolve(); };
        tx.onerror = function () { reject(tx.error); };
        if (value == null) tx.objectStore(PENDING_STORE).delete(key);
        else tx.objectStore(PENDING_STORE).put(value, key);
      });
    });
  }

  function idbGet(key) {
    return openPendingDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(PENDING_STORE, 'readonly');
        var req = tx.objectStore(PENDING_STORE).get(key);
        req.onsuccess = function () { resolve(req.result); };
        req.onerror = function () { reject(req.error); };
      });
    });
  }

  function saveInputFile(form, input) {
    var key = pendingInputKey(form, input);
    var file = input.files && input.files[0];
    if (!file) return idbPut(key, null).catch(function () {});
    return idbPut(key, {
      name: file.name,
      type: file.type,
      lastModified: file.lastModified,
      blob: file,
    }).catch(function () {});
  }

  function saveFormFiles(form) {
    var chain = Promise.resolve();
    Array.prototype.forEach.call(form.querySelectorAll('input[type="file"]'), function (input) {
      chain = chain.then(function () { return saveInputFile(form, input); });
    });
    return chain;
  }

  function clearFormPending(form) {
    var chain = Promise.resolve();
    Array.prototype.forEach.call(form.querySelectorAll('input[type="file"]'), function (input) {
      var key = pendingInputKey(form, input);
      chain = chain.then(function () { return idbPut(key, null); });
    });
    return chain.catch(function () {});
  }

  function assignFileToInput(input, file) {
    if (!file || typeof DataTransfer === 'undefined') return false;
    try {
      var dt = new DataTransfer();
      dt.items.add(file);
      input.files = dt.files;
      return !!(input.files && input.files.length);
    } catch (e) {
      return false;
    }
  }

  function restorePendingFiles() {
    var forms = document.querySelectorAll('form.doc-upload-fresh');
    if (!forms.length) return;
    openPendingDb().then(function () {
      var chain = Promise.resolve();
      Array.prototype.forEach.call(forms, function (form) {
        Array.prototype.forEach.call(form.querySelectorAll('input[type="file"]'), function (input) {
          chain = chain.then(function () {
            return idbGet(pendingInputKey(form, input)).then(function (row) {
              if (!row || !row.blob) return;
              var file = row.blob;
              if (!(file instanceof File)) {
                file = new File([row.blob], row.name || 'archivo', {
                  type: row.type || '',
                  lastModified: row.lastModified || Date.now(),
                });
              }
              if (assignFileToInput(input, file)) {
                updatePickLabel(input);
                markFormReady(form);
              }
            });
          });
        });
      });
      return chain;
    }).catch(function () {});
  }

  function otherReadyForms(exceptForm) {
    return Array.prototype.filter.call(
      document.querySelectorAll('form.doc-upload-fresh'),
      function (f) { return f !== exceptForm && formHasFiles(f); }
    );
  }

  function persistOtherReadyForms(exceptForm) {
    var chain = Promise.resolve();
    otherReadyForms(exceptForm).forEach(function (f) {
      chain = chain.then(function () { return saveFormFiles(f); });
    });
    return chain.catch(function () {});
  }

  function isImageName(name) {
    return /\.(png|jpe?g|webp|gif)$/i.test(name || '');
  }

  function promoteUploadedCard(form) {
    var card = form.closest('.doc-card');
    var previews = document.createElement('div');
    previews.className = 'doc-previews';
    Array.prototype.forEach.call(form.querySelectorAll('input[type="file"]'), function (input) {
      var file = input.files && input.files[0];
      if (!file) return;
      var a = document.createElement('a');
      a.className = 'doc-preview';
      a.href = URL.createObjectURL(file);
      a.target = '_blank';
      a.rel = 'noopener';
      if (isImageName(file.name)) {
        var img = document.createElement('img');
        img.src = a.href;
        img.alt = file.name;
        a.appendChild(img);
      } else {
        var pdf = document.createElement('span');
        pdf.className = 'doc-preview-pdf';
        pdf.innerHTML = '<i class="fas fa-file-pdf"></i>';
        a.appendChild(pdf);
      }
      var cap = document.createElement('span');
      cap.className = 'doc-preview-cap';
      cap.textContent = 'Por validar';
      a.appendChild(cap);
      previews.appendChild(a);
    });

    var prev = form.previousElementSibling;
    if (prev && prev.classList && prev.classList.contains('doc-hint')) prev.remove();
    form.replaceWith(previews);

    if (card) {
      card.classList.remove('is-bad', 'is-optional', 'is-ok', 'is-soon');
      card.classList.add('is-wait');
      var status = card.querySelector('.doc-status');
      if (status) {
        status.className = 'doc-status is-wait';
        status.textContent = 'Por validar';
      }
    }
  }

  document.addEventListener('change', function (ev) {
    var input = ev.target.closest('.doc-upload-fresh input[type="file"]');
    if (!input) return;
    var form = input.closest('form.doc-upload-fresh');
    updatePickLabel(input);
    markFormReady(form);
    if (form) saveInputFile(form, input);
  });

  document.addEventListener('submit', function (ev) {
    var form = ev.target;
    if (!form || !form.classList || !form.classList.contains('doc-upload-fresh')) return;
    ev.preventDefault();
    ev.stopPropagation();

    if (!formHasFiles(form)) {
      swalFire({ icon: 'info', title: 'Elige un archivo', confirmButtonText: 'OK' });
      return;
    }

    form.classList.add('is-uploading');
    var btn = form.querySelector('button[type="submit"]');
    if (btn) btn.disabled = true;

    var keepOthers = otherReadyForms(form).length > 0;

    persistOtherReadyForms(form)
      .then(function () { return clearFormPending(form); })
      .then(function () {
        var fd = new FormData(form);
        return fetch(form.getAttribute('action') || window.location.href, {
          method: 'POST',
          body: fd,
          credentials: 'same-origin',
          headers: { 'X-Requested-With': 'XMLHttpRequest' },
        }).then(function (res) {
          return res.json().then(
            function (data) {
              if (!res.ok || !data || !data.ok) {
                throw new Error((data && data.error) || ('Error HTTP ' + res.status));
              }
            },
            function () {
              throw new Error('Error HTTP ' + res.status);
            }
          );
        });
      })
      .then(function () {
        if (keepOthers) {
          // Solo este documento: los demás archivos elegidos se quedan en sus tarjetas.
          promoteUploadedCard(form);
          return;
        }
        window.location.reload();
      })
      .catch(function (err) {
        form.classList.remove('is-uploading');
        if (btn) btn.disabled = false;
        swalFire({
          icon: 'error',
          title: 'No se pudo subir',
          text: err && err.message ? err.message : 'Error de red',
          confirmButtonText: 'OK',
        });
      });
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', restorePendingFiles);
  } else {
    restorePendingFiles();
  }
})();
