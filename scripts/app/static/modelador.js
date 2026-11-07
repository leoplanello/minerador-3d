// Tela Modelador em cinco passos: 1 Link -> 2 Legenda -> 3 Voz -> 4 Enquadramento -> 5 Gerar; depois, o modelo 3D.
// Carrega antes do app.js; usa $, esc e post (definidos lá) só quando a tela é desenhada.
const MOD = {id: null, job: null, rec: null, chunks: [], timer: 0, busy: false, cor: '#E8478B', edKey: '', modKey: ''};
const MOD_ETAPAS = {baixando: 'Baixando o vídeo', transcrevendo: 'Transcrevendo', traduzindo: 'Traduzindo as legendas', buscando: 'Procurando o modelo', estudio: 'Montando o estúdio', pronto: 'Pronto', modelos: 'Modelos encontrados', estudio_pronto: 'Estúdio pronto', editando: 'Gerando o vídeo final', final_pronto: 'Vídeo final pronto', erro: 'Erro', login: 'Precisa de login'};
const tempo = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

async function modGet(id) {
  const r = await fetch('/api/referencia?id=' + encodeURIComponent(id));
  return r.json();
}

function modPoll() {
  clearTimeout(MOD.timer);
  const andando = MOD.job && (MOD.job.status === 'running' || ['buscando', 'estudio'].includes(MOD.job.etapa));
  if (!MOD.id || !andando) return;
  MOD.timer = setTimeout(async () => {
    try { MOD.job = await modGet(MOD.id); modDraw(); } catch (e) { /* servidor ocupado: tenta de novo */ }
    modPoll();
  }, 1500);
}

function modMsg(texto, erro) {
  const el = $('mod-msg');
  if (el) { el.textContent = texto || ''; el.className = 'small ' + (erro ? 'bad' : 'mut'); }
}

function edMsg(texto, erro) {
  const el = $('ed-msg');
  if (el) { el.textContent = texto || ''; el.className = 'small ' + (erro ? 'bad' : 'mut'); }
}

async function modAnalisar() {
  const url = ($('mod-url').value || '').trim();
  if (!url) return modMsg('cole o link do Reel ou do Short', true);
  MOD.busy = true; modMsg('Enviando o link…');
  try {
    const r = await post('/api/referencia', {url});
    if (r.error) return modMsg(r.error, true);
    MOD.id = r.id; MOD.job = r; MOD.edKey = ''; MOD.modKey = ''; modDraw(); modPoll();
  } catch (e) { modMsg('Sem conexão com o app', true); }
  finally { MOD.busy = false; }
}

// Tenta de novo; com perfil (site que pediu login), usa os cookies desse perfil do seu Chrome.
async function modTentar(perfil) {
  const j = await post('/api/referencia/baixar-de-novo', {id: MOD.id, perfil: perfil || ''});
  if (j.error) return modMsg(j.error, true);
  MOD.job = j; modDraw(); modPoll();
}

async function modBuscar() {
  const j = await post('/api/referencia/buscar', {id: MOD.id});
  if (j.error) return modMsg(j.error, true);
  MOD.job = j; modDraw(); modPoll();
}

async function modEstudio(indice) {
  const j = await post('/api/referencia/estudio', {id: MOD.id, indice, cor: MOD.cor});
  if (j.error) return modMsg(j.error, true);
  MOD.job = j; modDraw(); modPoll();
}

async function modEnviarModelo(input) {
  const f = input.files[0];
  if (!f) return;
  const r = await fetch('/api/referencia/modelo?id=' + encodeURIComponent(MOD.id) + '&name=' + encodeURIComponent(f.name), {method: 'POST', body: f});
  const j = await r.json();
  if (j.error) return modMsg(j.error, true);
  MOD.job = j; modDraw(); modPoll();
}

// Passo 1: link, andamento, login (se o site pedir), erro e o vídeo baixado.
function modPasso1(j) {
  const linhas = [];
  if (j.status === 'login') {
    const perfis = j.perfis || [];
    linhas.push(perfis.length
      ? `<label class="sm">Perfil do Chrome onde você já entrou neste site
           <select id="mod-perfil">${perfis.map(p => `<option value="${esc(p.pasta)}">${esc(p.nome)}${p.email ? ' · ' + esc(p.email) : ''}</option>`).join('')}</select></label>
         <button id="mod-tentar-login" class="pri">Tentar de novo com este perfil</button>`
      : '<p class="small bad">Não achei perfis do Chrome neste PC. Entre no site pelo Chrome e tente de novo.</p><button id="mod-tentar" class="pri">Tentar de novo</button>');
  }
  if (j.status === 'error' && j.etapa === 'erro') linhas.push('<button id="mod-tentar" class="pri">Tentar de novo</button>');
  if (j.video) {
    linhas.push(`<video class="mod-video" controls playsinline src="/api/referencia/arquivo?id=${encodeURIComponent(MOD.id)}&f=original"></video>`);
    if (j.titulo) linhas.push(`<p><b>${esc(j.titulo)}</b></p>`);
    if (j.descricao) linhas.push(`<details><summary class="small">Texto do post</summary><p class="mod-texto">${esc(j.descricao)}</p></details>`);
  }
  if (j.comando) linhas.push(`<details class="mod-comando"><summary class="small">Avançado: comando de download (PowerShell)</summary>
      <pre class="mod-texto">${esc(j.comando)}</pre><button id="mod-copiar" class="sm">Copiar comando</button></details>`);
  return linhas.join('');
}

function modDraw() {
  const j = MOD.job, box = $('mod-resultado');
  if (!box) return;
  if (!j) { box.innerHTML = ''; $('mod-editor-wrap').hidden = true; $('mod-modelo-wrap').hidden = true; return; }
  box.innerHTML = modPasso1(j);
  const on = (id, fn) => { const el = $(id); if (el) el.onclick = fn; };
  on('mod-tentar', () => modTentar(''));
  on('mod-tentar-login', () => modTentar($('mod-perfil').value));
  on('mod-copiar', () => { navigator.clipboard?.writeText(j.comando).then(() => modMsg('Comando copiado: cole no PowerShell.')); });
  if (j.status === 'error') modMsg(j.msg, true); else if (j.msg) modMsg(j.msg);
  edDesenhar(j);
  modDesenharModelo(j);
}

// Passos 2 a 5 aparecem quando o vídeo está baixado. Montados uma vez por vídeo, para não perder o que você digitou.
function edDesenhar(j) {
  const wrap = $('mod-editor-wrap'), box = $('mod-editor');
  if (!wrap) return;
  const pronto = j && j.video && !['baixando', 'transcrevendo', 'traduzindo'].includes(j.etapa);  // legendas prontas antes de editar
  wrap.hidden = !pronto;
  if (!pronto) { box.innerHTML = ''; MOD.edKey = ''; return; }
  const key = `${MOD.id}|${(j.legendas || []).length}`;
  if (key === MOD.edKey) return edAtualizar(j);
  MOD.edKey = key;
  const dur = j.duracao || 0, legs = j.legendas || [];
  box.innerHTML = `
    <section class="card mod-passo"><h3><span class="num">2</span> Legenda em português</h3>
      <p class="small mut">Confira e corrija a tradução. Cada fala vira uma legenda queimada no vídeo.</p>
      <div class="ed-legs">${legs.map(s => `<div class="ed-leg" data-a="${s.start}" data-b="${s.end}"><span class="small mut">${tempo(s.start)}</span><textarea rows="2">${esc(s.text)}</textarea></div>`).join('') || '<p class="small mut">Não achei fala neste vídeo: ele sai sem legenda.</p>'}</div>
      <label class="chk"><input type="checkbox" id="ed-legendas" checked> Mostrar legendas</label>
      <details><summary class="small">Transcrição original (${esc(j.idioma || '')})</summary><p class="mod-texto">${esc(j.transcricao || '')}</p></details>
    </section>
    <section class="card mod-passo"><h3><span class="num">3</span> Sua voz <span class="chip" id="ed-voz-chip" hidden>gravada</span></h3>
      <p class="small mut">Grave por cima do vídeo ou envie um áudio pronto. Sem voz, o vídeo usa só o som original (ou fica mudo).</p>
      <div class="row"><button id="ed-gravar" class="pri">Gravar minha voz</button><label class="sm">ou enviar um áudio <input type="file" id="ed-arquivo" accept="audio/*"></label></div>
      <div id="ed-voz" class="small mut"></div>
      <label class="chk"><input type="checkbox" id="ed-manter" checked> Manter também o som original</label>
    </section>
    <section class="card mod-passo"><h3><span class="num">4</span> Enquadramento e corte</h3>
      <div class="ed-grid">
        <label>Começa aos (s)<input id="ed-ini" type="number" step="0.1" min="0" value="0"></label>
        <label>Termina aos (s)<input id="ed-fim" type="number" step="0.1" min="0" value="${dur.toFixed(1)}"></label>
        <label>Formato<select id="ed-formato"><option value="9:16">Vertical 9:16</option><option value="1:1">Quadrado 1:1</option><option value="16:9">Horizontal 16:9</option></select></label>
        <label>Zoom<input id="ed-zoom" type="range" min="1" max="3" step="0.05" value="1"></label>
        <label>Deslocar na horizontal<input id="ed-dx" type="range" min="-1" max="1" step="0.05" value="0"></label>
        <label>Deslocar na vertical<input id="ed-dy" type="range" min="-1" max="1" step="0.05" value="0"></label>
      </div>
      <label class="chk"><input type="checkbox" id="ed-cobrir"> Cobrir a legenda original com uma faixa</label>
      <label>Posição da faixa<input id="ed-cobrir-y" type="range" min="0" max="0.86" step="0.01" value="0.8"></label>
      <label>Quadro da prévia (s do corte)<input id="ed-momento" type="range" min="0" max="${Math.max(0, dur - 0.1).toFixed(1)}" step="0.1" value="1"></label>
      <div class="row"><button id="ed-previa" class="pri">Ver um quadro</button></div>
      <img id="ed-img" class="ed-img" alt="Prévia do quadro" hidden>
    </section>
    <section class="card mod-passo"><h3><span class="num">5</span> Gerar o vídeo</h3>
      <div class="row"><button id="ed-gerar" class="pri">Gerar vídeo final</button></div>
      <div id="ed-final"></div><div id="ed-msg" class="small mut"></div>
    </section>
    <details class="card mod-avancado"><summary><b>Mais opções</b></summary>
      <label>Volume da sua voz<input id="ed-vol-voz" type="range" min="0" max="2" step="0.05" value="1"></label>
      <label>Volume do som original<input id="ed-vol-orig" type="range" min="0" max="2" step="0.05" value="0.3"></label>
      <label>Tamanho da legenda<input id="ed-tam" type="number" min="24" max="120" value="52"></label>
      <label>Cor da legenda<input id="ed-cor" type="color" value="#ffffff"></label>
      <label class="chk"><input type="checkbox" id="ed-caixa" checked> Caixa escura atrás da legenda</label>
      <label>Posição da legenda<select id="ed-pos"><option value="bottom">Embaixo</option><option value="center">No meio</option><option value="top">Em cima</option></select></label>
      <label>Estilo da faixa<select id="ed-estilo"><option value="caixa">Caixa</option><option value="borrao">Desfoque</option></select></label>
      <label>Cor da faixa<input id="ed-cor-faixa" type="color" value="#000000"></label>
      <label>Qualidade<select id="ed-qualidade"><option value="rapido">Menor arquivo</option><option value="normal" selected>Normal</option><option value="alta">Alta</option></select></label>
    </details>`;
  const limitar = () => { $('ed-momento').max = Math.max(0, +$('ed-fim').value - +$('ed-ini').value - 0.1).toFixed(1); };
  ['ed-ini', 'ed-fim'].forEach(id => $(id).oninput = limitar);
  $('ed-gravar').onclick = modGravar;
  $('ed-arquivo').onchange = () => modEnviarVoz($('ed-arquivo'));
  $('ed-previa').onclick = edPrevia;
  $('ed-gerar').onclick = edGerar;
  edAtualizar(j);
}

// Passo 3: gravar a voz no navegador (o vídeo toca mudo por cima).
async function modGravar() {
  if (MOD.rec) { MOD.rec.stop(); return; }
  if (!MOD.id) return edMsg('analise um link primeiro', true);
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({audio: true}); }
  catch (e) { return edMsg('não consegui acessar o microfone: confira a permissão do Windows e do app, ou envie um áudio', true); }
  MOD.chunks = [];
  MOD.rec = new MediaRecorder(stream);
  const v = document.querySelector('#mod-resultado .mod-video');
  if (v) { v.currentTime = 0; v.muted = true; v.play().catch(() => {}); }
  MOD.rec.ondataavailable = e => { if (e.data.size) MOD.chunks.push(e.data); };
  MOD.rec.onstop = async () => {
    stream.getTracks().forEach(t => t.stop());
    if (v) v.pause();
    const blob = new Blob(MOD.chunks, {type: MOD.rec.mimeType || 'audio/webm'});
    MOD.rec = null; edAtualizar(MOD.job);
    const r = await fetch('/api/referencia/voz?id=' + encodeURIComponent(MOD.id), {method: 'POST', body: blob});
    const j = await r.json();
    if (j.error) return edMsg(j.error, true);
    MOD.job = j; edAtualizar(j); edMsg(j.msg);
  };
  MOD.rec.start();
  edAtualizar(MOD.job);
}

async function modEnviarVoz(input) {
  const f = input.files[0];
  if (!f) return;
  const r = await fetch('/api/referencia/voz?id=' + encodeURIComponent(MOD.id), {method: 'POST', body: f});
  const j = await r.json();
  if (j.error) return edMsg(j.error, true);
  MOD.job = j; edAtualizar(j); edMsg(j.msg);
}

function edCfg() {
  const v = id => $(id).value, c = id => $(id).checked;
  return {inicio: +v('ed-ini') || 0, fim: v('ed-fim') === '' ? null : +v('ed-fim'), formato: v('ed-formato'), zoom: +v('ed-zoom'),
    dx: +v('ed-dx'), dy: +v('ed-dy'), legendas: c('ed-legendas'), legenda_tamanho: +v('ed-tam'), legenda_cor: v('ed-cor'),
    legenda_caixa: c('ed-caixa'), legenda_pos: v('ed-pos'), cobrir: c('ed-cobrir'), cobrir_y: +v('ed-cobrir-y'), cobrir_h: 0.14,
    cobrir_estilo: v('ed-estilo'), cobrir_cor: v('ed-cor-faixa'), som_original: c('ed-manter') ? 'manter' : 'silenciar',
    vol_original: +v('ed-vol-orig'), vol_voz: +v('ed-vol-voz'), qualidade: v('ed-qualidade'), momento: +v('ed-momento') || 0};
}

// Legendas: o texto que você editou, com o tempo original de cada fala.
const edLegendas = () => [...document.querySelectorAll('.ed-leg')].map(el => ({start: +el.dataset.a, end: +el.dataset.b, text: el.querySelector('textarea').value}));

async function edPrevia() {
  edMsg('Montando o quadro…');
  const j = await post('/api/referencia/quadro', {id: MOD.id, cfg: edCfg(), legendas: edLegendas()});
  if (j.error) return edMsg(j.error, true);
  const img = $('ed-img');
  img.src = `/api/referencia/arquivo?id=${encodeURIComponent(MOD.id)}&f=previa&v=${Date.now()}`;
  img.hidden = false;
  edMsg('Prévia de um quadro. Ajuste e veja de novo, ou gere o vídeo final.');
}

async function edGerar() {
  const j = await post('/api/referencia/editar', {id: MOD.id, cfg: edCfg(), legendas: edLegendas()});
  if (j.error) return edMsg(j.error, true);
  MOD.job = j; modPoll(); edAtualizar(j);
}

async function edAbrirPasta() {
  const j = await post('/api/referencia/abrir-pasta', {id: MOD.id});
  if (j.error) edMsg(j.error, true);
}

// Atualiza só os pedaços que mudam (voz, gravação, vídeo final): não redesenha o que você está editando.
function edAtualizar(j) {
  if (!$('ed-gravar') || !j) return;
  $('ed-gravar').textContent = MOD.rec ? 'Parar gravação' : 'Gravar minha voz';
  $('ed-gravar').className = MOD.rec ? 'bad' : 'pri';
  $('ed-voz').textContent = j.voz ? 'Voz pronta: entra no vídeo conforme as opções abaixo.' : 'Sem voz gravada ainda.';
  $('ed-voz-chip').hidden = !j.voz;
  $('ed-final').innerHTML = j.final ? `<div class="row"><a class="pri" href="/api/referencia/arquivo?id=${encodeURIComponent(MOD.id)}&f=final" download="video-final.mp4">Baixar vídeo final</a>
      <button id="ed-pasta">Abrir pasta</button></div>
      <video class="mod-video" controls playsinline src="/api/referencia/arquivo?id=${encodeURIComponent(MOD.id)}&f=final"></video>` : '';
  if ($('ed-pasta')) $('ed-pasta').onclick = edAbrirPasta;
  if (j.status === 'running' && j.etapa === 'editando') edMsg('Gerando o vídeo final. Pode levar alguns minutos.');
  else if (j.status === 'error' && j.etapa === 'pronto') edMsg(j.msg, true);
  else if (j.final) edMsg('Vídeo final pronto: baixe ou abra a pasta.');
}

// Depois do vídeo: buscar o modelo 3D (leva ao estúdio e ao cartão do produto) ou enviar o arquivo.
function modDesenharModelo(j) {
  const wrap = $('mod-modelo-wrap'), box = $('mod-modelo');
  if (!wrap) return;
  wrap.hidden = !(j.video && (j.etapa === 'pronto' || j.modelos || j.modelo || j.estudio || j.final));
  const key = JSON.stringify([j.modelos || [], j.estudio ? 1 : 0, j.modelo || '', j.consultas || [], j.etapa, MOD.cor]);
  if (key === MOD.modKey) return;
  MOD.modKey = key;
  const linhas = ['<h2>Modelo 3D deste produto</h2>'];
  if (!j.estudio) {
    linhas.push(`<p class="small mut">Procuro o modelo no Printables, no MakerWorld e no Thingiverse pelo título e pelas palavras do vídeo.</p>
      <div class="row"><button id="mod-buscar" class="pri">Buscar o modelo deste vídeo</button><label class="sm">ou enviar o arquivo (.stl ou .3mf) <input type="file" id="mod-arquivo" accept=".stl,.3mf"></label></div>`);
  }
  if (j.consultas && j.consultas.length) linhas.push(`<p class="small">Termos: ${j.consultas.map(c => `<span class="tag">${esc(c)}</span>`).join(' ')}</p>`);
  if (j.modelos) {
    linhas.push(j.modelos.length ? '<div class="mod-modelos">' + j.modelos.map((m, i) => `<div class="card mod-modelo">
        ${m.thumb ? `<img src="${esc(m.thumb)}" alt="">` : ''}
        <div><b>${esc(m.title)}</b><div class="small mut">${esc(m.author || '')}</div>
        <button class="sm mod-usar" data-i="${i}">Usar este modelo</button></div></div>`).join('') + '</div>'
      : '<p class="small mut">Nenhum modelo encontrado. Envie o arquivo do modelo.</p>');
    if (j.avisos && j.avisos.length) linhas.push(`<p class="small mut">${esc(j.avisos.join(' · '))}</p>`);
  }
  if (j.modelo && !j.estudio) linhas.push(`<div class="row"><label class="sm">Cor do produto <input type="color" id="mod-cor" value="${esc(MOD.cor)}"></label><button id="mod-estudio" class="pri">Gerar o estúdio (fotos 1:1, medidas e giro 9:16)</button></div>`);
  if (j.estudio) {
    const e = j.estudio, dims = e.dimensoes_mm ? e.dimensoes_mm.map(v => Math.round(v)).join(' × ') + ' mm' : '';
    linhas.push(`<h3>Estúdio</h3><p class="small">Medidas: ${esc(dims)}</p>
      <div class="mod-galeria">${[1, 2, 3, 4, 5, 6, 7, 8, 9].map(i => `<img src="/api/referencia/arquivo?id=${encodeURIComponent(MOD.id)}&f=estudio/angulo_${String(i).padStart(2, '0')}.png" alt="">`).join('')}
        <img src="/api/referencia/arquivo?id=${encodeURIComponent(MOD.id)}&f=estudio/medidas.png" alt="">
        <video class="mod-video" controls loop src="/api/referencia/arquivo?id=${encodeURIComponent(MOD.id)}&f=estudio/giro-360-9x16.mp4"></video></div>`);
  }
  box.innerHTML = linhas.join('');
  const on = (id, fn) => { const el = $(id); if (el) el.onclick = fn; };
  on('mod-buscar', modBuscar);
  on('mod-estudio', () => modEstudio(0));
  const cor = $('mod-cor');
  if (cor) cor.oninput = () => { MOD.cor = cor.value; };
  document.querySelectorAll('.mod-usar').forEach(b => b.onclick = () => modEstudio(Number(b.dataset.i)));
  const arq = $('mod-arquivo');
  if (arq) arq.onchange = () => modEnviarModelo(arq);
}

const VIEWS_MODELADOR = {
  modelador: {
    mount: () => `<section class="card mod-passo"><h2>Modelador</h2>
        <p class="small mut">Cole o link de um Reel do Instagram ou de um YouTube Shorts. O app baixa o vídeo, transcreve a fala e traduz as legendas. Depois você ajusta, grava sua voz e gera o vídeo final.</p>
        <h3><span class="num">1</span> Link</h3>
        <div class="row"><input id="mod-url" type="url" placeholder="https://www.youtube.com/shorts/… ou https://www.instagram.com/reel/…" style="flex:1"><button id="mod-analisar" class="pri">Analisar</button></div>
        <div id="mod-msg" class="small mut" style="margin-top:6px"></div>
        <div id="mod-resultado"></div></section>
      <div id="mod-editor-wrap" hidden><div id="mod-editor"></div></div>
      <section class="card" id="mod-modelo-wrap" hidden><div id="mod-modelo"></div></section>`,
    bind: () => {
      $('mod-analisar').onclick = modAnalisar;
      $('mod-url').onkeydown = e => { if (e.key === 'Enter') modAnalisar(); };
      modDraw(); modPoll();
    },
    update: () => {},
  },
};
