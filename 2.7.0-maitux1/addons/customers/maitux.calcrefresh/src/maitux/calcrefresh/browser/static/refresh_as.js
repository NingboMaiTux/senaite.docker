/* Per-AS calculation refresh button, injected into the AS-Grouped
 * manage_results table by maitux.calcrefresh.
 *
 * The toolbar "Refresh Cal" action points at @@refresh_calculation with no
 * keyword, which refreshes EVERY analysis on the worksheet and can peg the
 * instance CPU at 100%.  That action is now intercepted here (never navigated
 * to): single-AS refresh is only offered through a per-AS "Refresh Cal" button
 * injected into each as-group-header below, pointing at
 * @@refresh_calculation?keyword=<that AS>, so a refresh only ever touches one
 * Analysis Service.
 *
 * The per-AS buttons only exist in the AS-Grouped layout (the .as-group-panel
 * markup is rendered by maitux.worksheet).  In the classic layout the toolbar
 * click is instead turned into a prompt to switch layouts; the server-side
 * empty-keyword 400 (see RefreshCalculationView) stays as the backstop.
 */
(function () {
  "use strict";

  function init() {
    var panels = document.querySelectorAll(".as-group-panel");

    // 工具栏「Refresh Cal」不带 keyword，服务端已 400 拦下整表刷新。
    // 单 AS 刷新只走 AS-Grouped 布局里各 AS 标题栏注入的按钮，所以这里
    // 把工具栏按钮点击拦截掉，改成引导用户切布局 / 用标题栏按钮。
    var toolBtn = document.querySelector('a[href*="refresh_calculation"]');
    if (toolBtn) {
      toolBtn.addEventListener("click", function (event) {
        event.preventDefault();
        if (panels.length) {
          window.alert("请点击各分析项标题栏上的 Refresh Cal 按钮，逐个 AS 刷新。");
        } else {
          window.alert("单 AS 刷新只在 AS-Grouped 布局可用。请通过页面的 Layout 下拉框切换到 AS-Grouped 布局，然后点击各分析项标题栏的 Refresh Cal 按钮。");
        }
      });
    }

    if (!panels.length) {
      return;
    }

    // The toolbar action already carries the correct view URL; reuse it as the
    // URL template instead of reconstructing the VHM path by hand.
    var toolHref = toolBtn ? toolBtn.getAttribute("href") : "";

    Array.prototype.forEach.call(panels, function (panel) {
      var header = panel.querySelector(".as-group-header");
      var kwSpan = panel.querySelector(".as-group-keyword");
      if (!header || !kwSpan) {
        return;
      }

      var keyword = kwSpan.textContent.replace(/^\s+|\s+$/g, "");
      if (!keyword) {
        return;
      }

      // Idempotent: the script may run more than once (e.g. after a partial
      // DOM refresh), so never inject a second button into the same header.
      if (header.querySelector(".calcrefresh-refresh")) {
        return;
      }

      var btn = document.createElement("a");
      btn.className = "calcrefresh-refresh";
      btn.textContent = "Refresh Cal";
      btn.title = "Refresh calculation snapshot for AS " + keyword;

      if (toolHref) {
        var sep = toolHref.indexOf("?") === -1 ? "?" : "&";
        btn.href = toolHref + sep + "keyword=" + encodeURIComponent(keyword);
      }

      // AJAX so the analyst stays on manage_results and sees the refreshed
      // numbers after a reload, instead of navigating to a raw JSON page.
      btn.addEventListener("click", function (event) {
        event.preventDefault();
        if (!btn.href) {
          return;
        }
        btn.textContent = "Refreshing...";
        var xhr = new XMLHttpRequest();
        xhr.open("GET", btn.href, true);
        xhr.onload = function () {
          if (xhr.status === 200) {
            window.location.reload();
          } else {
            btn.textContent = "Refresh failed";
            window.alert("Refresh failed (HTTP " + xhr.status + ").");
          }
        };
        xhr.onerror = function () {
          btn.textContent = "Refresh failed";
          window.alert("Refresh request failed.");
        };
        xhr.send();
      });

      header.appendChild(btn);
    });
  }

  // The viewlet injects this script into <head>, so it runs before the body
  // (and the toolbar / as-group panels) is parsed.  Wait for the DOM.
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
