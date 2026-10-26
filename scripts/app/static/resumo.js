// Telas Resumo e Ajuda. Carrega antes do app.js; usa $, esc, post, brl, price, num, ic, date, STEP_LABEL e S (definidos lá) só quando a tela é desenhada.
const fmtDur = s => s == null ? '' : s < 60 ? `${s} s` : s < 3600 ? `${Math.floor(s / 60)} min ${s % 60} s` : `${Math.floor(s / 3600)} h ${Math.floor(s % 3600 / 60)} min`;
const localTime = ts => { if (!ts) return ''; const d = new Date(String(ts).replace(' ', 'T') + 'Z'); return isNaN(d) ? '' : d.toLocaleString('pt-BR', {day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'}); };

const RESUMO = {data: null, busy: false, simTimer: 0, simInit: false};

async function loadResumo() {
  if (RESUMO.busy) return;
  RESUMO.busy = true;
  try { RESUMO.data = await (await fetch('/api/summary')).json(); } catch (e) { RESUMO.busy = false; return; }
  RESUMO.busy = false;
  if (document.getElementById('rfunil')) drawResumo();
}

function drawResumo() {
  const d = RESUMO.data, f = d.funnel, tile = (n, l, hint) => `<div class="tile" title="${esc(hint || '')}"><b>${num(n)}</b><span>${l}</span></div>`;
  $('rfunil').innerHTML = `<div class="tiles">${tile(f.stores, 'Lojas lidas', 'Lojas do Mercado Livre que você analisou')}${tile(f.listings, 'Produtos lidos')}${tile(f.review, 'A revisar', 'Esperando aprovar ou descartar')}
    ${tile(f.approved, 'Em produção', 'Aprovados')}${tile(f.ready, 'Kits prontos', 'Kit confirmado')}${tile(f.with_video, 'Com vídeo')}${tile(f.published, 'Publicados')}</div>`;

  const chl = {ml: 'Mercado Livre', shopee: 'Shopee'};
  $('rpub').innerHTML = d.published.length ? `<div class="list">${d.published.map(p => `<div class="item"><div class="main"><a class="title" href="#/producao/${p.id}">${esc(p.title)}</a>
      <div class="meta"><span class="chip ${p.channel === 'ml' ? 'plat-ml' : 'plat-shopee'}">${chl[p.channel] || esc(p.channel)}</span>${p.external_id ? `<span>${esc(p.external_id)}</span>` : ''}</div></div>
      ${p.url ? `<a class="btn sm" href="${esc(p.url)}" target="_blank" rel="noopener">Abrir anúncio</a>` : '<span class="small mut">sem link</span>'}</div>`).join('')}</div>`
    : '<div class="empty"><b>Nenhum anúncio publicado ainda</b>Quando você publicar no Mercado Livre ou marcar a Shopee como publicada, ele aparece aqui.</div>';

  const ml = d.ml || {}, shp = d.published.filter(p => p.channel === 'shopee').length, mlp = d.published.filter(p => p.channel === 'ml').length;
  $('rmy').innerHTML = `<div class="stores">
    <div class="scard"><div class="head"><div class="logo">ML</div><div class="grow"><h3>Mercado Livre</h3><span class="small mut">${ml.connected ? 'conta conectada' : ml.configured ? 'falta conectar a conta' : 'falta configurar o app'}</span></div>
      <span class="chip ${ml.connected && !ml.error ? 'ok' : 'blocked'}">${ml.connected ? (ml.error ? 'Erro' : 'Conectada') : 'Desconectada'}</span></div>
      <dl>${ml.nickname ? `<div><dt>Usuário</dt><dd>${esc(ml.nickname)}</dd></div>` : ''}${ml.items != null ? `<div><dt>Anúncios na conta</dt><dd>${num(ml.items)}</dd></div>` : ''}
        ${ml.reputation ? `<div><dt>Reputação</dt><dd>${esc(ml.reputation)}</dd></div>` : ''}<div><dt>Publicados pelo app</dt><dd>${num(mlp)}</dd></div></dl>
      ${ml.error ? `<div class="small" style="color:var(--red)">${esc(ml.error)}</div>` : ''}
      <div class="acts">${ml.connected ? (ml.permalink ? `<a class="btn sm" href="${esc(ml.permalink)}" target="_blank" rel="noopener">Ver perfil</a>` : '') : '<a class="btn sm" href="#/config">Conectar em Configurações</a>'}</div></div>
    <div class="scard"><div class="head"><div class="logo" style="background:#EE4D2D;color:#fff">S</div><div class="grow"><h3>Shopee</h3><span class="small mut">publicação manual pela Central do Vendedor</span></div></div>
      <dl><div><dt>Links marcados como publicados</dt><dd>${num(shp)}</dd></div></dl>
      <div class="small mut">O app prepara o kit (texto, imagens, vídeo). Você cadastra na Shopee e cola o link no produto.</div></div></div>`;

  $('rcomp').innerHTML = d.stores.length ? `<div class="list">${d.stores.map(s => `<div class="item">
      <div class="logo" style="width:40px;height:40px;border-radius:50%;background:var(--yellow);display:grid;place-items:center;font-weight:700;overflow:hidden;flex:none">${s.logo ? `<img src="${esc(s.logo)}" alt="" style="width:100%;height:100%;object-fit:cover" referrerpolicy="no-referrer">` : esc((s.name || '?')[0]).toUpperCase()}</div>
      <div class="main"><a class="title" href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.name || shortUrl(s.url))}</a>
        <div class="meta"><span><b>${num(s.n)}</b> anúncios lidos</span>${s.avg_price != null ? `<span>preço médio <b>${brl(s.avg_price)}</b></span>` : ''}</div></div>
      <span class="chip ${esc(s.status)}">${STATUS_LABEL[s.status] || esc(s.status)}</span></div>`).join('')}</div>`
    : '<div class="empty"><b>Nenhuma loja lida</b><a href="#/lojas">Adicione uma loja</a> para começar.</div>';

  $('rprod').innerHTML = d.products.length ? d.products.map(p => {
    const pct = Math.round(p.done / p.total * 100), M = p.margin;
    return `<div class="rp"><div class="rp-head"><img class="thumb" src="${p.image ? '/images/' + p.id : esc(p.thumb || '')}" alt="" referrerpolicy="no-referrer">
      <div class="grow"><a class="title wrap" href="#/producao/${p.id}">${esc(p.kit_title || p.title)}</a>
        <div class="meta"><span>${price(p.price)}</span><span>${p.done} de ${p.total} etapas</span>
          ${p.slice ? `<span>${Math.floor(p.slice.minutes / 60)} h ${p.slice.minutes % 60} min · ${p.slice.grams.toLocaleString('pt-BR', {minimumFractionDigits: 1, maximumFractionDigits: 1})} g</span>` : ''}</div>
        <div class="bar" title="${pct}%"><i style="width:${pct}%"></i></div></div>
      <a class="btn sm" href="#/producao/${p.id}">Abrir</a></div>
      <div class="rp-body"><div class="stepper">${S.steps.map(n => `<div class="st ${esc(p.steps[n] || 'pending')}" title="${STATUS_LABEL[p.steps[n]] || ''}">${STEP_LABEL[n] || n}</div>`).join('')}</div>
        ${M ? `<div class="meta" style="margin:6px 0"><span>Mercado Livre: lucro <b>${brl(M.ml.lucro)}</b> (${M.ml.margem_pct.toLocaleString('pt-BR', {minimumFractionDigits: 1, maximumFractionDigits: 1})}%)</span>
          <span>Shopee: lucro <b>${brl(M.shopee.lucro)}</b> (${M.shopee.margem_pct.toLocaleString('pt-BR', {minimumFractionDigits: 1, maximumFractionDigits: 1})}%)</span><span>custo por peça <b>${brl(M.ml.custo_total)}</b></span></div>` : '<div class="small mut">Sem custo ainda: fatie o modelo.</div>'}
        ${p.model && p.model.source_url ? `<div class="small mut">Modelo: <a href="${esc(p.model.source_url)}" target="_blank" rel="noopener">fonte</a> · ${esc(p.model.license_note || 'licença não anotada')}</div>` : ''}
        <div class="media">${p.images.slice(0, 8).map(n => `<a href="/products/${p.id}/renders/${n}" target="_blank" rel="noopener"><img src="/products/${p.id}/renders/${n}" alt="" loading="lazy"></a>`).join('')}
          ${p.has_video ? `<a class="vid" href="/products/${p.id}/kit/video.mp4" target="_blank" rel="noopener">▶ Vídeo</a>` : ''}
          ${!p.images.length && !p.has_video ? '<span class="small mut">Sem imagens nem vídeo ainda.</span>' : ''}</div>
        ${Object.keys(p.publications).length ? `<div class="meta">${Object.entries(p.publications).map(([ch, x]) => `<span class="chip ok">${ch === 'ml' ? 'Mercado Livre' : 'Shopee'}: publicado</span>`).join('')}</div>` : ''}</div></div>`;
  }).join('') : '<div class="empty"><b>Nenhum produto em produção</b>Aprove produtos na aba <a href="#/produtos">Produtos</a>.</div>';

  const c = d.costs, L = d.labels, keys = ['filamento_rs_kg', 'energia_rs_kwh', 'maquina_rs_h', 'embalagem_rs', 'frete_rs', 'ml_pct', 'shopee_pct', 'margem_alvo_pct'];
  $('rcost').innerHTML = `<div class="row" style="margin-bottom:8px"><span class="chip ${d.costs_confirmed ? 'ok' : 'blocked'}">${d.costs_confirmed ? 'Custos confirmados' : 'Custos provisórios'}</span>
    <a href="#/config" class="small">Editar em Configurações</a></div>
    <div class="tiles">${keys.map(k => `<div class="tile"><b>${/_pct$/.test(k) ? Number(c[k]).toLocaleString('pt-BR') + '%' : brl(c[k])}</b><span>${esc(L[k] || k)}</span></div>`).join('')}</div>`;
}

// ---- simulação: os controles são desenhados uma vez; só o resultado é refeito
function drawSimControls() {
  const prods = RESUMO.data.products.filter(p => p.slice);
  if (!prods.length) { $('rsim').innerHTML = '<div class="empty"><b>Nada para simular ainda</b>Fatie ao menos um produto aprovado e a simulação aparece aqui.</div>'; RESUMO.simInit = false; return; }
  if (RESUMO.simInit === prods.map(p => p.id).join()) return;
  RESUMO.simInit = prods.map(p => p.id).join();
  $('rsim').innerHTML = `<div class="row" style="margin-bottom:10px"><label class="small mut">Canal <select id="simch"><option value="ml">Mercado Livre</option><option value="shopee">Shopee</option></select></label>
      <label class="small mut">Custo fixo por mês (R$) <input id="simfix" type="number" min="0" step="10" value="0" style="width:110px"></label></div>
    <div class="tablewrap"><table><thead><tr><th>Produto</th><th style="width:130px">Preço (R$)</th><th style="width:210px">Vendas por mês</th></tr></thead><tbody>
      ${prods.map(p => `<tr><td>${esc(p.kit_title || p.title)}</td><td><input type="number" min="5" max="2000" step="0.5" value="${p.price}" data-sp="${p.id}" style="width:100px"></td>
        <td><input type="range" min="0" max="200" value="10" data-su="${p.id}" style="width:120px"> <input type="number" min="0" max="10000" value="10" data-sn="${p.id}" style="width:64px"></td></tr>`).join('')}</tbody></table></div>
    <div id="simres" style="margin-top:12px"></div>`;
  const run = () => { clearTimeout(RESUMO.simTimer); RESUMO.simTimer = setTimeout(runSim, 250); };
  $('rsim').oninput = e => { const t = e.target; if (t.dataset.su) document.querySelector(`[data-sn="${t.dataset.su}"]`).value = t.value;
    if (t.dataset.sn) document.querySelector(`[data-su="${t.dataset.sn}"]`).value = Math.min(200, t.value); run(); };
  $('rsim').onchange = run;
  runSim();
}

async function runSim() {
  if (!$('simch')) return;
  const items = [...document.querySelectorAll('[data-sp]')].map(i => ({id: +i.dataset.sp, price: +i.value, units: +document.querySelector(`[data-sn="${i.dataset.sp}"]`).value}));
  const r = await post('/api/simulate', {channel: $('simch').value, fixed: +$('simfix').value || 0, items});
  const box = $('simres'); if (!box) return;
  if (r.error) { box.innerHTML = `<div class="small" style="color:var(--red)">${esc(r.error)}</div>`; return; }
  const sc = r.cenarios, title = {pessimista: 'Pessimista (metade das vendas)', esperado: 'Esperado', otimista: 'Otimista (1,5x das vendas)'};
  const byId = Object.fromEntries(RESUMO.data.products.map(p => [p.id, p]));
  box.innerHTML = `<div class="tiles">${Object.keys(sc).map(k => `<div class="tile ${sc[k] < 0 ? 'neg' : ''}"><b>${brl(sc[k])}</b><span>Lucro por mês · ${title[k]}</span></div>`).join('')}
      <div class="tile"><b>${brl(r.receita)}</b><span>Receita por mês</span></div><div class="tile"><b>${num(r.horas)} h</b><span>Horas de máquina por mês</span></div>
      <div class="tile"><b>${num(r.gramas)} g</b><span>Filamento por mês</span></div>
      <div class="tile"><b>${r.equilibrio_unidades == null ? 'nunca' : num(r.equilibrio_unidades)}</b><span>Peças por mês para cobrir o custo fixo</span></div></div>
    <div class="tablewrap" style="margin-top:12px"><table><thead><tr><th>Produto</th><th>Custo por peça</th><th>Taxas</th><th>Lucro por peça</th><th>Margem</th><th>Lucro no mês</th></tr></thead><tbody>
      ${r.rows.map(x => `<tr><td>${esc((byId[x.id] || {}).kit_title || (byId[x.id] || {}).title || x.id)}</td><td class="num">${brl(x.custo_peca)}</td><td class="num">${brl(x.taxas_peca)}</td>
        <td class="num" style="color:${x.lucro_peca > 0 ? 'var(--green)' : 'var(--red)'}">${brl(x.lucro_peca)}</td><td class="num">${x.margem_pct.toLocaleString('pt-BR', {minimumFractionDigits: 1, maximumFractionDigits: 1})}%</td><td class="num"><b>${brl(x.lucro_mes)}</b></td></tr>`).join('')}</tbody></table></div>
    ${RESUMO.data.costs_confirmed ? '' : '<p class="small mut">Os custos ainda são estimativas; ajuste em <a href="#/config">Configurações</a> para a simulação valer.</p>'}`;
}

const VIEWS_EXTRA = {
  resumo: {
    mount: () => `<div class="card" id="c-funil"><h2>Visão geral</h2><div id="rfunil"></div></div>
      <div class="card" id="c-prod"><div class="card-h"><h2>Produtos, mídias e custos</h2><a href="#/produtos" class="small">Ver todos os produtos</a></div><div id="rprod"></div></div>
      <div class="card" id="c-pub"><h2>Meus anúncios</h2><div id="rpub"></div></div>
      <div class="card" id="c-my"><h2>Minhas lojas e contas</h2><div id="rmy"></div></div>
      <div class="card" id="c-sim"><h2>Simulação de lucro</h2><p class="small mut" style="margin-top:0">Mude o preço e as vendas por mês e veja o lucro. Usa os custos de Configurações e o tempo e o filamento do fatiamento.</p><div id="rsim"></div></div>
      <div class="card" id="c-cost"><h2>Custos e taxas</h2><div id="rcost"></div></div>
      <div class="card" id="c-comp"><div class="card-h"><h2>Lojas que estou analisando</h2><a href="#/lojas" class="small">Gerenciar lojas</a></div><div id="rcomp"></div></div>`,
    update: () => { if (RESUMO.data) { drawResumo(); drawSimControls(); } loadResumo().then(() => { if ($('rsim')) drawSimControls(); }); },
  },
  ajuda: {
    mount: () => `<div class="card"><h2>Como o Minerador 3D funciona</h2>
        <ol class="flow"><li><b>Lojas.</b> Cole a URL de lojas do Mercado Livre que vendem bem. O app abre o Chrome, lê os anúncios mais vendidos e guarda preços, vendas e avaliações.</li>
          <li><b>Produtos.</b> Veja o ranking, aprove os que quer vender e descarte o resto.</li>
          <li><b>Modelo 3D.</b> Na Produção, busque o arquivo do modelo nos sites de modelos (Printables, MakerWorld, Thingiverse) e anote a licença.</li>
          <li><b>Etapas automáticas.</b> O app fatia o modelo, calcula custo e margem, escreve o texto com o Claude e gera as imagens.</li>
          <li><b>Kit.</b> Você revisa texto, preço e imagens e confirma. Dá para gravar a voz e gerar um vídeo.</li>
          <li><b>Publicar.</b> No Mercado Livre pelo app; na Shopee pela Central do Vendedor, colando o link depois. Nada vai ao ar sem o seu clique.</li></ol></div>
      <div class="card"><h2>Ajuda guiada</h2><p class="small mut" style="margin-top:0">Refaça o assistente inicial ou veja o passo a passo de cada tela.</p>
        <div class="row"><button class="pri" data-onb="0">Refazer o assistente inicial</button><button data-tour="resumo">Tour do Resumo</button><button data-tour="lojas">Tour das Lojas</button>
          <button data-tour="produtos">Tour dos Produtos</button><button data-tour="produto">Tour da Produção de um produto</button><button data-tour="config">Tour das Configurações</button></div></div>
      <div class="card"><h2>Perguntas comuns</h2>
        <details><summary>O Chrome pede captcha ou login</summary><p>Resolva na janela que o app abriu. A leitura continua sozinha. Para entrar com Google, use Configurações &gt; Entrar nas contas.</p></details>
        <details><summary>Por que a Shopee não é lida pelo app?</summary><p>A Shopee bloqueia navegador controlado por programa. O app prepara o kit e você cadastra o produto por lá.</p></details>
        <details><summary>O texto do anúncio não é gerado</summary><p>O app usa o Claude da linha de comando. Abra um terminal, rode <code>claude</code> e digite <code>/login</code> uma vez.</p></details>
        <details><summary>As imagens demoram</summary><p>Elas são renderizadas no Blender, no processador. Em Imagens do anúncio, escolha a qualidade Rápida (cerca de 1 minuto) ou reduza o número de vistas.</p></details>
        <details><summary>Os custos e a margem estão certos?</summary><p>Só depois que você preencher os valores reais em Configurações e marcar “confirmado”. Até lá são estimativas.</p></details></div>`,
    bind: () => {},
    update: () => {},
  },
};
