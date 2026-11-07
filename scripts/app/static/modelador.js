// Tela Modelador: link de Reel ou Short -> vídeo, texto e transcrição -> editor (corte, legendas em português, sua voz, enquadramento)
// -> modelo 3D -> estúdio. Carrega antes do app.js; usa $, esc e post (definidos lá) só quando a tela é desenhada.
const MOD = {id: null, job: null, rec: null, chunks: [], timer: 0, busy: false, cor: '#E8478B', edKey: ''};
const MOD_ETAPAS = {baixando: 'Baixando o vídeo', transcrevendo: 'Transcrevendo', traduzindo: 'Traduzindo as legendas', buscando: 'Procurando o modelo', estudio: 'Montando o estúdio', pronto: 'Pronto', modelos: 'Modelos encontrados', estudio_pronto: 'Estúdio pronto', editando: 'Gerando o vídeo final', final_pronto: 'Vídeo final pronto', erro: 'Erro'};

async function modGet(id) {
  const r = await fetch('/api/referencia?id=' + encodeURIComponent(id));
  return r.json();
}

function modPoll() {
  clearTimeout(MOD.timer);
  if (!MOD.id || !MOD.job || MOD.job.status !== 'running' && !['buscando', 'estudio'].includes(MOD.job.etapa)) return;
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
    MOD.id = r.id; MOD.job = r; MOD.edKey = ''; modDraw(); modPoll();
  } catch (e) { modMsg('Sem conexão com o app', true); }
  finally { MOD.busy = false; }
}

async function modGravar() {
  if (MOD.rec) { MOD.rec.stop(); return; }
  if (!MOD.id) return modMsg('analise um link primeiro', true);
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({audio: true}); }
  catch (e) { return edMsg('não consegui acessar o microfone: confira a permissão do Windows e do app', true); }
  MOD.chunks = [];
  MOD.rec = new MediaRecorder(stream);
  // o vídeo toca mudo enquanto você grava por cima dele
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

async function modBaixarPs() {
  const j = await post('/api/referencia/baixar-de-novo', {id: MOD.id, metodo: 'powershell'});
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

function modDraw() {
  const j = MOD.job, box = $('mod-resultado');
  if (!box) return;
  if (!j) { box.innerHTML = ''; edDesenhar(null); return; }
  const etapa = MOD_ETAPAS[j.etapa] || j.etapa || '';
  const linhas = [];
  linhas.push(`<p class="small mut">${esc(etapa)}${j.plataforma ? ' · ' + (j.plataforma === 'instagram' ? 'Instagram' : 'YouTube Shorts') : ''}</p>`);
  if (j.comando && !j.video) linhas.push(`<details class="mod-comando"><summary>Comando de download (PowerShell)</summary>
      <pre class="mod-texto">${esc(j.comando)}</pre><button id="mod-copiar" class="sm">Copiar comando</button>
      ${j.status === 'error' ? '<button id="mod-baixar-ps" class="pri">Baixar agora pelo PowerShell</button>' : ''}</details>`);
  if (j.video) linhas.push(`<video class="mod-video" controls playsinline src="/api/referencia/arquivo?id=${encodeURIComponent(MOD.id)}&f=original"></video>`);
  if (j.titulo) linhas.push(`<h3>${esc(j.titulo)}</h3>`);
  if (j.descricao) linhas.push(`<details><summary>Texto do post</summary><p class="mod-texto">${esc(j.descricao)}</p></details>`);
  if (j.transcricao) linhas.push(`<details><summary>Transcrição (${esc(j.idioma || '')})</summary><p class="mod-texto">${esc(j.transcricao)}</p></details>`);
  if (j.consultas && j.consultas.length) linhas.push(`<p class="small">Termos para buscar: ${j.consultas.map(c => `<span class="tag">${esc(c)}</span>`).join(' ')}</p>`);
  if (j.status === 'ok' && j.etapa === 'pronto' || j.modelos) linhas.push(`<div class="row" style="margin-top:8px"><button id="mod-buscar" class="pri">Buscar o modelo deste vídeo</button><label class="sm">ou enviar o arquivo do modelo (.stl ou .3mf) <input type="file" id="mod-arquivo" accept=".stl,.3mf"></label></div>`);
  if (j.modelos) {
    linhas.push(j.modelos.length ? '<div class="mod-modelos">' + j.modelos.map((m, i) => `<div class="card mod-modelo">
        ${m.thumb ? `<img src="${esc(m.thumb)}" alt="">` : ''}
        <div><b>${esc(m.title)}</b><div class="small mut">${esc(m.author || '')}</div>
        <button class="sm mod-usar" data-i="${i}">Usar este modelo</button></div></div>`).join('') + '</div>'
      : '<p class="small mut">Nenhum modelo encontrado. Envie o arquivo do modelo.</p>');
    if (j.avisos && j.avisos.length) linhas.push(`<p class="small mut">${esc(j.avisos.join(' · '))}</p>`);
  }
  if (j.modelo && j.etapa !== 'estudio' && !j.estudio) linhas.push(`<div class="row"><label class="sm">Cor do produto <input type="color" id="mod-cor" value="${esc(MOD.cor)}"></label><button id="mod-estudio" class="pri">Gerar o estúdio (fotos 1:1, medidas e giro 9:16)</button></div>`);
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
  on('mod-copiar', () => { navigator.clipboard?.writeText(j.comando).then(() => modMsg('Comando copiado: cole no PowerShell.')); });
  on('mod-baixar-ps', modBaixarPs);
  const cor = $('mod-cor');
  if (cor) cor.oninput = () => { MOD.cor = cor.value; };
  document.querySelectorAll('.mod-usar').forEach(b => b.onclick = () => modEstudio(Number(b.dataset.i)));
  const arq = $('mod-arquivo');
  if (arq) arq.onchange = () => modEnviarModelo(arq);
  if (j.status === 'error') modMsg(j.msg, true); else if (j.msg) modMsg(j.msg);
  edDesenhar(j);
}

// Editor: desenhado uma vez por vídeo (e de novo quando chegam as legendas), para não perder o que você digitou a cada andamento.
const tempo = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

function edDesenhar(j) {
  const wrap = $('mod-editor-wrap'), box = $('mod-editor');
  if (!wrap) return;
  wrap.hidden = !(j && j.video);
  if (!j || !j.video) { box.innerHTML = ''; MOD.edKey = ''; return; }
  const key = `${MOD.id}|${(j.legendas || []).length}`;
  if (key === MOD.edKey) return edAtualizar(j);
  MOD.edKey = key;
  const dur = j.duracao || 0, legs = j.legendas || [];
  box.innerHTML = `<h2>Editor do vídeo</h2>
    <div class="ed-grid">
      <label>Começa aos (s)<input id="ed-ini" type="number" step="0.1" min="0" value="0"></label>
      <label>Termina aos (s)<input id="ed-fim" type="number" step="0.1" min="0" value="${dur.toFixed(1)}"></label>
      <label>Formato<select id="ed-formato"><option value="9:16">Vertical 9:16</option><option value="1:1">Quadrado 1:1</option><option value="16:9">Horizontal 16:9</option></select></label>
      <label>Zoom<input id="ed-zoom" type="range" min="1" max="3" step="0.05" value="1"></label>
      <label>Deslocar na horizontal<input id="ed-dx" type="range" min="-1" max="1" step="0.05" value="0"></label>
      <label>Deslocar na vertical<input id="ed-dy" type="range" min="-1" max="1" step="0.05" value="0"></label>
    </div>
    <h3>Legendas em português</h3>
    <label class="chk"><input type="checkbox" id="ed-legendas" checked> Mostrar legendas</label>
    <div class="ed-legs">${legs.map(s => `<div class="ed-leg" data-a="${s.start}" data-b="${s.end}"><span class="small mut">${tempo(s.start)}</span><textarea rows="2">${esc(s.text)}</textarea></div>`).join('') || '<p class="small mut">Sem legendas: a transcrição não rodou ou não achou fala. Você pode gerar o vídeo sem legenda.</p>'}</div>
    <label class="chk"><input type="checkbox" id="ed-cobrir"> Cobrir a legenda original (faixa na parte de baixo)</label>
    <label>Posição da faixa<input id="ed-cobrir-y" type="range" min="0" max="0.86" step="0.01" value="0.8"></label>
    <h3>Sua voz</h3>
    <div class="row"><button id="ed-gravar" class="pri">Gravar minha voz</button><label class="sm">ou enviar um áudio <input type="file" id="ed-arquivo" accept="audio/*"></label></div>
    <div id="ed-voz" class="small mut"></div>
    <label class="chk"><input type="checkbox" id="ed-manter" ${j.voz ? '' : 'checked'}> Manter o som original</label>
    <label>Volume da sua voz<input id="ed-vol-voz" type="range" min="0" max="2" step="0.05" value="1"></label>
    <label>Volume do som original<input id="ed-vol-orig" type="range" min="0" max="2" step="0.05" value="0.3"></label>
    <details class="ed-mais"><summary>Mais opções</summary>
      <label>Tamanho da legenda<input id="ed-tam" type="number" min="24" max="120" value="52"></label>
      <label>Cor da legenda<input id="ed-cor" type="color" value="#ffffff"></label>
      <label class="chk"><input type="checkbox" id="ed-caixa" checked> Caixa escura atrás da legenda</label>
      <label>Posição da legenda<select id="ed-pos"><option value="bottom">Embaixo</option><option value="center">No meio</option><option value="top">Em cima</option></select></label>
      <label>Estilo da faixa<select id="ed-estilo"><option value="caixa">Caixa</option><option value="borrao">Desfoque</option></select></label>
      <label>Cor da faixa<input id="ed-cor-faixa" type="color" value="#000000"></label>
      <label>Qualidade<select id="ed-qualidade"><option value="rapido">Menor arquivo</option><option value="normal" selected>Normal</option><option value="alta">Alta</option></select></label>
    </details>
    <h3>Prévia e vídeo final</h3>
    <label>Quadro da prévia (s do corte)<input id="ed-momento" type="range" min="0" max="${Math.max(0, dur - 0.1).toFixed(1)}" step="0.1" value="1"></label>
    <div class="row"><button id="ed-previa">Ver um quadro</button><button id="ed-gerar" class="pri">Gerar vídeo final</button></div>
    <img id="ed-img" class="ed-img" alt="Prévia do quadro" hidden>
    <div id="ed-final"></div><div id="ed-msg" class="small mut"></div>`;
  const limitar = () => { $('ed-momento').max = Math.max(0, +$('ed-fim').value - +$('ed-ini').value - 0.1).toFixed(1); };
  ['ed-ini', 'ed-fim'].forEach(id => $(id).oninput = limitar);
  $('ed-gravar').onclick = modGravar;
  $('ed-arquivo').onchange = () => modEnviarVoz($('ed-arquivo'));
  $('ed-previa').onclick = edPrevia;
  $('ed-gerar').onclick = edGerar;
  edAtualizar(j);
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
  $('ed-voz').textContent = j.voz ? 'Voz pronta: entra no vídeo conforme as opções abaixo.' : 'Sem voz gravada: o vídeo usa só o som original ou fica mudo.';
  const final = $('ed-final');
  final.innerHTML = j.final ? `<div class="row"><a class="pri" href="/api/referencia/arquivo?id=${encodeURIComponent(MOD.id)}&f=final" download="video-final.mp4">Baixar vídeo final</a>
      <button id="ed-pasta">Abrir pasta</button></div>
      <video class="mod-video" controls playsinline src="/api/referencia/arquivo?id=${encodeURIComponent(MOD.id)}&f=final"></video>` : '';
  if ($('ed-pasta')) $('ed-pasta').onclick = edAbrirPasta;
  if (j.status === 'running' && j.etapa === 'editando') edMsg('Gerando o vídeo final. Pode levar alguns minutos.');
  else if (j.status === 'error' && j.etapa === 'pronto') edMsg(j.msg, true);
  else if (j.final) edMsg('Vídeo final pronto: baixe ou abra a pasta.');
}

const VIEWS_MODELADOR = {
  modelador: {
    mount: () => `<div class="card"><h2>Modelador</h2>
        <p class="small mut">Cole o link de um Reel do Instagram ou de um YouTube Shorts (ou de um vídeo do YouTube). O app baixa o vídeo e o texto do post, transcreve a fala e traduz as legendas para português. No editor você ajusta o corte, o enquadramento e as legendas, grava sua voz e gera o vídeo final. Depois, busca o modelo 3D e monta o estúdio.</p>
        <div class="row" style="margin-top:8px"><input id="mod-url" type="url" placeholder="https://www.instagram.com/reel/… ou https://www.youtube.com/watch?v=…" style="flex:1"><button id="mod-analisar" class="pri">Analisar</button></div>
        <div id="mod-msg" class="small mut" style="margin-top:6px"></div></div>
      <div class="card"><div id="mod-resultado"></div></div>
      <div class="card" id="mod-editor-wrap" hidden><div id="mod-editor"></div></div>`,
    bind: () => {
      $('mod-analisar').onclick = modAnalisar;
      $('mod-url').onkeydown = e => { if (e.key === 'Enter') modAnalisar(); };
      modDraw(); modPoll();
    },
    update: () => {},
  },
};
