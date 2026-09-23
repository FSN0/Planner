/**
 * Selectores de valoración actitud/conocimiento (0–5).
 * Uso: RatingDims.bind({ btnClass, actitudInput, conocimientoInput })
 */
(function (global) {
  function bind(opts) {
    var btnClass = opts.btnClass || 'rating-btn';
    var actitudInput = opts.actitudInput;
    var conocimientoInput = opts.conocimientoInput;
    var state = { actitud: null, conocimiento: null };

    function setDim(dim, score) {
      state[dim] = score;
      var $input = dim === 'actitud' ? $(actitudInput) : $(conocimientoInput);
      $input.val(score === null || score === undefined ? '' : score);
      $('.' + btnClass + '[data-dim="' + dim + '"]').removeClass('active');
      if (score !== null && score !== undefined) {
        $('.' + btnClass + '[data-dim="' + dim + '"][data-score="' + score + '"]').addClass('active');
      }
    }

    $(document).off('click.ratingDims.' + btnClass, '.' + btnClass);
    $(document).on('click.ratingDims.' + btnClass, '.' + btnClass, function () {
      var dim = $(this).data('dim');
      var score = $(this).data('score');
      if (state[dim] === score) {
        setDim(dim, null);
      } else {
        setDim(dim, score);
      }
    });

    return {
      reset: function () {
        setDim('actitud', null);
        setDim('conocimiento', null);
      },
      set: function (actitud, conocimiento) {
        setDim('actitud', actitud === null || actitud === undefined || actitud === '' ? null : Number(actitud));
        setDim('conocimiento', conocimiento === null || conocimiento === undefined || conocimiento === '' ? null : Number(conocimiento));
      },
      get: function () {
        var a = $(actitudInput).val();
        var c = $(conocimientoInput).val();
        return {
          actitud: a === '' ? null : Number(a),
          conocimiento: c === '' ? null : Number(c),
        };
      },
      payload: function () {
        var v = this.get();
        if (v.actitud === null && v.conocimiento === null) return null;
        return v;
      },
    };
  }

  global.RatingDims = { bind: bind };
})(window);
