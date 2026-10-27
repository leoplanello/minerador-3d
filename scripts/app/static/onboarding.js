// Assistente da primeira abertura e tour guiado por tela. Usa $, esc, post, toast, load, addStores e ic do app.js só quando roda.
const Onboarding = {
  state: {done: null, step: 0, tours: {}}, step: 0, health: null, tools: [], poll: 0,  // done null = ainda não carregou do servidor

  async init() {
    try { this.state = await (await fetch('/api/onboarding')).json(); } catch (e) { return; }
    if (!this.state.done) this.open(this.state.step || 0);
    else Tour.maybe(route.view);  // o primeiro desenho da tela veio antes de saber se o assistente já foi feito
  },

  save(patch) { Object.assign(this.state, patch); return post('/api/onboarding', patch); },

  async open(step = 0) {
    this.step = step;
    try { this.health = await (await fetch('/api/health')).json(); this.tools = await (await fetch('/api/tools')).json(); } catch (e) { this.health = {}; }
    let back = document.getElementById('ob');
    if (!back) { back = document.createElement('div'); back.id = 'ob'; back.className = 'ob-back'; back.setAttribute('role', 'dialog'); back.setAttribute('aria-modal', 'true'); document.body.appendChild(back); }
    back.hidden = false;
    this.draw();
  },

  close(done) {
    const b = document.getElementById('ob'); if (b) b.hidden = true;
    this.save({done: !!done, step: this.step});
  },

  steps() {
    const h = this.health || {}, ok = v => v ? '<span class="yes">✓ pronto</span>' : '<span class="no">✗ falta</span>';
    const row = (label, v, how) => `<div class="obrow"><span class="grow"><b>${label}</b><div class="small mut">${how}</div></span>${ok(v)}</div>`;
    return [
      {t: 'Bem-vindo ao Minerador 3D', body: () => `<p>Este app acha produtos que vendem bem no Mercado Livre e leva cada um até o anúncio: modelo 3D, fatiamento, custo, texto, imagens, vídeo e publicação.</p>
        <ol class="flow"><li>Você cola lojas e o app lê os mais vendidos.</li><li>Você aprova os produtos que quer vender.</li><li>O app cuida das etapas e você confirma o que vai ao ar.</li></ol>
        <p class="small mut">Este assistente leva uns 5 minutos e pode ser refeito depois em Ajuda. Nada é publicado sem o seu clique.</p>`},
      {t: 'Ferramentas do computador', body: () => `<p>O app usa estes programas. Os que faltam podem ser baixados aqui, direto do site oficial, com conferência de integridade.</p>
        ${(this.tools || []).map(t => { const j = t.job || {}, run = j.status === 'running', pct = j.total ? Math.round(j.done / j.total * 100) : 0;
          return `<div class="obrow"><span class="grow"><b>${esc(t.label)}</b><div class="small mut">${{bambustudio: 'Fatia o modelo e calcula tempo e filamento.', blender: 'Gera as imagens do anúncio.', ffmpeg: 'Monta o vídeo.'}[t.name] || ''} Download de cerca de ${t.size_mb} MB.</div>
            ${run ? `<div class="bar"><i style="width:${pct}%"></i></div><div class="small mut">${j.stage === 'baixando' ? 'Baixando… ' + pct + '%' : j.stage === 'conferindo' ? 'Conferindo a integridade…' : 'Instalando…'}</div>` : ''}
            ${j.status === 'error' ? `<div class="small" style="color:var(--red)">${esc(j.msg)}</div>` : ''}</span>
            ${t.installed ? '<span class="yes">✓ pronto</span>' : run ? '<span class="small mut">aguarde…</span>' : `<button class="sm pri" data-toolinstall="${esc(t.name)}">Baixar e instalar</button>`}</div>`; }).join('')}
        ${row('Google Chrome', h.chrome, 'Lê as lojas e abre os sites de modelos. Instale pelo site do Google se faltar.')}${row('Claude (linha de comando)', h.claude, 'Escreve o texto do anúncio. Se falta: abra um terminal, rode <code>claude</code> e digite <code>/login</code>.')}
        <p class="small mut">Depois de instalar algo por fora: <button class="sm" data-obre>Verificar de novo</button></p>`, after: () => this.pollTools()},
      {t: 'Entre nas suas contas', body: () => `<p>As leituras usam um perfil do Chrome só do app (escolha no topo da tela). Entre uma vez nas contas abaixo, com e-mail, telefone ou Google, e <b>feche a janela</b> do Chrome quando terminar.</p>
        <div class="row">${[['Mercado Livre', 'https://www.mercadolivre.com.br/'], ['MakerWorld', 'https://makerworld.com/'], ['Printables', 'https://www.printables.com/'], ['Thingiverse', 'https://www.thingiverse.com/']].map(([n, u]) => `<button data-login="${u}">${n}</button>`).join('')}</div>
        <p class="small mut">Perfis encontrados: ${(h.profiles || []).map(esc).join(', ') || 'nenhum'}. Com o Chrome do perfil aberto o app não consegue usá-lo.</p>`},
      {t: 'Custos reais', body: () => `<p>A margem de cada produto usa estes valores. Os atuais são estimativas; coloque os seus.</p><div class="cfgform" id="obcost"></div>
        <label class="chk" style="margin-top:8px"><input type="checkbox" id="obconf"> Estes são os custos reais (confirmado)</label>`, after: () => this.fillCosts(), save: () => this.saveCosts()},
      {t: 'Dados da sua loja', body: () => `<p>Entram no texto dos anúncios.</p><div class="cfgform" id="obbiz"></div>`, after: () => this.fillBiz(), save: () => this.saveBiz()},
      {t: 'Mercado Livre pela API (opcional)', body: () => `<p>Para publicar direto pelo app, crie um app em <a href="https://developers.mercadolivre.com.br/" target="_blank" rel="noopener">developers.mercadolivre.com.br</a> com a URL de redirecionamento <code>http://localhost:8765/api/ml/callback</code> e salve o App ID e a Secret Key em Configurações.</p>
        <p>Situação agora: <b>${h.ml && h.ml.connected ? 'conta conectada' : h.ml && h.ml.configured ? 'falta conectar a conta' : 'não configurado'}</b>.</p><p class="small mut">Pode pular. Sem isso você publica no Mercado Livre copiando o kit.</p>
        <a class="btn" href="#/config" data-obgo>Abrir Configurações</a>`},
      {t: 'Primeira loja', body: () => `<p>Cole a URL de uma loja do Mercado Livre que vende produtos que você quer fazer. O Chrome vai abrir e ler os anúncios mais vendidos. Pode ser feito depois.</p>
        <textarea id="obstore" placeholder="https://www.mercadolivre.com.br/pagina/nome_da_loja"></textarea>`, save: () => this.saveStore()},
      {t: 'Tudo pronto', body: () => `<p>Resumo do que está configurado:</p>${row('Ferramentas de produção', h.slicer && h.blender && h.ffmpeg, 'Fatiamento, imagens e vídeo.')}${row('Texto com o Claude', h.claude, 'Login do Claude.')}
        ${row('Custos confirmados', h.costs_confirmed, 'Margem confiável.')}${row('Mercado Livre conectado', h.ml && h.ml.connected, 'Publicação pelo app (opcional).')}
        <p class="small mut">O que faltar fica sinalizado nas telas. Em Ajuda você refaz este assistente e vê o tour de cada tela.</p>`},
    ];
  },

  draw() {
    const steps = this.steps(), s = steps[this.step], last = this.step === steps.length - 1, b = document.getElementById('ob');
    b.innerHTML = `<div class="ob-card"><div class="ob-prog">${steps.map((_, i) => `<i class="${i < this.step ? 'done' : i === this.step ? 'cur' : ''}"></i>`).join('')}</div>
      <div class="small mut">Passo ${this.step + 1} de ${steps.length}</div><h2>${esc(s.t)}</h2><div class="ob-body">${s.body()}</div>
      <div class="ob-foot"><button class="ghost" data-obskip>Pular o assistente</button><span class="grow"></span>
        ${this.step ? '<button data-obback>Voltar</button>' : ''}<button class="pri" data-obnext>${last ? 'Começar a usar' : 'Avançar'}</button></div></div>`;
    if (s.after) s.after();
    const first = b.querySelector('input,textarea,button.pri'); if (first) first.focus();
  },

  /** Enquanto algum download roda, atualiza o passo das ferramentas a cada segundo. */
  pollTools() {
    clearTimeout(this.poll);
    if (!(this.tools || []).some(t => t.job && t.job.status === 'running')) return;
    this.poll = setTimeout(async () => {
      try { this.tools = await (await fetch('/api/tools')).json(); this.health = await (await fetch('/api/health')).json(); } catch (e) { return; }
      const b = document.getElementById('ob');
      if (b && !b.hidden && this.steps()[this.step].t === 'Ferramentas do computador') this.draw();
    }, 1000);
  },

  async next() {
    const steps = this.steps(), s = steps[this.step];
    if (s.save) { const r = await s.save(); if (r === false) return; }
    if (this.step >= steps.length - 1) { this.close(true); location.hash = '#/resumo'; return; }
    this.step++; this.save({step: this.step}); this.draw();
  },

  COSTS: [['filamento_rs_kg', 'Filamento (R$/kg)'], ['energia_rs_kwh', 'Energia (R$/kWh)'], ['maquina_rs_h', 'Desgaste da máquina (R$/hora)'], ['embalagem_rs', 'Embalagem por peça (R$)'],
    ['frete_rs', 'Frete pago pelo vendedor (R$)'], ['margem_alvo_pct', 'Margem alvo (%)']],
  async fillCosts() { const {values} = await (await fetch('/api/costs')).json();
    $('obcost').innerHTML = this.COSTS.map(([k, l]) => `<label>${l}<input type="number" step="0.01" min="0" data-oc="${k}" value="${values[k]}"></label>`).join(''); $('obconf').checked = !!values.confirmado; },
  async saveCosts() { const d = {confirmado: $('obconf').checked ? 1 : 0}; document.querySelectorAll('[data-oc]').forEach(i => d[i.dataset.oc] = i.value);
    const r = await post('/api/costs', d); if (r.error) { toast(r.error); return false; } },
  BIZ: [['nome', 'Nome da loja'], ['cores', 'Cores disponíveis (ex.: preto, branco)'], ['medidas', 'Medidas (ex.: 12 x 8 x 6 cm)'], ['prazo_dias', 'Prazo de produção (dias úteis)']],
  async fillBiz() { const b = await (await fetch('/api/business')).json();
    $('obbiz').innerHTML = this.BIZ.map(([k, l]) => `<label>${l}<input data-ob="${k}" value="${esc(b[k])}"></label>`).join(''); },
  async saveBiz() { const d = {}; document.querySelectorAll('[data-ob]').forEach(i => d[i.dataset.ob] = i.value);
    const r = await post('/api/business', d); if (r.error) { toast(r.error); return false; } },
  async saveStore() { const urls = ($('obstore').value || '').split('\n').map(x => x.trim()).filter(x => /^https:\/\/([a-z0-9-]+\.)*mercadolivre\.com\.br/i.test(x));
    if (urls.length) await addStores(urls); },
};

// ---- tour: balões sobre a tela. Cada passo aponta um elemento; se ele não existe, o passo é ignorado.
const TOURS = {
  resumo: [
    {sel: '#rfunil', t: 'Visão geral', x: 'O caminho de cada produto: lojas lidas, a revisar, em produção, kits prontos e publicados.'},
    {sel: '#rprod', t: 'Produtos, mídias e custos', x: 'Cada produto aprovado com etapas, imagens, vídeo, licença do modelo e lucro por canal.'},
    {sel: '#rsim', t: 'Simulação', x: 'Mude preço e vendas por mês e veja o lucro nos cenários pessimista, esperado e otimista.'},
    {sel: '#rpub', t: 'Meus anúncios', x: 'Tudo o que já foi publicado, com link.'}],
  lojas: [
    {sel: '#urls', t: 'Adicione lojas', x: 'Cole uma ou mais URLs de lojas do Mercado Livre, uma por linha, e clique em Analisar lojas.'},
    {sel: '#sinfo', t: 'Atualizar dados', x: 'Abre o Chrome e atualiza nome, logo e dados das lojas sem reler os anúncios.'},
    {sel: '#stores .scard', t: 'Cartão da loja', x: 'Mostra reputação, vendas e preço médio. Arraste pela alça para reordenar e use Remover para apagar a loja.'}],
  produtos: [
    {sel: '.tabs', t: 'Situação', x: 'A revisar, Aprovados, Descartados ou Todos. Aprove direto no cartão do produto.'},
    {sel: '[data-layout]', t: 'Lista ou grade', x: 'Escolha como ver os produtos. A escolha fica salva.'},
    {sel: '#sort', t: 'Ordenar', x: 'Por ranking, crescimento, vendas, preço ou na sua própria ordem, arrastando.'}],
  produto: [
    {sel: '.next', t: 'Próximo passo', x: 'Sempre mostra o que fazer agora neste produto.'},
    {sel: '.msearch', t: 'Achar o modelo', x: 'Busque o modelo 3D nos sites e escolha o arquivo. A licença aparece em cada resultado.'},
    {sel: '#icfg', t: 'Imagens configuráveis', x: 'Cor, acabamento, fundo, vistas e qualidade. Você também pode enviar fotos suas.'},
    {sel: '#vcfg', t: 'Vídeo configurável', x: 'Formato, tempo por imagem, legenda, transição e música.'}],
  config: [
    {sel: '#cform', t: 'Custos', x: 'Preencha os valores reais e marque confirmado para a margem valer.'},
    {sel: '[data-login]', t: 'Entrar nas contas', x: 'Abre o Chrome normal no perfil do app para você entrar, inclusive com Google.'}],
};

const Tour = {
  name: '', i: 0, steps: [],
  maybe(name) {
    if (Onboarding.state.done !== true || Onboarding.state.tours[name] || !TOURS[name] || document.getElementById('ob') && !document.getElementById('ob').hidden) return;
    setTimeout(() => { const ob = document.getElementById('ob');
      if (route.view === name && Onboarding.state.done === true && !Onboarding.state.tours[name] && !(ob && !ob.hidden)) this.start(name); }, 900);
  },
  start(name) {
    this.name = name; this.i = 0; this.steps = (TOURS[name] || []).filter(s => document.querySelector(s.sel));
    if (!this.steps.length) { toast('Esta tela ainda não tem passos para mostrar.'); return; }
    if (route.view !== name) { location.hash = {produto: '#/producao'}[name] || '#/' + name; setTimeout(() => this.start(name), 700); return; }
    this.draw();
  },
  draw() {
    this.clear();
    const s = this.steps[this.i], el = document.querySelector(s.sel); if (!el) return this.finish();
    el.scrollIntoView({block: 'center', behavior: 'smooth'});
    setTimeout(() => {
      const r = el.getBoundingClientRect(), ring = document.createElement('div'), tip = document.createElement('div'), last = this.i === this.steps.length - 1;
      ring.id = 'tour-ring'; ring.style.cssText = `top:${r.top - 6}px;left:${r.left - 6}px;width:${r.width + 12}px;height:${r.height + 12}px`;
      tip.id = 'tour-tip'; tip.innerHTML = `<b>${esc(s.t)}</b><p>${esc(s.x)}</p><div class="row"><span class="small mut grow">${this.i + 1} de ${this.steps.length}</span>
        <button class="ghost sm" data-tourx>Fechar</button>${this.i ? '<button class="sm" data-tourback>Voltar</button>' : ''}<button class="pri sm" data-tournext>${last ? 'Concluir' : 'Próximo'}</button></div>`;
      document.body.append(ring, tip);
      const w = 320, left = Math.max(12, Math.min(innerWidth - w - 12, r.left)), below = r.bottom + 16 + 150 < innerHeight;
      tip.style.cssText = `width:${w}px;left:${left}px;top:${below ? r.bottom + 14 : Math.max(12, r.top - 14 - tip.offsetHeight)}px`;
    }, 350);
  },
  clear() { document.getElementById('tour-ring')?.remove(); document.getElementById('tour-tip')?.remove(); },
  finish() { this.clear(); Onboarding.save({tours: {[this.name]: true}}); Onboarding.state.tours[this.name] = true; },
  next() { this.i + 1 >= this.steps.length ? this.finish() : (this.i++, this.draw()); },
  back() { if (this.i) { this.i--; this.draw(); } },
};

document.addEventListener('click', e => {
  const t = e.target;
  if (t.closest('[data-obnext]')) return Onboarding.next();
  if (t.closest('[data-obback]')) { Onboarding.step--; Onboarding.save({step: Onboarding.step}); return Onboarding.draw(); }
  if (t.closest('[data-obskip]')) return Onboarding.close(true);
  if (t.closest('[data-obre]')) return Onboarding.open(Onboarding.step);
  const ti = t.closest('[data-toolinstall]');
  if (ti) return post('/api/tools/install', {name: ti.dataset.toolinstall}).then(async r => { if (r.error) return toast(r.error);
    Onboarding.tools = await (await fetch('/api/tools')).json(); Onboarding.draw(); });
  if (t.closest('[data-obgo]')) { Onboarding.close(false); return; }
  const o = t.closest('[data-onb]'); if (o) return Onboarding.open(+o.dataset.onb);
  const tr = t.closest('[data-tour]'); if (tr) return Tour.start(tr.dataset.tour);
  if (t.closest('[data-tournext]')) return Tour.next();
  if (t.closest('[data-tourback]')) return Tour.back();
  if (t.closest('[data-tourx]')) return Tour.finish();
});
document.addEventListener('keydown', e => { if (e.key === 'Escape') { Tour.clear(); } });
