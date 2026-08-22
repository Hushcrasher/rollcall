// Dismissable autocomplete panels — spec 2026-08-22-autocomplete-dismiss.
//
// htmx creates and fills every panel on this site; this module only ever
// toggles `hidden` on one. Two selectors describe all five panels (the nav
// suggest box, the credit form's game field, the shared employer field, and
// the three filter typeaheads), so no template needs a hook of its own.
//
// `hidden` is what actually hides a panel: the UA stylesheet's
// `[hidden] { display: none }` is specificity (0,1,0) and `app.css` sets no
// `display` on these two outside `:empty`. Adding one there would silently
// break every dismissal on the site — app.css carries a comment saying so.
//
// Panels are HIDDEN, never emptied: emptying loses the result set, so coming
// back to a field you dismissed would mean retyping.
(function () {
  "use strict";

  var OWNER = ".autocomplete, .nav-search";
  var PANEL = ".results, .nav-suggest";

  // Elements are the only event targets we care about; `document` and text
  // nodes have no closest().
  function panelFor(target) {
    if (!target || !target.closest) return null;
    var owner = target.closest(OWNER);
    return owner ? owner.querySelector(PANEL) : null;
  }

  function hideAllExcept(keep) {
    var panels = document.querySelectorAll(PANEL);
    for (var i = 0; i < panels.length; i++) {
      if (panels[i] !== keep) panels[i].hidden = true;
    }
  }

  // A fresh result set must appear even if the panel was dismissed a keystroke
  // ago, or the field looks broken on the next character typed.
  document.addEventListener("htmx:afterSwap", function (event) {
    var target = event.target;
    var panel = target && target.closest ? target.closest(PANEL) : null;
    panel = panel || panelFor(target);
    if (panel) panel.hidden = false;
  });

  // pointerdown, NOT click: click fires after focus has already moved, and
  // dismissing there would swallow the first press on whatever sits under the
  // panel. Here the panel is gone before the press lands, so the press reaches
  // the field underneath — which is the bug this module exists for.
  document.addEventListener("pointerdown", function (event) {
    hideAllExcept(panelFor(event.target));
  });

  // Escape closes the open panel, and calls preventDefault ONLY when one was
  // open — so a second Escape still reaches the browser's own behaviour on a
  // type=search input (clear the field).
  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    var panel = panelFor(event.target);
    if (panel && !panel.hidden) {
      panel.hidden = true;
      event.preventDefault();
    }
  });

  // Focus entering a field shows what that field last found; focus landing
  // anywhere else closes everything. This is what makes "hide, don't clear"
  // worth doing. A click on an option focuses that option's button, whose
  // owner is the same panel — so the panel survives long enough for the
  // existing per-template click handler to read it.
  document.addEventListener("focusin", function (event) {
    var panel = panelFor(event.target);
    if (panel && panel.innerHTML.trim() !== "") panel.hidden = false;
    hideAllExcept(panel);
  });
})();
