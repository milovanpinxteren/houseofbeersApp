/* Poll a running campaign preview and reload when it finishes, mirroring the
   analytics dashboard's build-in-background + auto-refresh pattern. */
(function () {
  'use strict';

  var panel = document.getElementById('preview-panel');
  if (!panel || !panel.dataset.running) return;

  var statusUrl = panel.dataset.statusUrl;
  var previewId = panel.dataset.previewId;
  var attempts = 0;

  function poll() {
    attempts += 1;
    if (attempts > 150) return; // ~5 minutes, then give up quietly
    fetch(statusUrl + '?preview_id=' + encodeURIComponent(previewId), {
      credentials: 'same-origin',
    })
      .then(function (response) { return response.json(); })
      .then(function (data) {
        if (data.status === 'done' || data.status === 'failed') {
          window.location.reload();
        } else {
          setTimeout(poll, 2000);
        }
      })
      .catch(function () { setTimeout(poll, 4000); });
  }

  setTimeout(poll, 2000);
})();
