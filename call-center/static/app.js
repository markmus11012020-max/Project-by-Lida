/* CallPilot demo interactions: audio player, review form, reject dialog. */
(function () {
  "use strict";

  function toast(message, isError) {
    var el = document.getElementById("toast");
    if (!el) return;
    el.textContent = message;
    el.classList.toggle("error", Boolean(isError));
    el.classList.add("show");
    window.clearTimeout(el._timer);
    el._timer = window.setTimeout(function () {
      el.classList.remove("show");
    }, 4200);
  }

  function formatTime(seconds) {
    var total = Math.max(0, Math.floor(Number(seconds) || 0));
    var minutes = Math.floor(total / 60);
    var rest = total % 60;
    return minutes + ":" + String(rest).padStart(2, "0");
  }

  /* Audio player + transcript sync */
  var audio = document.getElementById("call-audio");
  if (audio) {
    var toggle = document.getElementById("audio-toggle");
    var progress = document.getElementById("audio-progress");
    var timeLabel = document.getElementById("audio-time");
    var segmentsEl = document.getElementById("segments-data");
    var segments = [];
    try {
      segments = JSON.parse((segmentsEl && segmentsEl.textContent) || "[]");
    } catch (error) {
      segments = [];
    }
    var segmentEls = Array.prototype.slice.call(
      document.querySelectorAll(".segment[data-segment]")
    );

    function syncPlayer() {
      var duration = audio.duration || 0;
      var current = audio.currentTime || 0;
      if (progress) {
        progress.max = duration || 0;
        progress.value = current;
      }
      if (timeLabel) {
        timeLabel.textContent = formatTime(current) + " / " + formatTime(duration);
      }
      var active = null;
      var currentMs = current * 1000;
      segments.forEach(function (segment) {
        if (currentMs >= segment.start_ms && currentMs < segment.end_ms) {
          active = segment;
        }
      });
      segmentEls.forEach(function (el) {
        el.classList.toggle(
          "active",
          Boolean(active) && el.dataset.segment === active.id
        );
      });
    }

    audio.addEventListener("loadedmetadata", syncPlayer);
    audio.addEventListener("timeupdate", syncPlayer);
    audio.addEventListener("play", function () {
      if (toggle) toggle.textContent = "❚❚";
    });
    audio.addEventListener("pause", function () {
      if (toggle) toggle.textContent = "▶";
    });
    audio.addEventListener("ended", function () {
      if (toggle) toggle.textContent = "▶";
    });

    if (toggle) {
      toggle.addEventListener("click", function () {
        if (audio.paused) {
          audio.play();
        } else {
          audio.pause();
        }
      });
    }
    if (progress) {
      progress.addEventListener("input", function () {
        audio.currentTime = Number(progress.value) || 0;
        syncPlayer();
      });
    }

    segmentEls.forEach(function (el) {
      el.addEventListener("click", function () {
        var start = Number(el.dataset.start || 0);
        audio.currentTime = start / 1000;
        audio.play();
      });
    });

    document.querySelectorAll("[data-seek]").forEach(function (button) {
      button.addEventListener("click", function () {
        var id = button.dataset.seek;
        var segment = segments.find(function (item) {
          return item.id === id;
        });
        if (!segment) return;
        audio.currentTime = segment.start_ms / 1000;
        audio.play();
        var target = document.querySelector(
          '.segment[data-segment="' + id + '"]'
        );
        if (target) {
          target.scrollIntoView({ behavior: "smooth", block: "center" });
        }
      });
    });
  }

  /* Review form */
  var config = window.CALLPILOT || {};
  var draftEl = document.getElementById("draft-data");
  if (!draftEl || !config.callId || config.readOnly) return;

  var draft;
  try {
    draft = JSON.parse(draftEl.textContent || "{}");
  } catch (error) {
    return;
  }

  function setPath(target, path, value) {
    var parts = path.split(".");
    var current = target;
    for (var i = 0; i < parts.length - 1; i += 1) {
      if (!current[parts[i]] || typeof current[parts[i]] !== "object") {
        current[parts[i]] = {};
      }
      current = current[parts[i]];
    }
    current[parts[parts.length - 1]] = value;
  }

  function collectResult() {
    var result = JSON.parse(JSON.stringify(draft || {}));
    document.querySelectorAll("[data-path]").forEach(function (input) {
      setPath(result, input.dataset.path, input.value);
    });
    document.querySelectorAll(".qa-row[data-finding-index]").forEach(function (row) {
      var index = Number(row.dataset.findingIndex);
      if (!Array.isArray(result.qa_findings) || !result.qa_findings[index]) return;
      var status = row.querySelector('[data-finding-field="status"]');
      var comment = row.querySelector('[data-finding-field="comment"]');
      if (status) result.qa_findings[index].status = status.value;
      if (comment) result.qa_findings[index].comment = comment.value;
    });
    return result;
  }

  var confirmBtn = document.getElementById("confirm-btn");
  if (confirmBtn) {
    confirmBtn.addEventListener("click", function () {
      confirmBtn.disabled = true;
      var original = confirmBtn.textContent;
      confirmBtn.textContent = "Отправляю...";
      fetch("/calls/" + encodeURIComponent(config.callId) + "/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          final_result: collectResult(),
          reviewer: (document.getElementById("reviewer") || {}).value || "Менеджер",
          reason: (document.getElementById("review-reason") || {}).value || ""
        })
      })
        .then(function (response) {
          return response.json().then(function (data) {
            if (!response.ok) {
              throw new Error(data.detail || "Не удалось подтвердить карточку");
            }
            return data;
          });
        })
        .then(function (data) {
          window.location.href = data.redirect;
        })
        .catch(function (error) {
          toast(error.message, true);
          confirmBtn.disabled = false;
          confirmBtn.textContent = original;
        });
    });
  }

  var rejectBtn = document.getElementById("reject-btn");
  var rejectDialog = document.getElementById("reject-dialog");
  var rejectSubmit = document.getElementById("reject-submit");
  if (rejectBtn && rejectDialog) {
    rejectBtn.addEventListener("click", function () {
      rejectDialog.showModal();
    });
  }
  if (rejectSubmit && rejectDialog) {
    rejectSubmit.addEventListener("click", function () {
      var reasonEl = document.getElementById("reject-reason");
      var reason = reasonEl ? reasonEl.value.trim() : "";
      if (!reason) {
        toast("Укажите причину отклонения", true);
        return;
      }
      rejectSubmit.disabled = true;
      fetch("/calls/" + encodeURIComponent(config.callId) + "/reject", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          reviewer: (document.getElementById("reviewer") || {}).value || "Менеджер",
          reason: reason
        })
      })
        .then(function (response) {
          return response.json().then(function (data) {
            if (!response.ok) {
              throw new Error(data.detail || "Не удалось отклонить звонок");
            }
            return data;
          });
        })
        .then(function (data) {
          rejectDialog.close();
          window.location.href = data.redirect;
        })
        .catch(function (error) {
          toast(error.message, true);
          rejectSubmit.disabled = false;
        });
    });
  }
})();
