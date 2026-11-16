(function () {
  var DUR = 6500, root = document.documentElement;
  var win = document.getElementById('win'), steps = [].slice.call(document.querySelectorAll('.steps button'));
  var scenes = [].slice.call(win.querySelectorAll('.scene')), side = [].slice.call(win.querySelectorAll('.win-side li'));
  var status = document.getElementById('w-status'), search = document.getElementById('w-search'), cnt = document.getElementById('cnt');
  var pauseBtn = document.getElementById('pause'), demo = document.getElementById('demo');
  var reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  var STATE = [['work', 'Lendo loja…', 'Buscar produto ou loja'], ['', 'Parado', 'suporte parede'], ['work', 'Fatiando…', 'Buscar produto ou loja'], ['work', 'Renderizando…', 'Buscar produto ou loja'], ['ok', 'Pronto', 'Buscar produto ou loja']];
  var cur = 0, timer, raf, paused = false, visible = false;
  demo.style.setProperty('--dur', DUR + 'ms');

  function counter() {
    cancelAnimationFrame(raf); var t0 = performance.now(), from = 2700, span = 2600;
    cnt.textContent = '0';
    (function f(t) {
      var k = Math.min(1, Math.max(0, (t - t0 - from) / span)); cnt.textContent = Math.round(k * 63);
      if (k < 1) raf = requestAnimationFrame(f);
    })(t0);
  }
  function go(i) {
    cur = (i + scenes.length) % scenes.length;
    // tira tudo, força o reflow e põe de volta: as animações CSS da cena e da ficha recomeçam do zero
    scenes.forEach(function (s) { s.classList.remove('on'); });
    steps.forEach(function (b) { b.setAttribute('aria-selected', 'false'); });
    void win.offsetWidth;
    scenes[cur].classList.add('on'); steps[cur].setAttribute('aria-selected', 'true');
    side.forEach(function (s, n) { s.classList.toggle('on', n === cur); });
    status.className = 'win-status ' + STATE[cur][0]; status.lastChild.textContent = STATE[cur][1]; search.textContent = STATE[cur][2];
    if (cur === 0) counter(); else cnt.textContent = '63';
    clearTimeout(timer);
    if (!paused && !reduced && visible) timer = setTimeout(function () { go(cur + 1); }, DUR);
  }
  steps.forEach(function (b) { b.addEventListener('click', function () { go(+b.dataset.go); }); });
  pauseBtn.addEventListener('click', function () {
    paused = !paused; demo.classList.toggle('paused', paused);
    pauseBtn.setAttribute('aria-pressed', paused); pauseBtn.textContent = paused ? 'Retomar a demonstração' : 'Pausar a demonstração';
    if (paused) clearTimeout(timer); else go(cur);
  });

  if (reduced) { root.classList.add('reduced'); pauseBtn.hidden = true; go(1); cnt.textContent = '63'; }
  else go(0);

  // a demo só roda enquanto está na tela
  if ('IntersectionObserver' in window) {
    new IntersectionObserver(function (e) { var v = e[0].isIntersecting; if (v !== visible) { visible = v; if (v) go(cur); else clearTimeout(timer); } }, { threshold: .35 }).observe(win);
    var io = new IntersectionObserver(function (es) { es.forEach(function (x) { if (x.isIntersecting) { x.target.classList.add('in'); io.unobserve(x.target); } }); }, { threshold: .15 });
    [].forEach.call(document.querySelectorAll('.rise'), function (n) { io.observe(n); });
  } else { visible = true; [].forEach.call(document.querySelectorAll('.rise'), function (n) { n.classList.add('in'); }); go(cur); }
})();
