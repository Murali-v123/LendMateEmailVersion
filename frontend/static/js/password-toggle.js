/*
 * Adds a show/hide (eye) button to every password input on the page.
 * Runs once per input; safe to load on every page.
 */
(function () {
  var EYE_OPEN =
    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
    '<path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>' +
    '<circle cx="12" cy="12" r="3.2" stroke="currentColor" stroke-width="1.8"/></svg>';
  var EYE_OFF =
    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
    '<path d="M3 3l18 18" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>' +
    '<path d="M10.6 6.1A10.8 10.8 0 0 1 12 6c7 0 11 6 11 6a18 18 0 0 1-3.2 3.9M6.6 6.6A18 18 0 0 0 1 12s4 6 11 6a10.7 10.7 0 0 0 5.4-1.5" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>' +
    '<path d="M9.9 9.9a3.2 3.2 0 0 0 4.2 4.2" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';

  function addToggle(input) {
    if (input.dataset.pwToggle === "done") return;
    input.dataset.pwToggle = "done";

    var wrap = document.createElement("div");
    wrap.className = "lm-pw-wrap";
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);
    input.classList.add("lm-pw-input");

    var button = document.createElement("button");
    button.type = "button";
    button.className = "lm-pw-toggle";
    button.setAttribute("aria-label", "Show password");
    button.setAttribute("aria-pressed", "false");
    button.innerHTML = EYE_OPEN;

    button.addEventListener("click", function () {
      var showing = input.type === "text";
      input.type = showing ? "password" : "text";
      button.innerHTML = showing ? EYE_OPEN : EYE_OFF;
      button.setAttribute("aria-label", showing ? "Show password" : "Hide password");
      button.setAttribute("aria-pressed", showing ? "false" : "true");
    });

    wrap.appendChild(button);
  }

  function init() {
    document.querySelectorAll('input[type="password"]').forEach(addToggle);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
