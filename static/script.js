// Nav scroll
const nav = document.getElementById('nav');
window.addEventListener('scroll', () => {
  nav.classList.toggle('scrolled', window.scrollY > 40);
}, { passive: true });

// Burger
const burger = document.getElementById('burger');
const navLinks = document.getElementById('navLinks');
if (burger && navLinks) {
  burger.addEventListener('click', () => {
    navLinks.classList.toggle('open');
    const spans = burger.querySelectorAll('span');
    if (navLinks.classList.contains('open')) {
      spans[0].style.transform = 'rotate(45deg) translate(5px,5px)';
      spans[1].style.opacity = '0';
      spans[2].style.transform = 'rotate(-45deg) translate(5px,-5px)';
    } else {
      spans.forEach(s => { s.style.transform = ''; s.style.opacity = ''; });
    }
  });
  navLinks.querySelectorAll('a').forEach(a => {
    a.addEventListener('click', () => {
      navLinks.classList.remove('open');
      burger.querySelectorAll('span').forEach(s => { s.style.transform = ''; s.style.opacity = ''; });
    });
  });
}

// Cookie consent
(function () {
  if (localStorage.getItem('cookie_ok')) return;
  const _cl = localStorage.getItem('lang') || 'ru';
  const _ct = {
    ru: { text: 'Мы используем файлы cookie для улучшения сайта и аналитики.', privacy: 'Политика конфиденциальности', accept: 'Принять', decline: 'Отклонить' },
    en: { text: 'We use cookies to improve the site and for analytics.', privacy: 'Privacy Policy', accept: 'Accept', decline: 'Decline' },
    cs: { text: 'Používáme soubory cookie pro zlepšení webu a analytiku.', privacy: 'Ochrana osobních údajů', accept: 'Přijmout', decline: 'Odmítnout' },
  };
  const ct = _ct[_cl] || _ct.ru;
  const bar = document.createElement('div');
  bar.id = 'cookie-bar';
  bar.innerHTML =
    '<span>' + ct.text + ' <a href="/privacy">' + ct.privacy + '</a></span>' +
    '<div class="cookie-actions">' +
    '<button id="cookie-accept" class="cookie-btn cookie-btn-ok">' + ct.accept + '</button>' +
    '<button id="cookie-decline" class="cookie-btn">' + ct.decline + '</button>' +
    '</div>';
  document.body.appendChild(bar);
  setTimeout(() => bar.classList.add('visible'), 300);
  document.getElementById('cookie-accept').addEventListener('click', function () {
    localStorage.setItem('cookie_ok', '1');
    bar.classList.remove('visible');
    setTimeout(() => bar.remove(), 400);
  });
  document.getElementById('cookie-decline').addEventListener('click', function () {
    localStorage.setItem('cookie_ok', '0');
    bar.classList.remove('visible');
    setTimeout(() => bar.remove(), 400);
  });
})();

// Fade-up on scroll
const observer = new IntersectionObserver(entries => {
  entries.forEach(e => {
    if (e.isIntersecting) { e.target.classList.add('visible'); observer.unobserve(e.target); }
  });
}, { threshold: 0.1 });
document.querySelectorAll('.fade-up').forEach((el, i) => {
  el.style.transitionDelay = (i % 4) * 80 + 'ms';
  observer.observe(el);
});
