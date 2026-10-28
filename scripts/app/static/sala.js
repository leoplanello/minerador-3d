// Sala virtual: coloca qualquer modelo (o do produto ou um arquivo enviado) num ambiente 3D com materiais, móveis e luz do Poly Haven (CC0),
// e gera imagem e vídeo. Pré-visualização rápida em EEVEE antes do render final em Cycles.
const SALA = {
  id: null, data: null, busy: false,
  L: {ambiente: 'Ambiente', colocacao: 'Onde a peça fica', referencia: 'Objeto de referência (para ver a escala)', camera: 'Câmera', luz: 'Luz'},
  V: {colocacao: {chao: 'No chão', mesa: 'Sobre a mesa ou móvel', parede: 'Na parede', prateleira: 'Numa prateleira'}, referencia: {nenhuma: 'Nenhum', moeda: 'Moeda (27 mm)', caneca: 'Caneca (8 × 9,5 cm)', celular: 'Celular (15 cm)'},
      camera: {'3/4': 'Três quartos', frontal: 'Frontal', close: 'Close', orbital: 'Orbital (só no vídeo)'}, luz: {dia: 'Dia', tarde: 'Tarde', noite: 'Noite'}},
  async show(c) {
    const el = $('salacard'); if (!el) return;
    if (c.status !== 'approved') { el.hidden = true; return; }
    el.hidden = false;
    if (this.id === c.id && el.dataset.built) return;
    this.id = c.id; el.dataset.built = 1;
    this.data = await (await fetch('/api/cena?id=' + c.id)).json();
    this.draw(c);
  },
  get() {
    const q = k => $('sl_' + k).value;
    return {ambiente: q('ambiente'), colocacao: q('colocacao'), escala_pct: q('escala'), giro: q('giro'), referencia: q('referencia'), camera: q('camera'), luz: q('luz'), modelo: document.querySelector('[name=slmod]:checked').value};
  },
  draw(c) {
    const d = this.data, v = d.cena, sel = (k, opts, labels) => `<label class="small">${this.L[k]}<select id="sl_${k}">${opts.map(o => `<option value="${esc(o)}" ${o === v[k] ? 'selected' : ''}>${esc(labels[o] || o)}</option>`).join('')}</select></label>`;
    const maior = c.filtros && c.filtros.stats ? c.filtros.stats.dims[0] : null;
    $('salacard').innerHTML = `<div class="card-h"><h2>Sala virtual</h2><span class="small mut">qualquer modelo, num ambiente de casa de verdade</span></div>
      <p class="small mut" style="margin:0 0 8px">Escolha o ambiente e onde a peça fica, confira na pré-visualização (alguns segundos) e só então gere a imagem final ou o vídeo. A imagem final vai para as imagens do produto.</p>
      <div class="form">
        <div class="row">${sel('ambiente', Object.keys(d.ambientes), d.ambientes)}${sel('colocacao', d.opcoes.colocacao, this.V.colocacao)}${sel('referencia', d.opcoes.referencia, this.V.referencia)}</div>
        <div class="row">${sel('camera', d.opcoes.camera, this.V.camera)}${sel('luz', d.opcoes.luz, this.V.luz)}</div>
        <div class="row"><label class="small grow">Escala: <b id="sl_escv">${v.escala_pct}%</b>${maior ? ` <span class="mut">(maior lado ${String(Math.round(maior * v.escala_pct / 10) / 10).replace('.', ',')} mm)</span>` : ''}
            <input id="sl_escala" type="range" min="10" max="500" step="5" value="${v.escala_pct}"></label>
          <label class="small grow">Giro: <b id="sl_girov">${v.giro}°</b><input id="sl_giro" type="range" min="0" max="355" step="5" value="${v.giro}"></label></div>
        <div class="row small"><span>Modelo:</span><label class="chk"><input type="radio" name="slmod" value="produto" ${v.modelo !== 'enviado' ? 'checked' : ''}> do produto</label>
          <label class="chk"><input type="radio" name="slmod" value="enviado" ${v.modelo === 'enviado' ? 'checked' : ''}> um arquivo só para a cena ${d.modelo_enviado ? `(${esc(d.modelo_enviado)})` : ''}</label>
          <input id="slfile" type="file" accept=".stl,.3mf"></div>
        <div class="row"><button id="slprev" class="pri sm">Pré-visualizar (rápido)</button><button id="slfinal" class="sm">Gerar imagem final</button>
          <label class="small">Vídeo (s)<input id="slseg" type="number" min="3" max="20" value="6" style="width:64px"></label>
          <label class="chk small"><input type="checkbox" id="slcyc"> Cycles</label><button id="slvid" class="sm">Gerar vídeo orbital</button></div>
        <p id="slest" class="small mut" style="margin:0"></p><p id="slmsg" class="small" style="margin:0"></p>
        <div class="row" style="align-items:flex-start"><img id="slimg" alt="Pré-visualização" style="max-width:360px;width:100%;border-radius:8px;${d.previa ? '' : 'display:none'}" src="${d.previa ? `/products/${c.id}/cena/previa.jpg?t=${Date.now()}` : ''}">
          <video id="slvideo" controls style="max-width:200px;${d.video ? '' : 'display:none'}" ${d.video ? `src="/products/${c.id}/cena/video.mp4?t=${Date.now()}"` : ''}></video></div></div>`;
    const upd = () => { $('sl_escv').textContent = $('sl_escala').value + '%'; $('sl_girov').textContent = $('sl_giro').value + '°';
      const s = +$('slseg').value || 6, cy = $('slcyc').checked;
      $('slest').textContent = cy ? `Vídeo em Cycles: ${s * 24} quadros, cerca de ${Math.round(s * 24 * 55 / 60)} min nesta máquina (pesado). A pré-visualização e a imagem final são mais rápidas.`
        : `Vídeo em EEVEE: ${s * 24} quadros, cerca de ${Math.max(1, Math.round(s * 24 * 2.5 / 60))} min.`; };
    $('salacard').oninput = upd; upd();
    $('slfile').onchange = async e => { const f = e.target.files[0]; if (!f) return;
      const r = await (await fetch(`/api/cena/modelo?id=${c.id}&name=${encodeURIComponent(f.name)}`, {method: 'POST', body: f})).json();
      toast(r.error || 'Arquivo guardado para a sala virtual'); if (!r.error) document.querySelector('[name=slmod][value=enviado]').checked = true; };
    const run = async (btn, url, extra, okMsg) => { if (this.busy) return; this.busy = true; btn.disabled = true; $('slmsg').textContent = 'Trabalhando…';
      const r = await post(url, {id: c.id, cena: this.get(), ...extra}); this.busy = false; btn.disabled = false;
      if (r.error) { $('slmsg').textContent = r.error; toast(r.error); return null; }
      $('slmsg').textContent = okMsg; return r; };
    $('slprev').onclick = async () => { const r = await run($('slprev'), '/api/cena/previa', {}, 'Pré-visualização pronta.'); if (r) { const im = $('slimg'); im.style.display = ''; im.src = r.url; } };
    $('slfinal').onclick = async () => { const r = await run($('slfinal'), '/api/cena/render', {}, 'Renderizando a imagem final em Cycles (alguns minutos)…'); if (r) this.poll(c); };
    $('slvid').onclick = async () => { const r = await run($('slvid'), '/api/cena/video', {segundos: +$('slseg').value || 6, motor: $('slcyc').checked ? 'cycles' : 'eevee'}, 'Renderizando os quadros do vídeo…'); if (r) this.poll(c); };
  },
  poll(c) {
    clearTimeout(this.t);
    const go = async () => { const d = await (await fetch('/api/cena?id=' + c.id)).json(), j = d.job; if (!$('slmsg')) return;
      if (j && j.status === 'running') { $('slmsg').textContent = j.msg; this.t = setTimeout(go, 3000); return; }
      if (j) { $('slmsg').textContent = j.msg; if (j.status === 'ok') { if (j.kind === 'video') { const v = $('slvideo'); v.style.display = ''; v.src = `/products/${c.id}/cena/video.mp4?t=${Date.now()}`; } load(); } } };
    go();
  },
};
