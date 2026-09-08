// Shared dark-mode toggle for index.html + kb.html (same element IDs on both).
(function () {
  var toggle = document.getElementById('theme-toggle');
  var moon = document.getElementById('icon-moon');
  var sun = document.getElementById('icon-sun');
  if (!toggle || !moon || !sun) return;
  function sync() {
    var dark = document.documentElement.getAttribute('data-theme') === 'dark';
    moon.hidden = dark;
    sun.hidden = !dark;
    var label = dark ? 'Switch to light mode' : 'Switch to dark mode';
    toggle.setAttribute('aria-label', label);
    toggle.title = label;
  }
  toggle.addEventListener('click', function () {
    var next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    try { localStorage.setItem('theme', next); } catch (e) {}
    sync();
  });
  sync();
})();
