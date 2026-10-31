// Tela Modelador: link de Reel ou Short -> vídeo, texto e transcrição -> sua voz -> modelo 3D -> estúdio.
// Carrega antes do app.js; usa $, esc e post (definidos lá) só quando a tela é desenhada.
const MOD = {id: null, job: null, rec: null, chunks: [], timer: 0, busy: false, cor: '#E8478B'};
const MOD_ETAPAS = {baixando: 'Baixando o vídeo', transcrevendo: 'Transcrevendo', buscando: 'Procurando o modelo', estudio: 'Montando o estúdio', pronto: 'Pronto', modelos: 'Modelos encontrados', estudio_pronto: 'Estúdio pronto', erro: 'Erro'};

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

async function modAnalisar() {
  const url = ($('mod-url').value || '').trim();
  if (!url) return modMsg('cole o link do Reel ou do Short', true);
  MOD.busy = true; modMsg('Enviando o link…');
  try {
    const r = await post('/api/referencia', {url});
    if (r.error) return modMsg(r.error, true);
    MOD.id = r.id; MOD.job = r; modDraw(); modPoll();
  } catch (e) { modMsg('Sem conexão com o app', true); }
  finally { MOD.busy = false; }
}

async function modGravar() {
  if (MOD.rec) { MOD.rec.stop(); return; }
  if (!MOD.id) return modMsg('analise um link primeiro', true);
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({audio: true}); }
  catch (e) { return modMsg('não consegui acessar o microfone: confira a permissão do Windows e do app', true); }
  MOD.chunks = [];
  MOD.rec = new MediaRecorder(stream);
  MOD.rec.ondataavailable = e => { if (e.data.size) MOD.chunks.push(e.data); };
  MOD.rec.onstop = async () => {
    stream.getTracks().forEach(t => t.stop());
    const blob = new Blob(MOD.chunks, {type: MOD.rec.mimeType || 'audio/webm'});
    MOD.rec = null; modDraw();
    const r = await fetch('/api/referencia/voz?id=' + encodeURIComponent(MOD.id), {method: 'POST', body: blob});
    const j = await r.json();
    if (j.error) return modMsg(j.error, true);
    MOD.job = j; modDraw(); modMsg('Gravação salva. Ouça e aplique no vídeo quando quiser.');
  };
  MOD.rec.start();
  modDraw();
}

async function modBaixarPs() {
  const j = await post('/api/referencia/baixar-de-novo', {id: MOD.id, metodo: 'powershell'});
  if (j.error) return modMsg(j.error, true);
  MOD.job = j; modDraw(); modPoll();
}

async function modAplicarVoz() {
  modMsg('Trocando o áudio do vídeo…');
  const j = await post('/api/referencia/aplicar-voz', {id: MOD.id});
  if (j.error) return modMsg(j.error, true);
  MOD.job = j; modDraw(); modMsg(j.msg);
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
  if (!j) { box.innerHTML = ''; return; }
  const etapa = MOD_ETAPAS[j.etapa] || j.etapa || '';
  const linhas = [];
  linhas.push(`<p class="small mut">${esc(etapa)}${j.plataforma ? ' · ' + (j.plataforma === 'instagram' ? 'Instagram' : 'YouTube Shorts') : ''}</p>`);
  if (j.comando && !j.video) linhas.push(`<details class="mod-comando"><summary>Comando de download (PowerShell)</summary>
      <pre class="mod-texto">${esc(j.comando)}</pre><button id="mod-copiar" class="sm">Copiar comando</button>
      ${j.status === 'error' ? '<button id="mod-baixar-ps" class="pri">Baixar agora pelo PowerShell</button>' : ''}</details>`);
  if (j.video) linhas.push(`<video class="mod-video" controls playsinline src="/api/referencia/arquivo?id=${encodeURIComponent(MOD.id)}&f=original"></video>`);
  if (j.titulo) linhas.push(`<h3>${esc(j.titulo)}</h3>`);
  if (j.descricao) linhas.push(`<details><summary>Texto do post</summary><p class="mod-texto">${esc(j.descricao)}</p></details>`);
  if (j.transcricao) linhas.push(`<details open><summary>Transcrição (${esc(j.idioma || '')})</summary><p class="mod-texto">${esc(j.transcricao)}</p></details>`);
  if (j.consultas && j.consultas.length) linhas.push(`<p class="small">Termos para buscar: ${j.consultas.map(c => `<span class="tag">${esc(c)}</span>`).join(' ')}</p>`);
  linhas.push(`<div class="row" style="margin-top:8px">
      <button id="mod-gravar" class="${MOD.rec ? 'bad' : 'pri'}">${MOD.rec ? 'Parar gravação' : 'Gravar minha voz'}</button>
      ${j.voz && !j.video_final ? '<button id="mod-aplicar" class="pri">Trocar o áudio do vídeo pela minha voz</button>' : ''}
      ${j.video_final ? `<a class="sm" href="/api/referencia/arquivo?id=${encodeURIComponent(MOD.id)}&f=com-sua-voz">Baixar vídeo com sua voz</a>` : ''}
    </div>`);
  if (j.voz) linhas.push(`<audio controls src="/api/referencia/arquivo?id=${encodeURIComponent(MOD.id)}&f=voz"></audio>`);
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
  on('mod-gravar', modGravar);
  on('mod-aplicar', modAplicarVoz);
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
}

const VIEWS_MODELADOR = {
  modelador: {
    mount: () => `<div class="card"><h2>Modelador</h2>
        <p class="small mut">Cole o link de um Reel do Instagram ou de um YouTube Shorts. O app baixa o vídeo e o texto do post, transcreve a fala, troca o áudio pela sua voz, procura o modelo 3D e monta o estúdio: fotos 1:1 em fundo branco, medidas com régua e giro de 360° em 9:16.</p>
        <div class="row" style="margin-top:8px"><input id="mod-url" type="url" placeholder="https://www.instagram.com/reel/… ou https://www.youtube.com/shorts/…" style="flex:1"><button id="mod-analisar" class="pri">Analisar</button></div>
        <div id="mod-msg" class="small mut" style="margin-top:6px"></div></div>
      <div class="card"><div id="mod-resultado"></div></div>`,
    bind: () => {
      $('mod-analisar').onclick = modAnalisar;
      $('mod-url').onkeydown = e => { if (e.key === 'Enter') modAnalisar(); };
      modDraw(); modPoll();
    },
    update: () => {},
  },
};
