/* maitux.glossary - 勾选行即保存已修改的单元格
 *
 * 背景：本表 zh / en 是**手动保存**（列定义刻意不开 autosave：一改就发请求会
 * 与"按 calc keyword 批量写所有兄弟行"并发，撞出 ZODB ConflictError 500）。
 * core 的 Save 按钮在**表格最底部**，逐行保存时不好找；所以这里加一条更顺手的
 * 路子：**勾选一行 = 保存当前所有未保存的改动**。
 *
 * 为什么不改 core：Save 按钮（ButtonBar.coffee:119）与行勾选框（TableCells.coffee:107）
 * 都是 senaite.app.listing 打包好的 React 组件，服务端没有开关，改它就得改 core 的
 * 编译产物。所以只在**本列表页**注入这段脚本，通过"程序化点击 core 的 Save 按钮"
 * 复用官方保存链路（不自己发请求、不绕过权限与批量规则）。
 *
 * 关键细节：
 *   - 行勾选框：name="uids:list"（select_checkbox_name = "uids" + ":list"），
 *     表头的"全选"同名但在 thead 里，所以用 tbody 过滤掉。
 *   - 保存结束信号：core 保存完成后会清空 ajax_save_queue 并把 Save 按钮隐藏
 *     （listing.coffee:2480-2484），本脚本以"按钮消失"作为解锁信号。
 *   - 有锁：避免连续勾选多行时重复触发保存（那正是会撞 ConflictError 的用法）。
 *   - 没有未保存改动时，Save 按钮根本不存在 -> 勾选不会触发任何请求。
 */
(function () {
  "use strict";

  var SAVE_BUTTON_ID = "ajax_save_selection";
  var ROW_CHECKBOX_SELECTOR = 'input[type="checkbox"][name="uids:list"]';
  var LOCK_TIMEOUT_MS = 15000;
  var POLL_MS = 200;

  var locked = false;

  function getSaveButton() {
    return document.getElementById(SAVE_BUTTON_ID);
  }

  /* 只认"数据行的勾选框"：位于 tbody 内、且 name 是 uids:list */
  function isRowCheckbox(el) {
    if (!el || el.type !== "checkbox") {
      return false;
    }
    if (!el.matches || !el.matches(ROW_CHECKBOX_SELECTOR)) {
      return false;
    }
    if (typeof el.closest !== "function") {
      return false;
    }
    return el.closest("tbody") !== null;
  }

  function saveNow() {
    var button = getSaveButton();
    if (!button || locked) {
      return false;
    }
    locked = true;
    try {
      button.click();
    } catch (err) {
      locked = false;
      return false;
    }
    var deadline = Date.now() + LOCK_TIMEOUT_MS;
    var timer = window.setInterval(function () {
      if (!getSaveButton() || Date.now() > deadline) {
        window.clearInterval(timer);
        locked = false;
      }
    }, POLL_MS);
    return true;
  }

  document.addEventListener("change", function (event) {
    var el = event.target;
    if (!el || !el.checked) {
      return;
    }
    if (!isRowCheckbox(el)) {
      return;
    }
    saveNow();
  }, true);
})();
