// Language toggle for the privacy and support pages. The <head> script picks the
// first language (?lang=, #zh/#en, a saved choice, then the browser's language).
(function () {
  var d = document.documentElement, buttons = document.querySelectorAll(".lang button");
  function set(l) {
    d.classList.remove("en", "zh"); d.classList.add(l); d.lang = l == "zh" ? "zh-Hans" : "en";
    buttons.forEach(function (b) { b.setAttribute("aria-pressed", b.dataset.set == l ? "true" : "false"); });
    try { localStorage.setItem("arslan-lang", l); } catch (e) {}
  }
  buttons.forEach(function (b) { b.addEventListener("click", function () { set(b.dataset.set); }); });
  set(d.classList.contains("zh") ? "zh" : "en");
})();
