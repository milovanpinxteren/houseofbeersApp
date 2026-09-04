/* Puntentool front-end: member search (index page) and the live euro<->points
   helper (member page). Both are progressive enhancements — with JS off the
   search box does nothing but the form still works, because the server only
   ever reads the points/saldo fields, never the euro helper. */
(function () {
  'use strict';

  // ---------- Index: member search ----------
  var searchPanel = document.getElementById('search-panel');
  if (searchPanel) {
    var searchUrl = searchPanel.dataset.userSearchUrl;
    var memberUrlTemplate = searchPanel.dataset.memberUrl;
    var input = document.getElementById('id_member_search');
    var results = document.getElementById('member-search-results');
    var status = document.getElementById('member-search-status');
    var timer = null;

    input.addEventListener('input', function () {
      var query = input.value.trim();
      clearTimeout(timer);
      if (query.length < 2) {
        results.hidden = true;
        status.hidden = true;
        return;
      }
      timer = setTimeout(function () {
        status.textContent = 'Zoeken…';
        status.hidden = false;
        fetch(searchUrl + '?q=' + encodeURIComponent(query), {
          credentials: 'same-origin',
        })
          .then(function (response) { return response.json(); })
          .then(function (data) {
            var users = data.users || [];
            results.innerHTML = '';
            if (!users.length) {
              status.textContent = 'Geen klanten gevonden.';
              status.hidden = false;
              results.hidden = true;
              return;
            }
            status.hidden = true;
            users.forEach(function (user) {
              var item = document.createElement('a');
              item.className = 'result';
              item.href = memberUrlTemplate.replace(/\/0\/$/, '/' + user.id + '/');
              var title = document.createElement('div');
              title.className = 'r-title';
              title.textContent = user.email;
              item.appendChild(title);
              if (user.name) {
                var meta = document.createElement('div');
                meta.className = 'r-meta';
                meta.textContent = user.name;
                item.appendChild(meta);
              }
              results.appendChild(item);
            });
            results.hidden = false;
          })
          .catch(function () {
            status.textContent = 'Zoeken mislukt.';
            status.hidden = false;
          });
      }, 300);
    });
  }

  // ---------- Member page: mode switch + euro helper ----------
  var form = document.getElementById('points-form');
  if (!form) return;

  var rate = parseFloat(form.dataset.rate) || 0.05;
  var warnPoints = parseInt(form.dataset.warnPoints, 10) || 2000;
  var currentBalance = parseInt(form.dataset.balance, 10) || 0;

  var modeSelect = document.getElementById('id_mode');
  var modeHint = document.getElementById('mode-hint');
  var reasonHint = document.getElementById('reason-hint');
  var notify = document.getElementById('id_notify');
  var pointsInput = document.getElementById('id_points');
  var euroInput = document.getElementById('id_euro');
  var targetInput = document.getElementById('id_target_balance');
  var conversion = document.getElementById('conversion-line');
  var setConversion = document.getElementById('set-conversion-line');

  function formatEuro(value) {
    return '€' + value.toFixed(2).replace('.', ',');
  }

  function updateMode(userChanged) {
    var mode = modeSelect.value;
    Array.prototype.forEach.call(
      form.querySelectorAll('[data-mode]'),
      function (block) { block.hidden = block.dataset.mode !== mode; }
    );
    if (mode === 'add') {
      modeHint.textContent =
        'Het lid krijgt punten erbij en ziet de reden terug in zijn puntengeschiedenis.';
      reasonHint.textContent = 'Dit ziet het lid in de app — schrijf het zo op.';
      // Default ON for a reward, OFF for a correction — but only when staff
      // just switched mode, so a re-rendered form keeps their own choice.
      if (userChanged) notify.checked = true;
    } else {
      modeHint.textContent =
        'Corrigeert het saldo naar een exact aantal. Het verschil wordt als correctie geboekt, niet als verdiende punten.';
      reasonHint.textContent = 'Voor het logboek — houd het kort en feitelijk.';
      if (userChanged) notify.checked = false;
    }
    updateConversion();
  }

  function updateConversion() {
    if (modeSelect.value === 'add') {
      var points = parseInt(pointsInput.value, 10);
      if (isNaN(points) || points <= 0) {
        conversion.textContent = '';
        conversion.className = 'conversion';
        return;
      }
      conversion.textContent =
        points + ' punten ≈ ' + formatEuro(points * rate) +
        ' · saldo wordt ' + (currentBalance + points);
      conversion.className = points >= warnPoints ? 'conversion warn' : 'conversion';
    } else {
      var target = parseInt(targetInput.value, 10);
      if (isNaN(target) || target < 0) {
        setConversion.textContent = '';
        setConversion.className = 'conversion';
        return;
      }
      var delta = target - currentBalance;
      setConversion.textContent =
        'Verschil: ' + (delta > 0 ? '+' : '') + delta + ' punten ≈ ' +
        formatEuro(Math.abs(delta) * rate);
      setConversion.className =
        Math.abs(delta) >= warnPoints ? 'conversion warn' : 'conversion';
    }
  }

  // Euro -> points, the direction the shop asked for explicitly ("€10 is
  // hoeveel punten?"). The points field stays authoritative; this only fills it.
  euroInput.addEventListener('input', function () {
    var euros = parseFloat(euroInput.value.replace(',', '.'));
    if (isNaN(euros) || euros < 0 || rate <= 0) return;
    pointsInput.value = Math.round(euros / rate);
    updateConversion();
  });

  pointsInput.addEventListener('input', function () {
    var points = parseInt(pointsInput.value, 10);
    euroInput.value = isNaN(points) ? '' : (points * rate).toFixed(2);
    updateConversion();
  });

  targetInput.addEventListener('input', updateConversion);
  modeSelect.addEventListener('change', function () { updateMode(true); });

  updateMode(false);
})();
