const STEP_LABEL = {model:'Modelo 3D', slice:'Fatiar', cost:'Custo e margem', copy:'Texto do anúncio', images:'Imagens', kit:'Kit pronto', ml:'Mercado Livre', shopee:'Shopee', video:'Vídeo'};
const STATUS_LABEL = {pending:'Na fila', running:'Lendo', captcha:'Precisa de você', done:'Concluída', error:'Erro', ok:'Pronto', blocked:'Bloqueado'};
let pv = 'ml', S = {stores:[], candidates:[], steps:[], profiles:[]}, route = ['lojas'];
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const store = (k, v) => { try { v === undefined ? (v = localStorage[k]) : (localStorage[k] = v); } catch (e) {} return v; };
let filter = store('pfilter') || 'new', layout = store('playout') || 'list';
const shortUrl = u => { try { const x = new URL(u); return x.hostname.replace('www.', '') + x.pathname; } catch (e) { return u; } };
const validUrls = () => $('urls').value.split('\n').map(s => s.trim()).filter(u => /^https:\/\/([a-z0-9-]+\.)*mercadolivre\.com\.br(\/|\?|$)/i.test(u));
// dinheiro em pt-BR: sempre com vírgula e centavos; price() é a versão com centavos pequenos, como no Mercado Livre
const brl = v => v == null ? '—' : 'R$ ' + Number(v).toLocaleString('pt-BR', {minimumFractionDigits: 2, maximumFractionDigits: 2});
const price = v => { if (v == null) return '—'; const [i, c] = Number(v).toFixed(2).split('.'); return `R$ ${Number(i).toLocaleString('pt-BR')}<small>,${c}</small>`; };
const num = v => v == null ? '—' : Number(v).toLocaleString('pt-BR');
const ic = n => `<svg class="ic" aria-hidden="true"><use href="#i-${n}"/></svg>`;

const errHint = m => /captcha/i.test(m) ? 'o captcha não foi resolvido a tempo'
  : /closed/i.test(m) ? 'a janela do Chrome foi fechada'
  : /in use|already|lock|user data directory/i.test(m) ? 'o perfil está aberto em outro Chrome; feche-o'
  : /perfil/i.test(m) ? m : 'falha inesperada: ' + m.slice(0, 120);

function toast(msg) { const t = $('toast'); t.textContent = msg; t.classList.add('show'); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove('show'), 2600); }
async function post(url, body) { return (await fetch(url, {method:'POST', body:JSON.stringify(body)})).json(); }
async function load() {
  try { S = await (await fetch('/api/state')).json(); $('offline').style.display = 'none'; update(); }
  catch (e) { $('offline').style.display = 'block'; }
}

async function addStores(urls) {
  if (!$('profile').value) return toast('Escolha um perfil do Chrome primeiro');
  const r = await post('/api/stores', {urls, profile: $('profile').value});
  if (r.error) return toast(r.error);
  toast(r.added ? `${r.added} loja(s) na fila. O Chrome vai abrir.` : 'Essas lojas já estão na fila');
  if ($('urls')) { $('urls').value = ''; onUrls(); }
  load();
}
async function refreshInfo(id) {
  if (!$('profile').value) return toast('Escolha um perfil do Chrome primeiro');
  const r = await post('/api/stores/info', {id, profile: $('profile').value});
  toast(r.error || 'O Chrome vai abrir para atualizar os dados. Se pedir captcha, resolva por lá.'); setTimeout(load, 15000);
}
async function decide(id, status, msg) { await post('/api/decide', {id, status}); toast(msg); load(); }
function onUrls() {
  const lines = $('urls').value.split('\n').filter(s => s.trim()).length, ok = validUrls().length;
  $('add').disabled = !ok;
  $('urlhint').textContent = !lines ? 'O app abre o Chrome e lê os mais vendidos de cada loja, um anúncio por vez.'
    : `${ok} URL(s) válida(s)` + (lines > ok ? ` · ${lines - ok} ignorada(s) (não são do Mercado Livre)` : '');
}

// ---- telas: mount() desenha o esqueleto uma vez por rota; update() só preenche os dados (não apaga o que a pessoa digitou)
const VIEWS = {
  lojas: {
    mount: () => `<div class="card"><h2>Adicionar lojas</h2>
        <textarea id="urls" placeholder="Cole aqui uma ou mais URLs de lojas do Mercado Livre, uma por linha.&#10;Ex.: https://www.mercadolivre.com.br/pagina/nome_da_loja"></textarea>
        <div class="row small" style="margin-top:8px"><label class="chk"><input type="checkbox" class="bshow" checked> Mostrar o navegador durante a leitura</label>
          <span class="mut">O Chrome do app abre à vista e você acompanha (e resolve captchas). Desligado, roda escondido.</span></div>
        <div class="row" style="margin-top:10px"><span id="urlhint" class="small mut grow"></span><button id="add" class="pri" disabled>${ic('plus')}Analisar lojas</button></div></div>
      <div class="card"><div class="card-h"><h2>Lojas</h2><button id="sinfo" class="sm" title="Abre o Chrome e atualiza nome, logo e dados de cada loja, sem reler os anúncios">${ic('refresh')}Atualizar dados das lojas</button></div><div id="stores" class="stores"></div></div>`,
    bind: () => { $('sinfo').onclick = () => refreshInfo('all'); $('urls').oninput = onUrls; $('add').onclick = () => addStores(validUrls()); onUrls(); },
    update: () => {
      const rep = r => { const lv = /platinum/i.test(r) ? 5 : /gold|ouro/i.test(r) ? 4 : /l[ií]der|prata/i.test(r) ? 3 : 0;
        return `<span class="rep" aria-hidden="true">${[1,2,3,4,5].map(i => `<i class="${i <= lv ? 'on' + lv : ''}"></i>`).join('')}</span> ${esc(r)}`; };
      // só entra o que a leitura achou: campo sem dado não aparece
      const fields = s => [['Plataforma', `<span class="chip plat-${esc(s.platform || 'ml')}">Mercado Livre</span>`],
        ['Reputação', s.reputation && rep(s.reputation)], ['Localização', s.location && esc(s.location)], ['Na plataforma', s.since_text && esc(s.since_text)],
        ['Vendas', s.sales != null && '+' + num(s.sales)], ['Avaliação', s.rating != null && String(s.rating).replace('.', ',') + ' de 5'],
        ['Seguidores', s.followers != null && num(s.followers)], ['Anúncios lidos', num(s.n)], ['Preço médio', s.avg_price != null && brl(s.avg_price)],
        ['Perfil do Chrome', s.profile && esc(s.profile)], ['Mais vendido', s.best && `<span title="${esc(s.best)}">${esc(s.best)}</span>`, true],
        ['Última leitura', (s.read_at || s.added_at) && date(s.read_at || s.added_at)]]
        .filter(f => f[1]).map(([l, v, wide]) => `<div${wide ? ' style="grid-column:1/-1"' : ''}><dt>${l}</dt><dd>${v}</dd></div>`).join('');
      $('stores').innerHTML = S.stores.length ? S.stores.map(s => `<div class="scard" data-key="${s.id}">
          <div class="head"><div class="logo">${s.logo ? `<img src="${esc(s.logo)}" alt="" referrerpolicy="no-referrer">` : esc(storeName(s)[0] || '?').toUpperCase()}</div>
            <div class="grow"><h3 title="${esc(storeName(s))}">${esc(storeName(s))}</h3>
              <a class="small" href="${esc(s.url)}" target="_blank" rel="noopener">${esc(shortUrl(s.url).slice(0, 44))}</a></div>
            <span class="chip ${esc(s.status)}">${STATUS_LABEL[s.status] || esc(s.status)}</span></div>
          <dl>${fields(s)}</dl>
          ${s.status === 'done' && !s.n ? '<div class="small" style="color:var(--orange)">Nenhum anúncio encontrado nessa página.</div>' : ''}
          <div class="acts"><a class="btn sm" href="#/produtos" data-store="${s.id}">${ic('box')}Ver produtos</a>
            <button class="sm danger" data-remove="${s.id}" title="Remove a loja e os ${s.n} anúncios lidos (${s.n_appr} aprovados). Arquivos em products/ ficam no disco.">${ic('trash')}${armed.id === s.id && Date.now() < armed.until ? 'Clique de novo para remover' : 'Remover'}</button>
            <button class="sm" data-info="${s.id}" title="Atualiza só nome, logo e dados da loja">${ic('refresh')}Atualizar dados</button>
            ${['done','error'].includes(s.status) ? `<button class="sm" data-rerun="${esc(s.url)}" title="Lê de novo; serve para medir crescimento">${ic('refresh')}Ler de novo</button>` : ''}</div>
        </div>`).join('')
        : `<div class="empty"><b>Nenhuma loja ainda</b>Cole a URL de uma loja acima e clique em Analisar lojas.</div>`;
    },
  },
  config: {
    mount: () => `<div class="card"><h2>Entrar nas contas (Chrome)</h2>
        <p class="small mut" style="margin-top:0">Abre o Chrome normal, sem automação, no perfil escolhido no topo da tela. Entre com e-mail, telefone ou <b>Google</b> e depois <b>feche a janela</b>: o app reaproveita o login nas leituras e nas buscas. Com essa janela aberta o app não consegue usar o perfil.</p>
        <div class="row">${[['Mercado Livre', 'https://www.mercadolivre.com.br/'], ['MakerWorld', 'https://makerworld.com/'],
          ['Printables', 'https://www.printables.com/'], ['Thingiverse', 'https://www.thingiverse.com/']].map(([n, u]) => `<button data-login="${u}">${ic('store')}${n}</button>`).join('')}</div></div>
      <div class="card"><h2>Custos e taxas</h2>
        <p class="small mut" style="margin-top:0">Valores provisórios (estimativas). A margem de cada produto usa estes números; marque “confirmado” quando forem os reais.</p>
        <div class="form" id="cform"></div></div>
      <div class="card"><h2>Dados da loja (usados no texto dos anúncios)</h2><div class="form" id="bform"></div></div>
      <div class="card"><h2>Conta do Mercado Livre</h2><p id="mlst" class="small mut" style="margin-top:0"></p><div class="form" id="mlcfg"></div></div>`,
    bind: async () => {
      const {values, labels} = await (await fetch('/api/costs')).json();
      $('cform').innerHTML = Object.keys(labels).map(k => `<label>${esc(labels[k])}<input type="number" step="0.01" min="0" data-k="${k}" value="${values[k]}"></label>`).join('') +
        `<label class="row" style="flex-direction:row;gap:8px;color:var(--fg);font-size:14px"><input type="checkbox" id="cconf" ${values.confirmado ? 'checked' : ''}> Estes são os custos reais (confirmado)</label>
         <div class="row"><button id="csave" class="pri">Salvar custos</button></div>`;
      const b = await (await fetch('/api/business')).json(), BL = {nome:'Nome da loja', cores:'Cores disponíveis (ex.: preto, branco)', medidas:'Medidas (ex.: 12 x 8 x 6 cm)', prazo_dias:'Prazo de produção (dias úteis)'};
      $('bform').innerHTML = Object.keys(BL).map(k => `<label>${BL[k]}<input data-b="${k}" value="${esc(b[k])}"></label>`).join('') + '<div class="row"><button id="bsave" class="pri">Salvar dados da loja</button></div>';
      $('bsave').onclick = async () => { const d = {}; document.querySelectorAll('[data-b]').forEach(i => d[i.dataset.b] = i.value);
        const r = await post('/api/business', d); toast(r.error || 'Dados da loja salvos'); };
      const drawML = async () => { const m = await (await fetch('/api/ml/status')).json();
        $('mlst').innerHTML = `Crie o app em <a href="https://developers.mercadolivre.com.br/" target="_blank" rel="noopener">developers.mercadolivre.com.br</a> com a URL de redirecionamento <code>http://localhost:8765/api/ml/callback</code>. A Secret Key fica só neste computador. Situação: <b>${m.connected ? 'conta conectada' : m.configured ? 'falta conectar' : 'falta configurar'}</b>.`;
        $('mlcfg').innerHTML = `<label>App ID<input id="mlid" inputmode="numeric" autocomplete="off"></label><label>Secret Key<input id="mlsec" type="password" autocomplete="off" placeholder="${m.configured ? 'salva (digite para trocar)' : ''}"></label>
          <div class="row"><button id="mlsave">Salvar credenciais</button><a class="btn" href="/api/ml/auth" target="_blank" rel="noopener">Conectar conta</a></div>
          <label>Se o ML mostrar o código em vez de voltar para cá, cole o código (TG-...) ou a URL inteira<input id="mlcode"></label><div class="row"><button id="mlsend">Enviar código</button></div>`;
        $('mlsave').onclick = async () => { const r = await post('/api/ml/config', {client_id: $('mlid').value, client_secret: $('mlsec').value}); toast(r.error || 'Credenciais salvas'); drawML(); };
        $('mlsend').onclick = async () => { const r = await post('/api/ml/code', {code: $('mlcode').value}); toast(r.error || 'Conta conectada'); drawML(); }; };
      drawML();
      $('csave').onclick = async () => { const d = {confirmado: $('cconf').checked ? 1 : 0};
        document.querySelectorAll('[data-k]').forEach(i => d[i.dataset.k] = i.value);
        const r = await post('/api/costs', d); toast(r.error || 'Custos salvos'); load(); };
    },
    update: () => {},
  },
  produtos: {
    mount: () => `<div class="card"><div class="card-h"><h2>Produtos</h2>
        <div class="seg" role="group" aria-label="Exibição"><button data-layout="list" aria-pressed="${layout === 'list'}">${ic('list')}Lista</button><button data-layout="grid" aria-pressed="${layout === 'grid'}">${ic('grid')}Grade</button></div></div>
      <div class="tabs" role="group" aria-label="Situação">${[['new','A revisar'],['approved','Aprovados'],['discarded','Descartados'],['all','Todos']].map(([k, l]) =>
        `<button data-view="${k}" aria-pressed="${filter === k}">${l}<span class="n" id="n-${k}"></span></button>`).join('')}</div>
      <div class="toolbar"><select id="pstore" aria-label="Loja"><option value="">Todas as lojas</option></select>
        <select id="sort" aria-label="Ordenar"><option value="score">Melhor ranking</option><option value="growth">Mais crescimento</option><option value="sold">Mais vendidos</option>
          <option value="pa">Menor preço</option><option value="pd">Maior preço</option><option value="recent">Lidos recentemente</option><option value="manual">Minha ordem (arraste)</option></select>
        <span id="pcount" class="small mut grow"></span><button id="csv" class="sm ghost">Exportar CSV</button></div>
      <div id="plist"></div></div>`,
    bind: () => {
      $('pstore').onchange = $('sort').onchange = update;
      document.querySelectorAll('[data-view]').forEach(b => b.onclick = () => { filter = b.dataset.view; store('pfilter', filter);
        document.querySelectorAll('[data-view]').forEach(x => x.setAttribute('aria-pressed', x === b)); update(); });
      document.querySelectorAll('[data-layout]').forEach(b => b.onclick = () => { layout = b.dataset.layout; store('playout', layout);
        document.querySelectorAll('[data-layout]').forEach(x => x.setAttribute('aria-pressed', x === b)); update(); });
      $('csv').onclick = () => { const rows = catalog(), cols = [['title','Produto'],['store_name','Loja'],['price','Preço'],['sold','Vendidos'],['reviews','Avaliações'],['material','Material'],['status','Situação'],['last_seen','Última leitura']];
        const val = (c, k) => k === 'price' ? (c.price == null ? '' : String(c.price).replace('.', ',')) : k === 'last_seen' ? date(c[k]) : c[k] ?? '';
        const csv = [cols.map(c => c[1]), ...rows.map(c => cols.map(([k]) => val(c, k)))].map(r => r.map(v => `"${String(v).replace(/"/g, '""')}"`).join(';')).join('\n');
        const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob(['﻿' + csv], {type:'text/csv'})); a.download = 'produtos.csv'; a.click(); };
    },
    update: () => {
      const sf = $('pstore');
      if (sf.options.length !== S.stores.length + 1)
        sf.innerHTML = '<option value="">Todas as lojas</option>' + S.stores.map(s => `<option value="${s.id}">${esc(storeName(s))}</option>`).join('');
      if (pendingStore) { sf.value = pendingStore; pendingStore = ''; }
      ['new','approved','discarded','all'].forEach(k => { $('n-' + k).textContent = num(S.candidates.filter(c => k === 'all' || c.status === k).length); });
      const rows = catalog(), max = Math.max(1, ...S.candidates.map(c => c.score));
      $('pcount').textContent = `${num(rows.length)} de ${num(S.candidates.length)} produtos`;
      const acts = c => c.status === 'new' ? `<button class="ghost sm" data-decide="${c.id}" data-st="discarded">${ic('x')}Descartar</button><button class="pri sm" data-decide="${c.id}" data-st="approved">${ic('check')}Aprovar</button>`
        : c.status === 'approved' ? `<a class="btn sm" href="#/producao/${c.id}">Produzir</a>` : `<button class="sm" data-decide="${c.id}" data-st="new">${ic('undo')}Restaurar</button>`;
      const stat = {new:'A revisar', approved:'Aprovado', discarded:'Descartado'};
      $('plist').innerHTML = !rows.length ? `<div class="empty"><b>${S.candidates.length ? 'Nenhum produto neste filtro' : 'Nenhum produto ainda'}</b>${S.candidates.length ? 'Troque a aba ou a loja.' : 'Leia uma loja e os produtos aparecem aqui.'}</div>`
        : layout === 'grid' ? `<div class="grid">${rows.map(c => `<div class="pcard" data-key="${c.id}"><a class="pic" href="${esc(c.url)}" target="_blank" rel="noopener">${img(c)}<span class="chip ${esc(c.status)}">${stat[c.status]}</span></a>
            <div class="body"><a class="title wrap" href="${esc(c.url)}" target="_blank" rel="noopener" title="${esc(c.title)}">${esc(c.title || c.url)}</a>
              <div class="price">${price(c.price)}</div><div class="small mut">+${num(c.sold)} vendidos · ${num(c.reviews)} avaliações</div>
              <div class="small mut" title="${esc(c.store_name || '')}">${esc(c.store_name || '')}</div>
              <div class="bar" title="Ranking ${c.score}"><i style="width:${Math.round(c.score / max * 100)}%"></i></div></div>
            <div class="foot">${acts(c)}</div></div>`).join('')}</div>`
        : `<div class="list">${rows.map(c => `<div class="item" data-key="${c.id}"><div class="score" title="Ranking"><b>${c.score}</b><div class="bar"><i style="width:${Math.round(c.score / max * 100)}%"></i></div></div>
            ${img(c)}<div class="main"><a class="title wrap" href="${esc(c.url)}" target="_blank" rel="noopener" title="Abrir anúncio">${esc(c.title || c.url)}</a>
              <div class="price">${price(c.price)}<span class="sold">+${num(c.sold)} vendidos</span></div>
              <div class="meta"><span>${esc(c.store_name || '—')}</span><span><b>${num(c.reviews)}</b> avaliações</span>${growthInfo(c)}
                ${c.material ? `<span>material ${esc(c.material.replace(/^[:\s]+/, ''))}</span>` : ''}<span class="chip ${esc(c.status)}">${stat[c.status]}</span></div></div>
            <div class="actions">${acts(c)}</div></div>`).join('')}</div>`;
    },
  },
  producao: {
    mount: () => `<div class="card"><h2>Produtos aprovados</h2><div id="appr" class="list"></div></div>`,
    update: () => {
      const approved = S.candidates.filter(c => c.status === 'approved');
      $('appr').innerHTML = approved.length ? approved.map(c => {
        const done = S.steps.filter(n => c.steps[n] === 'ok').length;
        return `<div class="item" data-key="${c.id}"><div class="main">
          <a class="title" href="#/producao/${c.id}">${esc(c.title)}</a>
          <div class="price">${price(c.price)}<span class="sold">${done} de ${S.steps.length} etapas</span></div>
          <div class="stepper">${stepper(c)}</div></div>
          <div class="actions"><button class="ghost" data-decide="${c.id}" data-st="new" title="Volta para a revisão">Desfazer</button></div></div>`; }).join('')
        : `<div class="empty"><b>Nenhum produto aprovado</b>Aprove produtos na aba Produtos para começar a produção.</div>`;
    },
  },
  produto: {
    // o cabeçalho é refeito a cada atualização; o card do modelo é montado uma vez para não apagar o que você digita
    mount: () => `<div id="prod"></div>
      <div class="card" id="ovcard" hidden></div>
      <div class="card" id="tlcard" hidden><div class="card-h"><h2>Linha do tempo</h2><span class="small mut">cada etapa, quando rodou e quanto levou</span></div><div id="tline"></div></div>
      <div class="card" id="mcard" hidden><div class="card-h"><h2>Modelo 3D</h2><span id="mchip" class="chip"></span></div>
        <p id="mstate" class="small mut" style="margin:0 0 12px"></p>
        <div class="msearch"><h3>Achar o modelo nos sites</h3>
          <div class="row"><input id="msq" type="search" class="grow" placeholder="O que buscar (ex.: porta chaves de parede)" aria-label="Buscar modelo"><button id="msgo" class="pri sm">${ic('search')}Buscar modelos</button></div>
          <div class="row small mut" style="margin:6px 0"><label><input type="checkbox" data-msite="makerworld" checked> MakerWorld</label>
            <label><input type="checkbox" data-msite="printables" checked> Printables</label><label><input type="checkbox" data-msite="thingiverse" checked> Thingiverse</label>
            <span>(MakerWorld e Thingiverse abrem o Chrome do perfil escolhido no topo)</span></div>
          <div class="row small" style="margin:6px 0"><label class="chk"><input type="checkbox" id="mshow" checked> Mostrar o navegador durante a busca</label>
            <span class="mut">Desligado, o Chrome roda escondido (headless). Ligado, você acompanha a busca na janela e resolve verificações. Precisa de um perfil escolhido no topo.</span></div>
          <div class="row small" style="margin:6px 0"><button id="mterms" class="sm ghost">Sugerir termos em inglês</button><span id="mchips" class="chips"></span></div>
          <p id="msmsg" class="small mut" style="margin:4px 0"></p><div id="msres" class="mres"></div></div>
        <div class="form">
          <label>Link do modelo (MakerWorld, Printables…)<input id="mlink" type="url" placeholder="https://makerworld.com/..."></label>
          <label>Licença (anote o que o autor permite)<input id="mlic" maxlength="500" placeholder="Ex.: CC BY-NC, uso comercial só com permissão"></label>
          <div class="row"><button id="msave">Salvar link e licença</button></div>
          <label>Arquivo do modelo (.3mf ou .stl, até 200 MB)<input id="mfile" type="file" accept=".3mf,.stl"></label>
          <div class="row"><button id="mup" class="pri">Enviar arquivo</button>
            <select id="minbox" aria-label="Arquivos em inbox"></select><button id="muse">Usar arquivo de inbox/</button></div>
        </div></div>
      <div class="card" id="scard" hidden><div class="card-h"><h2>Fatiamento</h2><span id="schip" class="chip"></span></div>
        <p id="sstate" class="small mut" style="margin:0 0 12px"></p>
        <div class="row"><button id="sgo" class="pri">Fatiar agora</button></div></div>
      <div class="card" id="ccard" hidden><div class="card-h"><h2>Custo e margem</h2><span id="cchip" class="chip"></span></div>
        <div class="row" style="margin-bottom:12px"><label class="small mut">Preço-alvo (R$) <input id="cprice" type="number" step="0.01" min="5" style="height:40px;width:120px;margin-left:6px"></label>
          <button id="cpsave">Salvar preço</button></div>
        <p id="cstate" class="small mut" style="margin:0 0 8px"></p><div class="tablewrap"><table id="ctab"></table></div></div>
      <div class="card" id="tcard" hidden><div class="card-h"><h2>Texto do anúncio</h2><span id="tchip" class="chip"></span></div>
        <p id="tstate" class="small mut" style="margin:0 0 12px"></p>
        <div class="form">
          <label>Título (até 60 caracteres) <span id="tcount"></span><input id="ttitle" maxlength="60"></label>
          <label>Descrição<textarea id="tdesc" style="min-height:160px"></textarea></label>
          <label>Bullets (um por linha)<textarea id="tbul" style="min-height:90px"></textarea></label>
          <label>Roteiros de vídeo (separe com uma linha em branco)<textarea id="tscr" style="min-height:120px"></textarea></label>
          <label>Palavras-chave (separe com vírgula)<input id="tkey"></label>
          <div class="row"><button id="tgen" class="pri">Gerar com Claude</button><button id="tsave">Salvar edições</button></div>
        </div></div>
      <div class="card" id="icard" hidden><div class="card-h"><h2>Imagens do anúncio</h2><span id="ichip" class="chip"></span></div>
        <p id="istate" class="small mut" style="margin:0 0 12px"></p>
        <details class="cfg" open><summary>Configurar as imagens</summary><div id="icfg" class="cfgform"></div></details>
        <div class="row" style="margin:12px 0"><button id="igo" class="pri">Gerar imagens</button>
          <label class="small mut">Ou envie uma foto sua <input id="ifoto" type="file" accept="image/*"></label><button id="ifup" class="sm">Enviar foto</button></div>
        <p class="small mut" style="margin:0 0 8px">Use as setas para mudar a ordem (a primeira é a foto principal) e Ocultar para tirar uma imagem do anúncio, do kit e do vídeo.</p>
        <div id="igal" class="gallery"></div></div>
      <div class="card" id="vcard" hidden><div class="card-h"><h2>Vídeo</h2><span id="vchip" class="chip"></span></div>
        <p id="vstate" class="small mut" style="margin:0 0 12px"></p>
        <details class="cfg" open><summary>Configurar o vídeo</summary><div id="vcfg" class="cfgform"></div></details>
        <div class="row" style="margin:12px 0"><label class="small mut">Sua voz lendo o roteiro (opcional) <input id="vfile" type="file" accept=".wav,.mp3,.m4a,.ogg"></label><button id="vup" class="sm">Enviar áudio</button>
          <label class="small mut">Música de fundo (opcional) <input id="mfile2" type="file" accept=".wav,.mp3,.m4a,.ogg"></label><button id="mup2" class="sm">Enviar música</button>
          <span class="grow"></span><button id="vgo" class="pri">Gerar vídeo</button></div>
        <div id="vbox" style="margin-top:12px"></div></div>
      <div class="card" id="kcard" hidden><div class="card-h"><h2>Kit pronto</h2><span id="kchip" class="chip"></span></div>
        <ul id="kcheck" class="check"></ul>
        <div class="row" style="margin:12px 0"><div class="seg" role="group" aria-label="Prévia"><button data-pv="ml" aria-pressed="true">Prévia Mercado Livre</button><button data-pv="shopee" aria-pressed="false">Prévia Shopee</button></div>
          <span class="grow"></span><a id="kzip" class="btn" href="#">Baixar kit (.zip)</a><button id="kok" class="pri">Confirmar kit</button></div>
        <div id="kprev"></div></div>
      <div class="card" id="mlcard" hidden><div class="card-h"><h2>Publicar no Mercado Livre</h2><span id="mlchip" class="chip"></span></div>
        <p id="mlstate" class="small mut" style="margin:0 0 12px"></p>
        <div id="mlform" class="form" hidden>
          <label>Categoria (busca pelo título)<div class="row"><input id="mlq" style="flex:1"><button id="mlsearch">Buscar categorias</button></div></label>
          <div id="mlcats"></div><div id="mlattrs" class="form"></div>
          <label>Quantidade disponível (a peça é feita sob encomenda; o ML exige pelo menos 1)<input id="mlqty" type="number" min="1" max="50" value="5"></label>
          <div class="row"><button id="mlval">Validar no Mercado Livre</button><button id="mlpub" class="pri">Publicar</button></div>
        </div></div>
      <div class="card" id="shcard" hidden><div class="card-h"><h2>Publicar na Shopee</h2><span id="shchip" class="chip"></span></div>
        <p id="shstate" class="small mut" style="margin:0 0 12px"></p>
        <div class="row" style="margin-top:12px"><input id="shurl" type="url" placeholder="Link do anúncio na Shopee (opcional)" style="flex:1;height:40px"><button id="shdone">Marquei como publicado</button></div></div>`,
    bind: () => {
      const id = () => +route[1];
      const mlargs = () => ({id: id(), category_id: (document.querySelector('[name=mlcat]:checked') || {}).value,
        attributes: Object.fromEntries([...document.querySelectorAll('[data-attr]')].map(i => [i.dataset.attr, i.value])), quantity: $('mlqty').value});
      const sites = () => [...document.querySelectorAll('[data-msite]')].filter(x => x.checked).map(x => x.dataset.msite);
      $('msgo').onclick = async () => { const r = await post('/api/model/search', {id: id(), q: $('msq').value, profile: $('profile').value, sites: sites(), headless: !$('mshow').checked});
        if (r.error) return toast(r.error); pollModel(id()); };
      $('mterms').onclick = async () => { const c = S.candidates.find(x => String(x.id) === route[1]); $('mterms').disabled = true; $('mchips').textContent = 'Pensando…';
        const r = await post('/api/model/suggest', {title: c.title}); $('mterms').disabled = false;
        $('mchips').innerHTML = r.error ? esc(r.error) : r.terms.map(t => `<button class="sm ghost" data-term="${esc(t)}">${esc(t)}</button>`).join(''); };
      $('mchips').onclick = e => { const b = e.target.closest('[data-term]'); if (b) { $('msq').value = b.dataset.term; $('msgo').click(); } };
      $('msres').onclick = async e => {
        const f = e.target.closest('[data-mfile]'), g = e.target.closest('[data-mpick]'); const job = MJOB.results || [];
        if (f) { const it = job[+f.dataset.i]; const r = await post('/api/model/get', {id: id(), model_id: it.id, file_id: f.dataset.mfile, title: it.title, url: it.url, license: it.license, thumb: it.thumb, author: it.author, downloads: it.downloads, likes: it.likes, q: MJOB.q || $('msq').value, file_size: +f.dataset.fsize || null});
          toast(r.error || 'Modelo baixado e guardado'); load(); return; }
        if (g) { const it = job[+g.dataset.mpick];
          if (it.source === 'printables') { const box = $('mf' + g.dataset.mpick); box.textContent = 'Carregando arquivos…';
            const fl = await (await fetch('/api/model/files?model_id=' + it.id)).json();
            box.innerHTML = fl.error ? esc(fl.error) : fl.length ? fl.map(x => `<div class="row small"><span class="grow">${esc(x.name)} · ${x.size ? Math.round(x.size / 1024).toLocaleString('pt-BR') + ' KB' : ''}</span><button class="sm pri" data-mfile="${esc(x.id)}" data-fsize="${x.size || ''}" data-i="${g.dataset.mpick}">Usar este arquivo</button></div>`).join('') : 'Esse modelo não tem arquivo .stl; abra a página e baixe o .3mf.';
            return; }
          const r = await post('/api/model/capture', {id: id(), url: it.url, profile: $('profile').value, license: it.license, source: it.source});
          toast(r.error || 'Chrome aberto: clique em Baixar na página do modelo'); if (!r.error) pollModel(id()); } };
      $('vup').onclick = () => { const f = $('vfile').files[0]; if (!f) return toast('Escolha o arquivo de áudio');
        fetch(`/api/voice/upload?id=${id()}&name=${encodeURIComponent(f.name)}`, {method:'POST', body:f}).then(r => r.json()).then(r => { toast(r.error || 'Áudio enviado. Gere o vídeo de novo.'); load(); }); };
      $('vgo').onclick = async () => { const sv = await post('/api/media/config', {video: cfgRead('v', VID_FIELDS)}); if (sv.error) return toast(sv.error);
        const r = await post('/api/video', {id: id()}); toast(r.error || 'Gerando o vídeo…'); load(); };
      $('shdone').onclick = async () => { const r = await post('/api/shopee/done', {id: id(), url: $('shurl').value}); toast(r.error || 'Marcado como publicado'); load(); };
      $('mlsearch').onclick = async () => { const r = await (await fetch('/api/ml/categories?q=' + encodeURIComponent($('mlq').value))).json();
        $('mlcats').innerHTML = r.error ? `<p class="small" style="color:var(--red)">${esc(r.error)}</p>` : r.map((c, i) => `<label class="row" style="flex-direction:row;gap:8px;color:var(--fg);font-size:14px"><input type="radio" name="mlcat" value="${esc(c.category_id)}" ${i ? '' : 'checked'}> ${esc(c.name || c.domain)} <span class="mut small">${esc(c.category_id)}</span></label>`).join('');
        if (!r.error) $('mlcats').querySelector('input').dispatchEvent(new Event('change', {bubbles: true})); };
      $('mlcats').onchange = async () => { const cat = (document.querySelector('[name=mlcat]:checked') || {}).value; if (!cat) return;
        const a = await (await fetch('/api/ml/attributes?q=' + cat)).json(); const cand = S.candidates.find(x => String(x.id) === route[1]);
        $('mlattrs').innerHTML = a.error ? `<p class="small" style="color:var(--red)">${esc(a.error)}</p>` : a.map(x => `<label>${esc(x.name)} (${esc(x.id)})<input data-attr="${esc(x.id)}" list="dl-${esc(x.id)}" value="${x.id === 'BRAND' ? 'Genérica' : x.id === 'MODEL' ? esc((cand.kit.title || '').slice(0, 40)) : ''}"><datalist id="dl-${esc(x.id)}">${x.values.map(v => `<option>${esc(v)}</option>`).join('')}</datalist></label>`).join(''); };
      $('mlval').onclick = async () => { const r = await post('/api/ml/validate', mlargs()); toast(r.error ? 'O ML recusou: ' + r.error : 'O Mercado Livre aceitou o anúncio'); };
      $('mlpub').onclick = async () => { const b = $('mlpub');
        if (!b.dataset.armed) { b.dataset.armed = 1; b.textContent = 'Clique de novo para publicar de verdade'; setTimeout(() => { delete b.dataset.armed; b.textContent = 'Publicar'; }, 6000); return; }
        delete b.dataset.armed; b.textContent = 'Publicando…'; const r = await post('/api/ml/publish', mlargs()); b.textContent = 'Publicar';
        toast(r.error ? 'Não publicou: ' + r.error : 'Publicado no Mercado Livre'); load(); };
      $('kok').onclick = async () => { const r = await post('/api/kit/confirm', {id: id()}); toast(r.error || 'Kit confirmado'); load(); };
      document.querySelectorAll('[data-pv]').forEach(b => b.onclick = () => { pv = b.dataset.pv; document.querySelectorAll('[data-pv]').forEach(x => x.setAttribute('aria-pressed', x === b)); update(); });
      $('icfg').innerHTML = presetBar('i', IMG_PRESETS) + cfgHtml('i', IMG_FIELDS) + '<fieldset class="views"><legend>Vistas (cada uma vira uma imagem)</legend><div id="iviews"></div></fieldset>';
      $('vcfg').innerHTML = presetBar('v', VID_PRESETS) + cfgHtml('v', VID_FIELDS);
      const applyPreset = (pre, fields, list, e) => { const b = e.target.closest(`[data-${pre}preset]`); if (!b) return; const p = list.find(x => x.k === b.dataset[pre + 'preset']);
        cfgFill(pre, fields, {...cfgRead(pre, fields), ...p.c}); if (p.c.views) document.querySelectorAll('[data-iview]').forEach(x => x.checked = p.c.views.includes(x.dataset.iview)); toast('Sugestão aplicada: ' + p.l + '. Clique em Gerar para usar.'); };
      $('icfg').onclick = e => applyPreset('i', IMG_FIELDS, IMG_PRESETS, e); $('vcfg').onclick = e => applyPreset('v', VID_FIELDS, VID_PRESETS, e);
      fetch('/api/media/config').then(r => r.json()).then(m => {
        $('iviews').innerHTML = Object.entries(m.options.views).map(([k, l]) => `<label class="chk"><input type="checkbox" data-iview="${k}"> ${esc(l)}</label>`).join('');
        cfgFill('i', IMG_FIELDS, m.render); cfgFill('v', VID_FIELDS, m.video);
        document.querySelectorAll('[data-iview]').forEach(x => x.checked = m.render.views.includes(x.dataset.iview)); });
      const imgCfg = () => ({...cfgRead('i', IMG_FIELDS), views: [...document.querySelectorAll('[data-iview]')].filter(x => x.checked).map(x => x.dataset.iview)});
      $('igo').onclick = async () => { const r = await post('/api/render', {id: id(), cfg: imgCfg()}); toast(r.error || 'Gerando imagens… leva alguns minutos'); load(); };
      $('ifup').onclick = () => { const f = $('ifoto').files[0]; if (!f) return toast('Escolha uma imagem');
        fetch(`/api/photo/upload?id=${id()}&name=${encodeURIComponent(f.name)}`, {method:'POST', body:f}).then(r => r.json()).then(r => { toast(r.error || 'Foto adicionada'); $('ifoto').value = ''; load(); }); };
      $('mup2').onclick = () => { const f = $('mfile2').files[0]; if (!f) return toast('Escolha o arquivo de música');
        fetch(`/api/music/upload?id=${id()}&name=${encodeURIComponent(f.name)}`, {method:'POST', body:f}).then(r => r.json()).then(r => { toast(r.error || 'Música enviada'); load(); }); };
      $('igal').onclick = async e => {
        const c = S.candidates.find(x => String(x.id) === route[1]); const b = e.target.closest('[data-g]'); if (!c || !b) return;
        const names = c.media.map(m => m.name), n = b.dataset.n; let hidden = c.media.filter(m => m.hidden).map(m => m.name);
        if (b.dataset.g === 'del') { const r = await post('/api/photo/delete', {id: c.id, name: n}); toast(r.error || 'Foto apagada'); return load(); }
        if (b.dataset.g === 'hide') hidden = hidden.includes(n) ? hidden.filter(x => x !== n) : [...hidden, n];
        else { const i = names.indexOf(n), j = i + (b.dataset.g === 'left' ? -1 : 1); if (j < 0 || j >= names.length) return; [names[i], names[j]] = [names[j], names[i]]; }
        const r = await post('/api/media/order', {id: c.id, order: names, hidden}); toast(r.error || 'Ordem salva'); load(); };
      $('tgen').onclick = async () => { const r = await post('/api/copy', {id: id()}); toast(r.error || 'Gerando o texto… leva cerca de 1 minuto'); load(); };
      $('ttitle').oninput = () => $('tcount').textContent = `(${$('ttitle').value.length}/60)`;
      $('tsave').onclick = async () => { const lines = t => t.split('\n').map(x => x.trim()).filter(Boolean);
        const r = await post('/api/kit', {id: id(), title: $('ttitle').value, description: $('tdesc').value, bullets: lines($('tbul').value),
          scripts: $('tscr').value.split(/\n\s*\n/).map(x => x.trim()).filter(Boolean), keywords: $('tkey').value.split(',').map(x => x.trim()).filter(Boolean)});
        toast(r.error || 'Texto salvo'); if (!r.error) { $('tcard').dataset.init = ''; } load(); };
      $('cpsave').onclick = async () => { const r = await post('/api/price', {id: id(), price: $('cprice').value}); toast(r.error || 'Preço salvo'); load(); };
      $('sgo').onclick = async () => { const r = await post('/api/slice', {id: id()}); toast(r.error || 'Fatiando… leva alguns segundos'); load(); };
      const run = async (p, ok) => { const r = await p; if (r.error) return toast(r.error); toast(ok); load(); };
      $('msave').onclick = () => run(post('/api/model', {id: id(), source_url: $('mlink').value, license_note: $('mlic').value}), 'Link e licença salvos');
      $('mup').onclick = () => { const f = $('mfile').files[0]; if (!f) return toast('Escolha um arquivo .3mf ou .stl');
        run(fetch(`/api/model/upload?id=${id()}&name=${encodeURIComponent(f.name)}`, {method:'POST', body:f}).then(r => r.json()), 'Modelo enviado'); };
      $('muse').onclick = () => run(post('/api/model/inbox', {id: id(), name: $('minbox').value}), 'Modelo copiado de inbox/');
      fetch('/api/inbox').then(r => r.json()).then(l => { $('minbox').innerHTML = l.length ? l.map(n => `<option>${esc(n)}</option>`).join('') : '<option value="">inbox/ está vazia</option>'; $('muse').disabled = !l.length; });
    },
    update: () => {
      const c = S.candidates.find(x => String(x.id) === route[1]);
      $('mcard').hidden = !c;
      $('prod').innerHTML = !c ? `<div class="card empty"><b>Produto não encontrado</b><a href="#/producao">Voltar para Produção</a></div>` :
        `<div class="crumb"><a href="#/producao">Produção</a> › ${esc(c.title)}</div>
         <div class="card"><div class="card-h"><h2>${esc(c.title)}</h2><a href="${esc(c.url)}" target="_blank" rel="noopener">Ver anúncio original</a></div>
           <div class="price">${price(c.price)}<span class="sold">+${c.sold} vendidos · ${c.reviews} avaliações</span></div>
           <div class="stepper">${stepper(c, 1)}</div>
           ${(() => { const [t, d, a, k] = nextAction(c); return `<div class="next ${k || ''}"><div class="grow"><b>${esc(t)}</b><div class="small">${esc(d)}</div></div>${a === 'auto' ? `<button class="pri" data-auto="${c.id}">${ic('refresh')}Rodar etapas automáticas</button>` : ''}</div>`; })()}</div>`;
      if (!c) return;
      $('ovcard').hidden = false; $('ovcard').innerHTML = overview(c);
      $('tlcard').hidden = false;
      const msgs = {slice: c.slice_msg, copy: c.copy_msg, images: c.images_msg, video: c.video_msg, shopee: ''};
      $('tline').innerHTML = `<ol class="tl">${S.steps.map(n => { const st = c.steps[n] || 'pending', t = (c.step_times || {})[n] || {}, own = c.publications[n];
        return `<li class="${esc(st)}" data-step="${n}" tabindex="0" role="button" aria-expanded="${OPEN.has(n)}"><span class="dotx"></span><div class="grow"><b>${esc(STEP_LABEL[n] || n)}</b> <span class="small mut tlmore">${OPEN.has(n) ? '▾ ocultar' : '▸ ver detalhes'}</span>
          <span class="chip ${esc(st)}">${STATUS_LABEL[st] || esc(st)}</span>${st === 'running' ? ' <span class="small mut">em andamento…</span>' : ''}
          <div class="small mut">${t.started ? 'começou ' + localTime(t.started) : ''}${t.seconds != null && t.seconds > 0 ? ' · levou ' + fmtDur(t.seconds) : ''}${own && own.url ? ` · <a href="${esc(own.url)}" target="_blank" rel="noopener">abrir anúncio</a>` : ''}</div>
          ${st === 'error' && msgs[n] ? `<div class="small" style="color:var(--red)">${esc(msgs[n])}</div>` : ''}
          ${OPEN.has(n) ? `<div class="tldet">${stepDetail(c, n)}</div>` : ''}</div></li>`; }).join('')}</ol>`;
      $('tline').onclick = e => { if (e.target.closest('a, video, .tldet')) return; const li = e.target.closest('li[data-step]'); if (!li) return;
        OPEN.has(li.dataset.step) ? OPEN.delete(li.dataset.step) : OPEN.add(li.dataset.step); VIEWS.produto.update(); };
      $('tline').onkeydown = e => { if (e.target.dataset && e.target.dataset.step && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); e.target.click(); } };
      const m = c.model || {}, hasFile = !!m.file_path;
      if (!$('msq').dataset.init) { $('msq').value = (c.title || '').split(' ').slice(0, 5).join(' '); $('msq').dataset.init = 1; pollModel(c.id); }
      if (!$('mlink').dataset.init) { $('mlink').value = m.source_url || ''; $('mlic').value = m.license_note || ''; $('mlink').dataset.init = 1; }
      $('mchip').className = 'chip ' + (hasFile ? 'ok' : 'pending'); $('mchip').textContent = hasFile ? 'Pronto' : 'Falta o arquivo';
      const ss = c.steps.slice || 'pending', sl = c.slice;
      $('scard').hidden = false;
      $('schip').className = 'chip ' + ss; $('schip').textContent = {pending:'Na fila', running:'Fatiando', ok:'Pronto', error:'Erro'}[ss] || ss;
      $('sgo').disabled = !hasFile || ss === 'running'; $('sgo').textContent = ss === 'ok' ? 'Fatiar de novo' : 'Fatiar agora';
      $('sstate').textContent = ss === 'error' ? c.slice_msg : sl ? `${Math.floor(sl.minutes / 60)} h ${sl.minutes % 60} min · ${sl.grams.toLocaleString('pt-BR', {minimumFractionDigits: 1, maximumFractionDigits: 1})} g de PLA (A1, bocal 0,4 mm, camada 0,20 mm, preenchimento padrão)`
        : hasFile ? 'Pronto para fatiar no perfil Bambu Lab A1, PLA, camada 0,20 mm.' : 'Envie o modelo 3D primeiro.';
      $('kcard').hidden = !c.kit;
      if (c.kit) {
        const names = {model:'Modelo 3D', slice:'Fatiamento', cost:'Custo e margem', copy:'Texto do anúncio', images:'Imagens'}, ok = n => c.steps[n] === 'ok';
        $('kcheck').innerHTML = Object.keys(names).map(n => `<li class="${ok(n) ? 'yes' : 'no'}">${ok(n) ? '✓' : '○'} ${names[n]}</li>`).join('');
        const ready = Object.keys(names).every(ok), done = c.steps.kit === 'ok';
        $('kchip').className = 'chip ' + (done ? 'ok' : ready ? 'running' : 'pending'); $('kchip').textContent = done ? 'Confirmado' : ready ? 'Falta confirmar' : 'Faltam etapas';
        $('kok').disabled = !ready || done; $('kzip').href = `/api/kit/${c.id}.zip`;
        const k = c.kit, im = c.images.map(n => `/products/${c.id}/renders/${n}`), pr = c.target_price;
        $('kprev').innerHTML = `<div class="preview ${pv}"><div class="pgal">${im[0] ? `<img class="big" src="${im[0]}" alt="">` : '<div class="big"></div>'}<div class="pth">${im.map(u => `<img src="${u}" alt="">`).join('')}</div></div>
          <div class="pinfo"><small>Novo · feito sob encomenda</small><h3>${esc(k.title)}</h3><div class="price">${price(pr)}</div>
            <ul>${k.bullets.map(b => `<li>${esc(b)}</li>`).join('')}</ul><button class="buy" disabled>${pv === 'ml' ? 'Comprar agora' : 'Comprar'}</button></div>
          <div class="pdesc"><h4>Descrição</h4><p>${esc(k.description).replace(/\n/g, '<br>')}</p></div></div>`;
      }
      $('vcard').hidden = !c.images.length || !c.kit;
      const vs = c.steps.video || 'pending';
      $('vchip').className = 'chip ' + vs; $('vchip').textContent = {pending:'Falta gerar', running:'Gerando', ok:'Pronto', error:'Erro'}[vs] || vs;
      $('vgo').disabled = vs === 'running';
      $('vstate').textContent = vs === 'error' ? c.video_msg : vs === 'ok' ? `Vídeo pronto, ${c.video_msg}.` : 'Usa as imagens visíveis, na ordem acima, com a legenda do primeiro roteiro. Com o áudio da sua voz, cada imagem dura o mesmo tempo.' + (c.has_voice ? ' Voz enviada.' : '') + (c.has_music ? ' Música enviada.' : '');
      if (vs === 'ok' && $('vbox').dataset.k !== c.video_msg + c.has_voice) { $('vbox').dataset.k = c.video_msg + c.has_voice; $('vbox').innerHTML = `<video src="/products/${c.id}/kit/video.mp4?t=${Date.now()}" controls style="max-height:420px;border-radius:6px"></video>`; }
      $('shcard').hidden = c.steps.kit !== 'ok';
      const sh = c.steps.shopee || 'pending', shp = c.publications.shopee;
      $('shchip').className = 'chip ' + (shp ? 'ok' : sh); $('shchip').textContent = shp ? 'Publicado' : {pending:'Falta publicar', error:'Erro'}[sh] || sh;
      $('shstate').innerHTML = shp ? `Marcado como publicado${shp.url ? `: <a href="${esc(shp.url)}" target="_blank" rel="noopener">${esc(shp.url)}</a>` : ''}`
        : 'Cadastre o produto na Central do Vendedor da Shopee com o kit (botão Baixar kit, no cartão Kit pronto): título, descrição, preço e imagens. Depois cole o link aqui e marque como publicado.';
      $('mlcard').hidden = c.steps.kit !== 'ok';
      if (c.steps.kit === 'ok') {
        const pub = c.publications.ml;
        if (!$('mlq').value) $('mlq').value = c.kit.title;
        fetch('/api/ml/status').then(r => r.json()).then(m => {
          if (!$('mlchip')) return;  // saiu da página enquanto a resposta vinha
          $('mlchip').className = 'chip ' + (pub ? 'ok' : m.connected ? 'running' : 'blocked'); $('mlchip').textContent = pub ? 'Publicado' : m.connected ? 'Conta conectada' : m.configured ? 'Falta conectar' : 'Falta configurar';
          $('mlform').hidden = !m.connected || !!pub;
          $('mlstate').innerHTML = pub ? `Publicado: <a href="${esc(pub.url)}" target="_blank" rel="noopener">${esc(pub.external_id)}</a>` : m.connected ? 'Escolha a categoria, valide e publique. Nada vai ao ar sem o seu segundo clique.'
            : 'Antes de publicar, conecte sua conta em <a href="#/config">Configurações</a> (App ID, Secret Key e login).'; });
      }
      $('icard').hidden = !hasFile && !c.media.length;
      const is = c.steps.images || 'pending';
      $('ichip').className = 'chip ' + is; $('ichip').textContent = {pending:'Falta gerar', running:'Gerando', ok:'Pronto', error:'Erro'}[is] || is;
      $('igo').disabled = is === 'running'; $('igo').textContent = c.images.length ? 'Gerar de novo' : 'Gerar imagens';
      $('istate').textContent = is === 'error' ? c.images_msg : is === 'running' ? 'O Blender está renderizando as vistas escolhidas. Pode levar alguns minutos; a qualidade Rápida leva cerca de 1.'
        : c.media.length ? 'Renders são imagens do modelo 3D, não fotos da peça impressa. Mude a configuração e gere de novo, ou envie fotos suas.' : 'Gera uma imagem por vista a partir do modelo 3D, ou envie fotos suas.';
      const gal = c.media.map(m => m.name + m.hidden).join('|');
      if ($('igal').dataset.k !== gal + is + c.id) { $('igal').dataset.k = gal + is + c.id;
        $('igal').innerHTML = c.media.map((m, i) => `<div class="gi ${m.hidden ? 'off' : ''}"><a href="/products/${c.id}/renders/${m.name}" target="_blank" rel="noopener"><img src="/products/${c.id}/renders/${m.name}?t=${Date.now()}" alt="${esc(m.name)}" loading="lazy"></a>
          <div class="gctl"><span class="small">${i === 0 && !m.hidden ? 'Principal' : m.name.startsWith('photo') ? 'Sua foto' : 'Render'}</span>
            <button class="sm ghost" data-g="left" data-n="${m.name}" title="Mover para antes" ${i ? '' : 'disabled'}>←</button><button class="sm ghost" data-g="right" data-n="${m.name}" title="Mover para depois" ${i < c.media.length - 1 ? '' : 'disabled'}>→</button>
            <button class="sm ghost" data-g="hide" data-n="${m.name}">${m.hidden ? 'Mostrar' : 'Ocultar'}</button>${m.name.startsWith('photo') ? `<button class="sm ghost danger" data-g="del" data-n="${m.name}">Apagar</button>` : ''}</div></div>`).join(''); }
      $('tcard').hidden = !c.margin;
      const ts = c.steps.copy || 'pending';
      $('tchip').className = 'chip ' + ts; $('tchip').textContent = {pending:'Falta gerar', running:'Gerando', ok:'Pronto', error:'Erro'}[ts] || ts;
      $('tgen').disabled = ts === 'running'; $('tgen').textContent = c.kit ? 'Gerar de novo com Claude' : 'Gerar com Claude';
      $('tstate').textContent = ts === 'error' ? c.copy_msg : c.kit ? 'Edite o que quiser e clique em Salvar edições.' : 'O Claude escreve título, descrição, bullets e roteiros com os dados do produto. Preencha o nome da loja, as cores e as medidas em Configurações antes.';
      if (c.kit && !$('tcard').dataset.init) { const k = c.kit; $('ttitle').value = k.title; $('tdesc').value = k.description; $('tbul').value = k.bullets.join('\n');
        $('tscr').value = k.scripts.join('\n\n'); $('tkey').value = k.keywords.join(', '); $('tcard').dataset.init = 1; $('ttitle').oninput(); }
      $('ccard').hidden = !c.margin;
      if (c.margin) {
        if (!$('cprice').dataset.init) { $('cprice').value = c.target_price; $('cprice').dataset.init = 1; }
        $('cchip').className = 'chip ' + (c.costs_confirmed ? 'ok' : 'blocked'); $('cchip').textContent = c.costs_confirmed ? 'Custos confirmados' : 'Custos provisórios';
        const M = c.margin, row = (l, f) => `<tr><td>${l}</td><td class="num">${f(M.ml)}</td><td class="num">${f(M.shopee)}</td></tr>`;
        $('cstate').innerHTML = `Com base em ${Math.floor(c.slice.minutes / 60)} h ${c.slice.minutes % 60} min e ${c.slice.grams.toLocaleString('pt-BR', {minimumFractionDigits: 1, maximumFractionDigits: 1})} g. ${c.costs_confirmed ? '' : 'Os custos ainda são estimativas: <a href="#/config">ajuste em Configurações</a>.'}`;
        $('ctab').innerHTML = `<thead><tr><th></th><th>Mercado Livre</th><th>Shopee</th></tr></thead><tbody>` +
          row('Produção (filamento, máquina, energia)', m => brl(m.producao)) + row('Garantia de reimpressão', m => brl(m.garantia)) +
          row('Embalagem', m => brl(m.embalagem)) + row('Frete do vendedor', m => brl(m.frete)) + row('Comissão e taxas', m => brl(m.taxas)) +
          row('<b>Lucro por peça</b>', m => `<b style="color:${m.lucro > 0 ? 'var(--green)' : 'var(--red)'}">${brl(m.lucro)}</b>`) +
          row('<b>Margem</b>', m => `<b>${m.margem_pct.toLocaleString('pt-BR', {minimumFractionDigits: 1, maximumFractionDigits: 1})}%</b>`) + row('Preço mínimo para a margem alvo', m => m.preco_minimo ? brl(m.preco_minimo) : '—') + '</tbody>';
      }
      $('mstate').textContent = hasFile ? `Arquivo: ${m.file_path.split('/').pop()}` : 'Cole o link do modelo, anote a licença e envie o arquivo. A etapa fica pronta quando o arquivo chega.';
    },
  },
};
Object.assign(VIEWS, VIEWS_EXTRA);  // Resumo e Ajuda vêm de resumo.js
let pendingStore = '', armed = {id: 0, until: 0};
const date = ts => ts ? String(ts).slice(0, 10).split('-').reverse().join('/') : '—';
const storeName = s => s.name || shortUrl(s.url).slice(0, 40);
const img = c => c.image || c.thumb ? `<img class="thumb" src="${c.image ? '/images/' + c.id : esc(c.thumb)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : '<div class="thumb"></div>';
function catalog() {
  const q = $('q').value.toLowerCase(), st = $('pstore').value;
  const key = {score:c => -c.score, growth:c => -(c.growth * 1000 + c.sold_growth), sold:c => -c.sold, pa:c => c.price ?? 1e9, pd:c => -(c.price ?? 0),
    recent:c => -Date.parse(String(c.last_seen).replace(' ', 'T') + 'Z'), manual:c => { const i = DND.load('products').indexOf(String(c.id)); return i < 0 ? 1e9 : i; }}[$('sort').value];
  return S.candidates.filter(c => (!st || String(c.store_id) === st) && (filter === 'all' || c.status === filter)
      && (!q || (c.title || '').toLowerCase().includes(q) || (c.store_name || '').toLowerCase().includes(q))).sort((a, b) => key(a) - key(b));
}
// crescimento entre a 1ª e a última leitura, com a data da 1ª e uma minilinha das avaliações
const spark = h => { const lo = Math.min(...h), span = Math.max(...h) - lo || 1;
  return `<svg width="64" height="20" viewBox="0 0 64 20" aria-hidden="true"><polyline fill="none" stroke="currentColor" stroke-width="1.5" points="${h.map((v, i) => `${(i / (h.length - 1) * 62 + 1).toFixed(1)},${(18 - (v - lo) / span * 16).toFixed(1)}`).join(' ')}"/></svg>`; };
const growthInfo = c => c.snapshots < 2 ? '<span>lido uma vez, sem histórico ainda</span>'
  : `<span style="color:${c.growth > 0 || c.sold_growth > 0 ? 'var(--green)' : 'inherit'}"><b>+${num(c.growth)}</b> avaliações · <b>+${num(c.sold_growth)}</b> vendidos desde ${esc(String(c.since).slice(0, 10).split('-').reverse().join('/'))} ${spark(c.history)}</span>`;
const OPEN = new Set();  // etapas abertas na linha do tempo (sobrevive às atualizações da tela)
const link = (u, t) => u ? `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(t || u)}</a>` : '—';
const kv = rows => `<dl class="kv">${rows.filter(r => r[1] != null && r[1] !== '').map(([k, v, raw]) => `<dt>${k}</dt><dd>${raw ? v : esc(v)}</dd>`).join('')}</dl>`;
const mdur = m => `${Math.floor(m / 60)} h ${m % 60} min`;
const pct = v => v.toLocaleString('pt-BR', {maximumFractionDigits: 1}) + '%';
// o que a etapa fez, com os dados exatos que ela usou ou gerou
function stepDetail(c, n) {
  const m = c.model || {}, mi = m.info || {}, sl = c.slice, k = c.kit, t = (c.step_times || {})[n] || {}, pub = c.publications || {}, M = c.margin;
  const when = kv([['Começou', localTime(t.started)], ['Última mudança', localTime(t.ts)], ['Duração', t.seconds > 0 ? fmtDur(t.seconds) : '']]);
  const ad = `<div class="adbox">${img(c)}<div><b>${esc(c.title)}</b><div class="small mut">${esc(c.store_name || '')} · ${c.material ? esc(c.material.replace(/^[:\s]+/, '')) + ' · ' : ''}${price(c.price)} · +${num(c.sold)} vendidos · ${num(c.reviews)} avaliações</div>
    <div class="small">${link(c.url, 'Abrir o anúncio original no Mercado Livre')}</div></div></div>`;
  if (n === 'model') return ad + (m.file_path ? `<div class="adbox">${mi.thumb ? `<img class="thumb" src="${esc(mi.thumb)}" alt="" referrerpolicy="no-referrer">` : '<div class="thumb"></div>'}<div><b>${esc(mi.title || m.file_path.split('/').pop())}</b>
    <div class="small">${link(m.source_url, 'Abrir a página do modelo')}</div></div></div>` + kv([['Fonte', mi.source], ['Autor', mi.author], ['Downloads', mi.downloads != null ? num(mi.downloads) : ''], ['Curtidas', mi.likes != null ? num(mi.likes) : ''],
      ['Licença', m.license_note], ['Arquivo baixado', mi.file], ['Guardado em', m.file_path], ['Adicionado', localTime(m.added_at)]]) + when : '<div class="small mut">Ainda sem modelo. Busque no cartão “Modelo 3D” abaixo.</div>');
  if (n === 'slice') return sl ? kv([['Tempo de impressão', mdur(sl.minutes)], ['Filamento', sl.grams.toLocaleString('pt-BR', {minimumFractionDigits: 1}) + ' g de PLA'], ['Perfil', 'Bambu Lab A1, bocal 0,4 mm, camada 0,20 mm'],
    ['Modelo fatiado', m.file_path], ['G-code', c.slice_file]]) + when : '<div class="small mut">Ainda não fatiado.</div>';
  if (n === 'cost') return M ? kv([['Preço do anúncio', brl(c.target_price)], ['Custos', c.costs_confirmed ? 'confirmados' : 'provisórios (estimativas)'], ['Base', sl ? `${mdur(sl.minutes)} e ${sl.grams} g` : ''],
    ['Mercado Livre', `produção ${brl(M.ml.producao)} · taxas ${brl(M.ml.taxas)} · lucro ${brl(M.ml.lucro)} (${pct(M.ml.margem_pct)})`],
    ['Shopee', `produção ${brl(M.shopee.producao)} · taxas ${brl(M.shopee.taxas)} · lucro ${brl(M.shopee.lucro)} (${pct(M.shopee.margem_pct)})`]]) + when : '<div class="small mut">Depende do fatiamento.</div>';
  if (n === 'copy') return k ? kv([['Título', k.title], ['Descrição', esc(k.description).replace(/\n/g, '<br>'), 1], ['Bullets', '<ul>' + k.bullets.map(b => `<li>${esc(b)}</li>`).join('') + '</ul>', 1],
    ['Palavras-chave', k.keywords.join(', ')], ['Roteiros', k.scripts.map(x => esc(x)).join('<br><br>'), 1]]) + when : `<div class="small mut">${esc(c.copy_msg) || 'Texto ainda não gerado.'}</div>`;
  if (n === 'images') return (c.media.length ? `<div class="gal">${c.media.map(x => `<a href="/products/${c.id}/renders/${x.name}" target="_blank" rel="noopener"><img src="/products/${c.id}/renders/${x.name}" alt="" loading="lazy"></a>`).join('')}</div>`
    + kv([['Imagens', c.media.length + (c.images.length !== c.media.length ? ` (${c.images.length} visíveis)` : '')]]) : `<div class="small mut">${esc(c.images_msg) || 'Imagens ainda não geradas.'}</div>`) + when;
  if (n === 'kit') return kv([['Situação', c.steps.kit === 'ok' ? 'Confirmado' : 'Ainda não confirmado'], ['Título', k && k.title], ['Imagens', c.images.length]]) + when;
  if (n === 'video') return (c.steps.video === 'ok' ? `<video src="/products/${c.id}/kit/video.mp4" controls style="max-width:100%;max-height:320px;border-radius:6px"></video>` : '')
    + kv([['Resultado', c.video_msg], ['Voz', c.has_voice ? 'enviada' : 'sem voz'], ['Música', c.has_music ? 'enviada' : 'sem música']]) + when;
  const p = pub[n]; return kv([['Anúncio publicado', p ? link(p.url, p.url || p.external_id) : 'ainda não publicado', 1], ['Código', p && p.external_id]]) + when;
}
// avisos do produto: tudo o que merece atenção antes de publicar de verdade (no teste do app, só informam)
function warnings(c) {
  const w = [], m = c.model || {}, sl = c.slice, M = c.margin;
  if (!m.file_path) w.push(['Sem modelo 3D', 'Busque e escolha um modelo no cartão “Modelo 3D” abaixo.']);
  if (m.license_note && /NÃO permite uso comercial/.test(m.license_note)) w.push(['A licença do modelo não permite uso comercial', 'Para vender, troque por um modelo com licença comercial ou peça permissão ao autor.']);
  else if (m.file_path && m.license_note && /licença não informada|confira o uso/.test(m.license_note)) w.push(['Confira a licença do modelo', 'A página do modelo não deixou claro se o uso comercial é permitido.']);
  if (sl && sl.minutes > 240) w.push(['A impressão passa de 4 h', `Está em ${mdur(sl.minutes)}. O plano pede até 4 h por peça; peças longas travam a impressora e encarecem o produto.`]);
  if (sl && sl.grams > 120) w.push(['O filamento passa de 120 g', `Está em ${sl.grams.toLocaleString('pt-BR')} g, acima do limite do plano.`]);
  if (M && M.ml.lucro < 0) w.push(['No preço atual cada peça dá prejuízo', `Preço ${brl(c.target_price)}, lucro ${brl(M.ml.lucro)} por peça no Mercado Livre. Preço mínimo para a margem alvo: ${M.ml.preco_minimo ? brl(M.ml.preco_minimo) : '—'}. Sem problema para testar o app; ajuste antes de publicar de verdade.`]);
  else if (M && M.ml.preco_minimo && c.target_price < M.ml.preco_minimo) w.push(['Margem abaixo da meta', `Preço mínimo para a margem alvo: ${brl(M.ml.preco_minimo)}.`]);
  if (M && !c.costs_confirmed) w.push(['Custos provisórios', 'Os custos usados são estimativas. Confirme em Configurações para a margem valer.']);
  if (c.images.length && c.steps.images === 'ok') w.push(['As imagens são renders, não fotos da peça', 'O Mercado Livre pede foto fiel ao produto; troque por uma foto real depois da primeira peça impressa.']);
  return w;
}
// o produto de relance: anúncio de origem, modelo escolhido (exatamente qual), números e texto
function overview(c) {
  const m = c.model || {}, mi = m.info || {}, sl = c.slice, M = c.margin, k = c.kit, ms = c.msearch || {};
  const btn = (u, t, chrome) => `<button class="sm ghost" data-open="${esc(u)}" ${chrome ? 'data-chrome="1"' : ''}>${t}</button>`;
  const ws = warnings(c);
  return `${ws.length ? `<div class="warns"><b>Atenção (${ws.length})</b><ul>${ws.map(([t, d]) => `<li><b>${esc(t)}.</b> ${esc(d)}</li>`).join('')}</ul></div>` : '<div class="warns ok"><b>Sem avisos neste produto.</b></div>'}
  <div class="ov">
    <section><h3>Anúncio de origem</h3>${img(c)}<b class="ovt">${esc(c.title)}</b>
      <div class="small mut">${esc(c.store_name || '')}${c.material ? ' · ' + esc(c.material.replace(/^[:\s]+/, '')) : ''}</div>
      <div class="small">${price(c.price)} · +${num(c.sold)} vendidos · ${num(c.reviews)} avaliações</div>
      <div class="row">${btn(c.url, 'Abrir no navegador')}${btn(c.url, 'Abrir no Chrome do app', 1)}</div></section>
    <section><h3>Modelo 3D</h3>${m.file_path ? `${mi.thumb ? `<img class="thumb big" src="${esc(mi.thumb)}" alt="" referrerpolicy="no-referrer">` : '<div class="thumb big"></div>'}
      <b class="ovt">${esc(mi.title || m.file_path.split('/').pop())}</b>
      <div class="small mut">${[mi.source, mi.author && 'por ' + mi.author, mi.downloads != null && num(mi.downloads) + ' downloads', mi.likes != null && num(mi.likes) + ' curtidas'].filter(Boolean).map(esc).join(' · ')}</div>
      <div class="small">Arquivo: <b>${esc(mi.file || m.file_path.split('/').pop())}</b>${mi.file_size ? ' · ' + Math.round(mi.file_size / 1024).toLocaleString('pt-BR') + ' KB' : ''}</div>
      ${mi.query ? `<div class="small mut">Buscado como “${esc(mi.query)}”</div>` : ''}
      <div class="small">${esc(m.license_note || 'Licença não anotada')}</div>
      <div class="row">${m.source_url ? btn(m.source_url, 'Abrir página do modelo') + btn(m.source_url, 'No Chrome do app', 1) : ''}<button class="sm pri" data-swap>Trocar modelo</button></div>`
      : `<div class="small mut">Nenhum modelo escolhido ainda.</div><div class="row"><button class="sm pri" data-swap>Buscar modelo</button></div>`}
      ${ms.q ? `<div class="small mut">Última busca: “${esc(ms.q)}”, ${(ms.results || []).length} resultados${ms.at ? ' em ' + localTime(String(ms.at).replace('T', ' ')) : ''}</div>` : ''}</section>
    <section><h3>Impressão e custo</h3>${sl ? kv([['Tempo', mdur(sl.minutes)], ['Filamento', sl.grams.toLocaleString('pt-BR', {minimumFractionDigits: 1}) + ' g'], ['Preço-alvo', brl(c.target_price)],
      ['Lucro (ML)', M ? `<b style="color:${M.ml.lucro > 0 ? 'var(--green)' : 'var(--red)'}">${brl(M.ml.lucro)} (${pct(M.ml.margem_pct)})</b>` : '', 1], ['Lucro (Shopee)', M ? `${brl(M.shopee.lucro)} (${pct(M.shopee.margem_pct)})` : '']]) : '<div class="small mut">Ainda não fatiado.</div>'}</section>
    <section><h3>Texto do anúncio</h3>${k ? `<b class="ovt">${esc(k.title)}</b><div class="small ovd">${esc(k.description).replace(/\n+/g, '<br>')}</div>
      <ul class="small">${k.bullets.map(b => `<li>${esc(b)}</li>`).join('')}</ul>` : '<div class="small mut">Texto ainda não gerado.</div>'}
      ${c.images.length ? `<div class="gal">${c.images.slice(0, 4).map(n => `<a href="/products/${c.id}/renders/${n}" target="_blank"><img src="/products/${c.id}/renders/${n}" alt="" loading="lazy"></a>`).join('')}</div>` : ''}</section>
  </div>`;
}
const STEP_CARD = {model:'mcard', slice:'scard', cost:'ccard', copy:'tcard', images:'icard', kit:'kcard', ml:'mlcard', shopee:'shcard', video:'vcard'};
const stepper = (c, nav) => S.steps.map(n => { const s = c.steps[n] || 'pending';
  return nav ? `<a class="st ${esc(s)}" href="#" data-goto="${STEP_CARD[n] || ''}" title="${STATUS_LABEL[s] || s}. Clique para ir até esta etapa.">${STEP_LABEL[n] || n}</a>`
    : `<div class="st ${esc(s)}" title="${STATUS_LABEL[s] || s}">${STEP_LABEL[n] || n}</div>`; }).join('');

// o que fazer agora neste produto: [título, explicação, ação?]
function nextAction(c) {
  const st = n => c.steps[n], au = c.auto || {};
  if (!(c.model || {}).file_path) return ['Passo 1: ache o modelo 3D', 'Busque nos sites do cartão "Modelo 3D" e escolha um arquivo, ou envie o seu .3mf ou .stl.'];
  if (au.status === 'running' || Object.values(c.steps).includes('running')) return [au.msg || 'Trabalhando…', 'Pode deixar esta tela aberta. O Blender e o fatiador demoram alguns minutos.', '', 'run'];
  if (au.status === 'error') return ['Parou: ' + au.msg, 'Corrija o que a mensagem diz e rode de novo.', 'auto'];
  if (['slice', 'copy', 'images'].some(n => st(n) !== 'ok')) return ['Passo 2: rodar as etapas automáticas', 'O app fatia o modelo, escreve o texto com o Claude e gera as imagens. Você não precisa clicar em mais nada.', 'auto'];
  if (st('kit') !== 'ok') return ['Passo 3: revisar e confirmar o kit', 'Confira o texto, o preço e as imagens abaixo e clique em Confirmar kit.'];
  if (!c.publications.ml && !c.publications.shopee) return ['Passo 4: publicar', 'Publique no Mercado Livre pelo cartão abaixo, ou cadastre na Shopee pela Central do Vendedor, com o kit baixado. Nada vai ao ar sem o seu clique.'];
  return ['Produto publicado', 'Se quiser, gere o vídeo 9:16 no cartão de vídeo.'];
}
const IMG_FIELDS = [
  {k:'color', l:'Cor da peça', t:'color'},
  {k:'finish', l:'Acabamento', t:'select', o:{matte:'Fosco', gloss:'Brilhante', silk:'Seda (metálico suave)'}},
  {k:'background', l:'Fundo', t:'select', o:{white:'Branco (o ML exige na foto principal)', gray:'Cinza claro', warm:'Creme'}},
  {k:'light', l:'Iluminação', t:'select', o:{soft:'Suave', normal:'Normal', strong:'Forte'}},
  {k:'quality', l:'Qualidade', t:'select', o:{rapido:'Rápida (cerca de 1 min)', normal:'Normal', alta:'Alta (demora mais)'}},
  {k:'size', l:'Tamanho da imagem (px)', t:'number', min:600, max:2400, step:100},
  {k:'fill', l:'Enquadramento', t:'select', o:{perto:'Perto (peça grande)', medio:'Médio', longe:'Longe'}},
  {k:'turn', l:'Giro da peça (graus)', t:'number', min:0, max:345, step:15},
  {k:'shadow', l:'Sombra no chão', t:'check'}];
const VID_FIELDS = [
  {k:'format', l:'Formato', t:'select', o:{'9:16':'Vertical 9:16 (Reels, TikTok, Shopee)', '1:1':'Quadrado 1:1', '16:9':'Horizontal 16:9'}},
  {k:'seconds', l:'Segundos por imagem (sem voz)', t:'number', min:1, max:10, step:0.5},
  {k:'transition', l:'Transição', t:'select', o:{none:'Corte seco', fade:'Esmaecer'}},
  {k:'zoom', l:'Zoom lento nas imagens', t:'check'},
  {k:'captions', l:'Mostrar legenda do roteiro', t:'check'},
  {k:'caption_size', l:'Tamanho da legenda', t:'number', min:24, max:120, step:2},
  {k:'caption_pos', l:'Posição da legenda', t:'select', o:{bottom:'Embaixo', center:'No meio', top:'Em cima'}},
  {k:'caption_color', l:'Cor da legenda', t:'color'},
  {k:'caption_box', l:'Caixa escura atrás da legenda', t:'check'},
  {k:'background', l:'Cor de fundo', t:'color'},
  {k:'music', l:'Usar a música de fundo enviada', t:'check'},
  {k:'music_volume', l:'Volume da música (0 a 1)', t:'number', min:0, max:1, step:0.05},
  {k:'fps', l:'Quadros por segundo', t:'select', o:{24:'24 (cinema)', 30:'30 (padrão)', 60:'60 (fluido)'}},
  {k:'quality', l:'Qualidade do arquivo', t:'select', o:{rapido:'Rápida (arquivo menor)', normal:'Normal', alta:'Alta (maior)'}}];

const HINTS = {
  color: 'Combine com a cor que você tem em estoque; cinza e preto fotografam melhor.', finish: 'Fosco esconde as camadas; brilhante realça o volume.',
  background: 'Branco puro é o que o Mercado Livre exige na foto principal.', light: 'Suave evita brilho estourado em peças claras.',
  quality: 'Use Rápida para testar o enquadramento e Alta só no final.', size: '1200 px é suficiente para o Mercado Livre (mínimo 500).',
  shadow: 'A sombra no chão faz a peça parecer apoiada, não flutuando.', fill: 'Perto faz a peça ocupar mais da imagem.', turn: 'Gira a peça em volta do eixo vertical, para mostrar o lado mais bonito.',
  format: '9:16 serve para Reels, TikTok e Shopee Vídeo.', seconds: '3 a 4 s por imagem mantém o ritmo.', transition: 'Esmaecer suaviza a troca entre imagens.',
  zoom: 'Um zoom lento prende mais a atenção.', captions: 'A maioria assiste sem som: deixe a legenda ligada.', caption_size: '50 a 60 lê bem no celular.',
  caption_pos: 'Embaixo evita cobrir a peça.', caption_color: 'Escuro no fundo claro; claro com a caixa escura.', caption_box: 'A caixa dá leitura em qualquer fundo.',
  background_v: '', music: 'Envie uma música livre de direitos antes.', music_volume: '0,15 a 0,3 deixa a voz clara.', fps: '30 é o padrão; 24 dá aspecto de cinema e arquivo menor.', quality_v: 'Alta gera arquivo maior.'};
const IMG_PRESETS = [
  {k:'ml', l:'Mercado Livre (foto principal)', d:'Fundo branco puro, peça perto, luz normal: o padrão que o ML aceita.', c:{background:'white', finish:'matte', light:'normal', fill:'perto', shadow:true, quality:'normal', turn:0, views:['frente','lado','cima','tras']}},
  {k:'vitrine', l:'Vitrine (cinza suave)', d:'Fundo cinza claro e luz suave, 4 vistas. Bom para o carrossel.', c:{background:'gray', finish:'matte', light:'soft', fill:'medio', shadow:true, quality:'normal', turn:0, views:['frente','lado','cima','tras']}},
  {k:'destaque', l:'Destaque (brilho e detalhe)', d:'Acabamento seda, luz forte e um detalhe em zoom. Chama atenção no feed.', c:{background:'warm', finish:'silk', light:'strong', fill:'perto', shadow:true, quality:'alta', turn:0, views:['frente','detalhe','topo']}},
  {k:'teste', l:'Teste rápido', d:'Qualidade rápida e 2 vistas, para conferir o enquadramento em cerca de 1 min.', c:{quality:'rapido', size:800, views:['frente','topo']}}];
const VID_PRESETS = [
  {k:'reels', l:'Reels / TikTok', d:'Vertical, 3 s por imagem, esmaecer, zoom lento e legenda grande com caixa.', c:{format:'9:16', seconds:3, transition:'fade', zoom:true, captions:true, caption_size:60, caption_box:true, fps:30, quality:'normal'}},
  {k:'shopee', l:'Shopee Vídeo', d:'Vertical, 4 s por imagem, corte seco e legenda simples.', c:{format:'9:16', seconds:4, transition:'none', zoom:false, captions:true, caption_size:52, caption_box:false, fps:30, quality:'normal'}},
  {k:'feed', l:'Feed quadrado', d:'1:1, 3 s por imagem e zoom lento.', c:{format:'1:1', seconds:3, transition:'fade', zoom:true, captions:true, caption_size:48, fps:30, quality:'normal'}},
  {k:'rapido', l:'Teste rápido', d:'Qualidade rápida e 24 fps para gerar em poucos segundos.', c:{seconds:2, fps:24, quality:'rapido', zoom:false}}];
const presetBar = (pre, list) => `<div class="presets"><span class="small mut">Sugestões:</span> ${list.map(p => `<button type="button" class="sm ghost" data-${pre}preset="${p.k}" title="${esc(p.d)}">${esc(p.l)}</button>`).join('')}</div>`;
const cfgHtml = (pre, fields) => fields.map(f => `<label class="${f.t === 'check' ? 'chk' : ''}" title="${esc(HINTS[f.k === 'quality' && pre === 'v' ? 'quality_v' : f.k] || '')}">${f.t === 'check' ? '' : esc(f.l)}${
  f.t === 'select' ? `<select data-${pre}="${f.k}">${Object.entries(f.o).map(([v, t]) => `<option value="${esc(v)}">${esc(t)}</option>`).join('')}</select>`
  : f.t === 'check' ? `<input type="checkbox" data-${pre}="${f.k}"> ${esc(f.l)}`
  : `<input type="${f.t}" data-${pre}="${f.k}" ${f.min != null ? `min="${f.min}" max="${f.max}" step="${f.step}"` : ''}>`}<small class="hint">${esc(HINTS[f.k === 'quality' && pre === 'v' ? 'quality_v' : f.k] || '')}</small></label>`).join('');
const cfgFill = (pre, fields, v) => fields.forEach(f => { const el = document.querySelector(`[data-${pre}="${f.k}"]`); if (el) f.t === 'check' ? el.checked = !!v[f.k] : el.value = v[f.k]; });
const cfgRead = (pre, fields) => Object.fromEntries(fields.map(f => { const el = document.querySelector(`[data-${pre}="${f.k}"]`);
  return [f.k, f.t === 'check' ? el.checked : f.t === 'number' ? +el.value : el.value]; }));
let MJOB = {};
async function pollModel(lid) {
  clearTimeout(pollModel.t);
  const draw = () => { const m = $('msmsg'); if (!m) return;
    m.textContent = (MJOB.msg || '') + (MJOB.notes && MJOB.notes.length ? ' · ' + MJOB.notes.join(' · ') : '');
    const SRC = {printables:'Printables', makerworld:'MakerWorld', thingiverse:'Thingiverse'};
    const cur = (S.candidates.find(x => String(x.id) === String(route[1])) || {}).model || {};
    if (!$('mshow').dataset.init && MJOB.headless != null) { $('mshow').checked = !MJOB.headless; $('mshow').dataset.init = 1; }
    if (MJOB.q && !$('msq').dataset.q) { $('msq').dataset.q = 1; $('msq').value = MJOB.q; }
    $('msres').innerHTML = (MJOB.q && (MJOB.results || []).length ? `<div class="small mut" style="margin:4px 0">Resultados de “${esc(MJOB.q)}”${MJOB.headless ? ' (navegador oculto)' : ' (navegador visível)'}. Escolha outro para trocar o modelo.</div>` : '') + (MJOB.results || []).map((r, i) => `<div class="mr ${cur.source_url && r.url === cur.source_url ? 'cur' : ''}"><img class="thumb" src="${esc(r.thumb)}" alt="" loading="lazy" referrerpolicy="no-referrer">
      <div class="grow"><a class="title wrap" href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.title)}</a>${cur.source_url && r.url === cur.source_url ? ' <span class="chip ok">Em uso</span>' : ''} <button class="sm ghost" data-open="${esc(r.url)}">Abrir</button>
        <div class="meta"><span class="chip">${SRC[r.source] || esc(r.source)}</span>${r.author ? `<span>${esc(r.author)}</span>` : ''}${r.downloads != null ? `<span><b>${num(r.downloads)}</b> downloads</span>` : ''}
          ${r.license ? `<span class="chip ${r.commercial === false ? 'error' : r.commercial ? 'ok' : ''}" title="${esc(r.license)}">${r.commercial === false ? 'Sem uso comercial' : r.commercial ? 'Uso comercial ok' : 'Veja a licença'}</span>` : ''}</div>
        <div id="mf${i}" class="small"></div></div>
      <button class="sm ${r.source === 'printables' ? 'pri' : ''}" data-mpick="${i}">${r.source === 'printables' ? 'Escolher arquivo' : 'Abrir e baixar'}</button></div>`).join(''); };
  try { MJOB = await (await fetch('/api/model/search?id=' + lid)).json(); } catch (e) { return; }
  const open = $('msres') && [...document.querySelectorAll('#msres [id^=mf]')].some(x => x.innerHTML); if (!open) draw();
  if (MJOB.status === 'running') pollModel.t = setTimeout(() => pollModel(lid), 1500); else if (MJOB.status === 'done' && /guardado/.test(MJOB.msg)) load();
}

function go() {
  route = (location.hash.replace(/^#\//, '') || 'resumo').split('/');
  if (route[0] === 'revisar') { location.hash = '#/produtos'; return; }
  Tour.clear();  // trocar de tela fecha o balão da tela anterior
  const name = route[0] === 'producao' && route[1] ? 'produto' : (VIEWS[route[0]] ? route[0] : 'resumo');
  route.view = name;
  document.querySelectorAll('.side a').forEach(a => a.dataset.nav === route[0] ? a.setAttribute('aria-current', 'page') : a.removeAttribute('aria-current'));
  $('view').innerHTML = VIEWS[name].mount();
  VIEWS[name].bind?.();
  update();
  Tour.maybe(name);
}

function update() {
  if (DND.dragging) return;  // redesenhar no meio do arraste soltaria o cartão
  const sel = $('profile');
  if (sel.options.length !== S.profiles.length) {
    const saved = store('profile');
    sel.innerHTML = S.profiles.map(p => `<option ${p === saved ? 'selected' : ''}>${esc(p)}</option>`).join('');
  }
  const needs = S.stores.filter(s => s.status === 'captcha'), errs = S.stores.filter(s => s.status === 'error');
  const running = S.stores.find(s => s.status === 'running'), queued = S.stores.filter(s => s.status === 'pending').length;
  const toReview = S.candidates.filter(c => c.status === 'new').length;
  const st = $('status');
  const work = S.candidates.flatMap(c => S.steps.filter(n => c.steps[n] === 'running').map(n => `${STEP_LABEL[n] || n}: ${(c.title || '').slice(0, 28)}`));
  st.className = 'status ' + (needs.length ? 'need' : running || work.length ? 'run' : 'idle');
  st.title = work.join('\n');
  st.lastChild.textContent = needs.length ? 'Precisa de você' : running ? `Lendo loja · ${running.n} anúncios` + (queued ? ` · ${queued} na fila` : '')
    : work.length ? `Trabalhando · ${work[0]}` + (work.length > 1 ? ` (+${work.length - 1})` : '') : 'Parado';
  $('alerts').innerHTML =
    needs.map(s => `<div class="alert need"><span aria-hidden="true">⚠</span><div><b>${s.msg === 'login' ? 'Faça login no Mercado Livre' : 'Resolva o captcha no Chrome'}</b>
      Vá até a janela do Chrome aberta pelo app e ${s.msg === 'login' ? 'entre com a sua conta' : 'marque “Não sou um robô” ou conclua a etapa de segurança'}. A leitura de <i>${esc(shortUrl(s.url))}</i> continua sozinha.</div></div>`).join('') +
    (errs.length ? `<div class="alert err"><span aria-hidden="true">✕</span><div class="grow">
      <b>${errs.length === 1 ? '1 loja não foi lida' : errs.length + ' lojas não foram lidas'}</b>
      ${errs.map(s => `<div class="row small" style="margin-top:4px"><span class="grow">${esc(shortUrl(s.url))} · <span class="mut">${esc(errHint(s.msg))}</span></span>
        <button data-rerun="${esc(s.url)}">Tentar de novo</button></div>`).join('')}</div></div>` : '');
  const badge = (id, n) => { $(id).hidden = !n; $(id).textContent = n; };
  badge('b-lojas', S.stores.length); badge('b-produtos', toReview); badge('b-producao', S.candidates.filter(c => c.status === 'approved').length);
  VIEWS[route.view].update();
  enhance();
}

/** Alças de arrastar e ordem salva: cartões da tela, lojas, produção e produtos (a ordem dos produtos vira o "Minha ordem"). */
function enhance() {
  const v = $('view');
  [...v.querySelectorAll(':scope > .card')].forEach((el, i) => el.dataset.key = el.id || (el.querySelector('h2') || {}).textContent || 'c' + i);
  DND.apply(v, '.card', 'view:' + route.view);
  DND.apply($('stores'), '.scard', 'stores');
  DND.apply($('appr'), '.item', 'producao');
  const pl = document.querySelector('#plist > .grid, #plist > .list');
  if (pl) {
    const sel = pl.classList.contains('grid') ? '.pcard' : '.item';
    DND.apply(pl, sel, 'products-view');  // só põe as alças; a ordem dos produtos é feita pelos dados
    DND.bind(pl, sel, 'products', keys => { DND.save('products', keys.concat(DND.load('products').filter(k => !keys.includes(k)))); $('sort').value = 'manual'; update(); });
  }
}

$('profile').onchange = e => { store('profile', e.target.value); toast('Perfil: ' + e.target.value); };
$('q').oninput = () => { if (route[0] !== 'produtos') location.hash = '#/produtos'; else update(); };
document.body.addEventListener('click', e => {
  const r = e.target.closest('[data-rerun]'); if (r) return addStores([r.dataset.rerun]);
  const lg = e.target.closest('[data-login]');
  if (lg) return post('/api/profile/open', {profile: $('profile').value, url: lg.dataset.login}).then(r => toast(r.error || 'Chrome aberto. Entre na conta e feche a janela quando terminar.'));
  const au = e.target.closest('[data-auto]');
  if (au) return post('/api/auto', {id: +au.dataset.auto}).then(r => { toast(r.error || 'Rodando as etapas automáticas'); load(); });
  const rm = e.target.closest('[data-remove]');
  if (rm) { const id = +rm.dataset.remove;
    if (armed.id !== id || Date.now() > armed.until) { armed = {id, until: Date.now() + 5000}; update(); setTimeout(update, 5100); return; }
    armed = {id: 0, until: 0}; return post('/api/stores/remove', {id}).then(r => { toast(r.error || 'Loja removida'); load(); }); }
  const inf = e.target.closest('[data-info]'); if (inf) return refreshInfo(+inf.dataset.info);
  const sv = e.target.closest('[data-store]'); if (sv) pendingStore = sv.dataset.store;
  const d = e.target.closest('[data-decide]');
  if (d) decide(+d.dataset.decide, d.dataset.st, {approved:'Aprovado: foi para Produção', discarded:'Descartado', new:'Voltou para a revisão'}[d.dataset.st]);
});
// ---- atualização automática: confere ao abrir e a cada meia hora; instala só com o seu clique
async function checkUpdate(force) {
  let u; try { u = await (await fetch('/api/update/check' + (force ? '?force=1' : ''))).json(); } catch (e) { return; }
  if (u.version && $('ver')) $('ver').textContent = 'versão ' + u.version;
  const bar = $('updatebar'), j = u.job || {};
  if (j.status === 'running' || j.status === 'installing') {
    const pct = j.total ? Math.round(j.done / j.total * 100) : 0;
    bar.innerHTML = `<div class="alert upd"><div class="grow"><b>${esc(j.msg)}</b>${j.status === 'running' ? `<div class="bar"><i style="width:${pct}%"></i></div>` : ''}</div></div>`;
    return setTimeout(() => checkUpdate(), 1000);
  }
  if (j.status === 'error') bar.innerHTML = `<div class="alert err"><div class="grow"><b>A atualização falhou</b>${esc(j.msg)}</div><button data-updapply>Tentar de novo</button></div>`;
  else if (!u.frozen && u.behind > 0) bar.innerHTML = `<div class="alert upd"><div class="grow"><b>${u.behind} ${u.behind > 1 ? 'alterações novas' : 'alteração nova'} no GitHub</b><span class="small">Atualizar baixa tudo, fecha o app e abre de novo.</span></div><button class="pri" data-updapply>Atualizar agora</button></div>`;
  else if (u.frozen && u.newer) bar.innerHTML = `<div class="alert upd"><div class="grow"><b>Versão ${esc(u.latest)} disponível</b><span class="small">Você está na ${esc(u.current)}.${u.notes ? ' ' + esc(u.notes.split('\n').find(l => l.trim() && !/full changelog/i.test(l)) || '') : ''}</span></div>
      <button class="pri" data-updapply>Atualizar agora</button></div>`;
  else bar.innerHTML = '';
}
document.body.addEventListener('click', async e => {
  if (!e.target.closest('[data-updapply]')) return;
  const r = await post('/api/update/apply', {}); if (r.error) return toast(r.error);
  r.restart ? waitRestart() : checkUpdate();
});
// depois de fechar e abrir de novo, recarrega a tela quando o servidor voltar
const waitRestart = () => { const wait = () => fetch('/api/state', {cache: 'no-store'}).then(r => r.ok ? location.reload() : setTimeout(wait, 1000)).catch(() => setTimeout(wait, 1000)); setTimeout(wait, 3000); };
window.onhashchange = go;
go(); load(); setInterval(load, 3000); Onboarding.init(); checkUpdate(); setInterval(() => checkUpdate(true), 30 * 60 * 1000);

// Atualizar: puxa o que houver de novo (GitHub, ou a release no app instalado) e reinicia; sem novidade, só reinicia
$('restart').onclick = async () => {
  $('restart').disabled = true; $('restart').lastChild.textContent = 'Atualizando…';
  const u = await fetch('/api/update/check?force=1').then(r => r.json()).catch(() => ({}));
  const r = await post(u.frozen ? (u.newer ? '/api/update/apply' : '/api/restart') : (u.behind > 0 ? '/api/update/apply' : '/api/restart'), {}).catch(() => ({}));
  if (r.error) { $('restart').disabled = false; $('restart').lastChild.textContent = 'Atualizar'; return toast(r.error); }
  if (u.frozen && u.newer) return checkUpdate();
  waitRestart();
};

// links externos: o WebView do app não abre janelas novas, então o app abre no navegador padrão (ou no Chrome do perfil)
document.body.addEventListener('click', async e => {
  const b = e.target.closest('[data-open]'), a = e.target.closest('a[target=_blank][href^="http"]'), sw = e.target.closest('[data-swap]');
  if (sw) { const m = $('mcard'); m.scrollIntoView({behavior: 'smooth', block: 'start'}); $('msq').focus(); return; }
  const url = b ? b.dataset.open : a && a.href; if (!url) return;
  e.preventDefault();
  const r = await post('/api/open', {url, chrome: !!(b && b.dataset.chrome), profile: $('profile').value});
  if (r.error) { toast(r.error); if (!b || !b.dataset.chrome) window.open(url, '_blank'); }
});

// as etapas do topo levam ao cartão de cada uma
document.body.addEventListener('click', e => { const g = e.target.closest('[data-goto]'); if (!g) return; e.preventDefault();
  const el = $(g.dataset.goto); if (el && !el.hidden) { el.scrollIntoView({behavior: 'smooth', block: 'start'}); el.classList.add('flash'); setTimeout(() => el.classList.remove('flash'), 1400); } else toast('Esta etapa ainda não está liberada: faça as anteriores primeiro'); });

// a faixa de modo de teste pode ser fechada; lembra a escolha
(() => { const bar = document.querySelector('.testbar'); let off = false; try { off = localStorage.getItem('testbar') === '0'; } catch (e) {}
  if (off) bar.hidden = true; bar.insertAdjacentHTML('beforeend', '<button class="x" title="Fechar este aviso" aria-label="Fechar">×</button>');
  bar.querySelector('.x').onclick = () => { bar.hidden = true; try { localStorage.setItem('testbar', '0'); } catch (e) {} }; })();

// uma escolha só (Chrome visível ou oculto) para leitura de lojas e busca de modelos
const bshows = () => document.querySelectorAll('.bshow, #mshow');
fetch('/api/browser').then(r => r.json()).then(b => { window.BHEAD = b.headless; });
document.body.addEventListener('change', e => { const t = e.target.closest('.bshow, #mshow'); if (!t) return; window.BHEAD = !t.checked; post('/api/browser', {headless: !t.checked});
  bshows().forEach(x => x.checked = t.checked); toast(t.checked ? 'O navegador vai aparecer durante a leitura e a busca' : 'O navegador vai rodar escondido'); });
setInterval(() => { if (window.BHEAD != null) bshows().forEach(x => { if (x !== document.activeElement) x.checked = !window.BHEAD; }); }, 1000);
