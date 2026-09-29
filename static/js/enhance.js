// Optional progressive enhancement: copy buttons. Every page works without this file.
document.addEventListener("click", function (event) {
  var button = event.target.closest("[data-copy]");
  if (!button || !navigator.clipboard) return;
  event.preventDefault();
  navigator.clipboard.writeText(button.getAttribute("data-copy")).then(function () {
    var original = button.textContent;
    button.textContent = "Copied";
    setTimeout(function () { button.textContent = original; }, 1500);
  });
});
document.querySelectorAll("[data-copy]").forEach(function (el) { el.hidden = false; });
