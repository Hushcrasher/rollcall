// Dismissable autocomplete panels — spec 2026-08-22-autocomplete-dismiss.
//
// htmx creates and fills every panel on this site; this module only ever
// toggles `hidden` on one. Two selectors describe all six panels (the nav
// suggest box, the credit form's game field, the shared employer field, and
// the three filter typeaheads) across their four call-site templates, so no
// template needs a hook of its own.
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

  // A swap shows the panel when it delivered something and hides it when it
  // delivered nothing. This keeps `hidden` agreeing with the other two handlers
  // and does not depend on CSS :empty, whose whitespace blind spot would leave
  // an invisible 2px sliver. Only while focus is still inside the owner, though:
  // between the debounce and the round trip the user can press elsewhere, and a
  // late response must not pop the panel back open over whatever they moved to.
  document.addEventListener("htmx:afterSwap", function (event) {
    var target = event.target;
    var panel = target && target.closest ? target.closest(PANEL) : null;
    panel = panel || panelFor(target);
    if (!panel) return;
    var owner = panel.closest(OWNER);
    if (owner && owner.contains(document.activeElement)) panel.hidden = panel.innerHTML.trim() === "";
  });

  // pointerdown, NOT click — but not for the usual "click would swallow the
  // first press" reason, which does not apply here: hit-testing resolves the
  // event target before any handler runs, so a press on the covered region IS
  // a press on the panel whatever we do, and a press outside the owner never
  // targeted the panel in the first place. (That folklore belongs to blur-based
  // dismissers; this module dismisses on owner-scoped focusin, not on blur.)
  // The three real reasons: closing at press time is what native menus and
  // selects do, where a click dismisser visibly lags to mouseup; a touch scroll
  // started outside the panel fires pointerdown but never click, so on mobile
  // the panel goes away as the page moves instead of riding along (there is no
  // scroll listener); and a text-selection drag from inside the input released
  // outside the owner fires click on a common ancestor outside it, which a
  // click dismisser would read as "outside" and close the panel of the very
  // field being selected in — pointerdown, still inside the owner, keeps it.
  document.addEventListener("pointerdown", function (event) {
    hideAllExcept(panelFor(event.target));
  });

  // Escape closes the open panel, and calls preventDefault ONLY when one was
  // open — so a second Escape still reaches the browser's own behaviour on a
  // type=search input (clear the field). `!hidden` alone does not mean open:
  // a panel that has never been filled, or that an option-pick emptied, is
  // `hidden === false` and invisible through `.results:empty { display: none }`.
  // Without the emptiness test the first Escape in the nav box — pasted text,
  // or anything inside the 250ms debounce — would silently eat the clear.
  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    var panel = panelFor(event.target);
    if (panel && !panel.hidden && panel.innerHTML.trim() !== "") {
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
