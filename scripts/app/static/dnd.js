// Arrastar para reordenar. Cada região é (container, seletor dos itens, escopo); a ordem fica em localStorage e vale após cada redesenho.
// O item só vira arrastável enquanto o mouse está na alça (.grip), para não atrapalhar links, campos e seleção de texto.
const DND = {
  dragging: false, src: null,
  load(scope) { try { return JSON.parse(localStorage['order:' + scope] || '[]'); } catch (e) { return []; } },
  save(scope, keys) { try { localStorage['order:' + scope] = JSON.stringify(keys); } catch (e) {} },
  keyOf: el => el.dataset.key,

  /** Põe os itens na ordem salva (os que não estão na lista ficam no fim, na ordem atual) e garante a alça. */
  apply(container, sel, scope) {
    if (!container) return;
    const items = [...container.querySelectorAll(':scope > ' + sel)];
    const saved = DND.load(scope), pos = k => { const i = saved.indexOf(k); return i < 0 ? 1e9 : i; };
    items.forEach(el => {
      if (!el.querySelector(':scope > .grip')) {
        const g = document.createElement('span'); g.className = 'grip'; g.title = 'Arraste para mover'; g.setAttribute('aria-hidden', 'true');
        g.innerHTML = '<svg class="ic"><use href="#i-grip"/></svg>'; el.prepend(g);
      }
    });
    if (saved.length) {
      const want = [...items].sort((a, b) => pos(DND.keyOf(a)) - pos(DND.keyOf(b)));
      if (want.some((el, i) => el !== items[i])) want.forEach(el => container.appendChild(el));  // só mexe se a ordem mudou: mover nó com foco derruba o cursor
    }
    DND.bind(container, sel, scope);
  },

  bind(container, sel, scope, onDrop) {
    if (container._dnd) { container._dnd.scope = scope; container._dnd.onDrop = onDrop || container._dnd.onDrop; return; }
    container._dnd = {scope, onDrop};
    // o item é o filho direto do container que contém o alvo: cartões aninhados (loja dentro do cartão da tela) não se confundem
    const item = e => { let n = e.target; while (n && n.parentNode !== container) n = n.parentNode; return n && n.matches && n.matches(sel) ? n : null; };
    container.addEventListener('mousedown', e => { const g = e.target.closest('.grip'); const it = g && g.parentNode; if (it && it.parentNode === container && it.matches(sel)) it.draggable = true; });
    container.addEventListener('mouseup', () => container.querySelectorAll('[draggable=true]').forEach(x => x.draggable = false));
    container.addEventListener('dragstart', e => {
      const it = item(e); if (!it || !it.draggable || e.target !== it) return;
      DND.dragging = true; DND.src = it; it.classList.add('dragging'); e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', DND.keyOf(it) || '');
    });
    container.addEventListener('dragover', e => {
      if (!DND.src || DND.src.parentNode !== container) return;
      const it = item(e); if (!it || it === DND.src || it.parentNode !== container) return;
      e.preventDefault();
      const r = it.getBoundingClientRect(), grid = getComputedStyle(container).display === 'grid';
      const before = grid ? e.clientX < r.left + r.width / 2 : e.clientY < r.top + r.height / 2;
      container.insertBefore(DND.src, before ? it : it.nextSibling);
    });
    container.addEventListener('drop', e => e.preventDefault());
    container.addEventListener('dragend', () => {
      const src = DND.src; DND.dragging = false; DND.src = null;
      if (!src) return;
      src.classList.remove('dragging'); src.draggable = false;
      const keys = [...container.querySelectorAll(':scope > ' + sel)].map(DND.keyOf).filter(Boolean);
      const st = container._dnd;
      if (st.onDrop) st.onDrop(keys); else { const old = DND.load(st.scope).filter(k => !keys.includes(k)); DND.save(st.scope, keys.concat(old)); }
    });
  },
};
