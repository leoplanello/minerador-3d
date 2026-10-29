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
        <div id="slimpbox" class="small"></div>
        <div id="slblend" class="small" style="border-top:1px solid var(--line);padding-top:10px"></div>
        <div class="row"><button id="slprev" class="pri sm">Pré-visualizar (rápido)</button><button id="slfinal" class="sm">Gerar imagem final</button>
          <label class="small">Vídeo (s)<input id="slseg" type="number" min="3" max="20" value="6" style="width:64px"></label>
          <label class="chk small"><input type="checkbox" id="slcyc"> Cycles</label><button id="slvid" class="sm">Gerar vídeo orbital</button></div>
        <p id="slest" class="small mut" style="margin:0"></p><p id="slmsg" class="small" style="margin:0"></p>
        <div class="row" style="align-items:flex-start"><img id="slimg" alt="Pré-visualização" style="max-width:360px;width:100%;border-radius:8px;${d.previa ? '' : 'display:none'}" src="${d.previa ? `/products/${c.id}/cena/previa.jpg?t=${Date.now()}` : ''}">
          <video id="slvideo" controls style="max-width:200px;${d.video ? '' : 'display:none'}" ${d.video ? `src="/products/${c.id}/cena/video.mp4?t=${Date.now()}"` : ''}></video></div>
        <p class="small mut" style="margin:6px 0 0">Salas importadas (CGTrader, modelos gratuitos): ${(d.importadas || []).map(m => `“${esc(m.titulo)}” por ${esc(m.autor)} (<a href="${esc(m.pagina)}" target="_blank" rel="noopener">CGTrader</a>)`).join('; ')}. ${esc(d.creditos || '')} Móveis das salas padrão: Poly Haven, CC0.</p></div>`;
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
    $('sl_ambiente').addEventListener('change', () => this.imp(c));
    this.imp(c);
    this.blend(c);
  },
  // sala importada (GLB/FBX de terceiros): baixa na primeira vez que for escolhida, com tamanho, progresso e retomada
  imp(c) {
    const box = $('slimpbox'); if (!box) return;
    const id = $('sl_ambiente').value, m = (this.data.importadas || []).find(x => x.id === id);
    const falta = !!m && !m.instalada, j = m && m.job, rodando = !!j && j.status === 'running';
    ['slprev', 'slfinal', 'slvid', 'slmake'].forEach(b => { const e = $(b); if (e) e.disabled = falta; });
    clearTimeout(this.ti);
    if (!m) { box.innerHTML = ''; return; }
    if (m.instalada) { box.innerHTML = `<span class="chip ok">Sala baixada</span> “${esc(m.titulo)}” de ${esc(m.autor)}. Sala grande: a pré-visualização usa até ${m.ram_gb} GB de memória e demora ${m.ram_gb > 6 ? 'cerca de 2 a 4 minutos' : 'cerca de 1 minuto'} (carregar a sala é o que leva tempo).`; return; }
    const pct = j && j.total ? Math.round(100 * j.done / j.total) : 0, mb = x => Math.round(x / 1048576);
    box.innerHTML = rodando ? `<b>${j.stage === 'baixando' ? 'Baixando' : j.stage === 'conferindo' ? 'Conferindo o arquivo' : 'Instalando'} ${esc(m.label)}</b>: ${pct}% (${mb(j.done)} de ${mb(j.total)} MB). Pode fechar esta tela; se a internet cair, é só baixar de novo que continua de onde parou.`
      : `Essa sala (${esc(m.label)}) tem <b>${m.size_mb} MB</b> e é baixada uma vez, da página de downloads do projeto no GitHub. ${j && j.status === 'error' ? `<span style="color:var(--red)">${esc(j.msg)}</span> ` : ''}<button id="sldl" class="sm pri">${j && j.status === 'error' ? 'Tentar de novo' : `Baixar (${m.size_mb} MB)`}</button>`;
    if ($('sldl')) $('sldl').onclick = async () => { const r = await post('/api/salas/baixar', {id}); if (r.error) return toast(r.error); await this.refresh(c); };
    if (rodando) this.ti = setTimeout(() => this.refresh(c), 2000);
  },
  async refresh(c) {
    this.data = await (await fetch('/api/cena?id=' + c.id)).json();
    if ($('slimpbox')) this.imp(c);
  },
  // sala editável: o app gera a sala.blend, abre o Blender, e as imagens e o vídeo saem do arquivo salvo
  async blend(c) {
    const box = $('slblend'); if (!box) return;
    const d = this.data = await (await fetch('/api/cena?id=' + c.id)).json(), s = d.sala, j = d.job;
    $('sl_ambiente') && ['ambiente', 'colocacao', 'referencia', 'luz', 'escala', 'giro'].forEach(k => { const e = $('sl_' + k); if (e) e.disabled = s.existe; });
    const ocupado = j && j.status === 'running';
    box.innerHTML = !s.existe
      ? `<b>Editar a sala no Blender</b>
         <p class="mut" style="margin:4px 0">Monta a sala com as opções acima e cria um arquivo <code>sala.blend</code> com cada móvel solto. Você abre no Blender, move tudo do seu jeito, salva e fecha. As imagens e o vídeo passam a sair desse arquivo.</p>
         <button id="slmake" class="sm" ${ocupado ? 'disabled' : ''}>Montar a sala para editar</button> <span id="slbmsg" class="mut">${ocupado ? esc(j.msg) : ''}</span>`
      : `<b>Sala editável</b> <span class="chip ${s.aberto ? '' : 'ok'}">${s.aberto ? 'Aberta no Blender: salve (Ctrl+S) e feche a janela' : 'Salva ' + esc(s.salvo_em.replace('T', ' ')) + ' (' + s.tamanho_mb + ' MB)'}</span>
         <p class="mut" style="margin:4px 0">As opções de ambiente, lugar, escala, giro e luz valem só para montar a sala; depois, o que vale é o arquivo. Imagens e vídeo usam a câmera e a luz salvas nele. No Blender: <b>G</b> move, <b>R</b> gira, <b>S</b> muda o tamanho, <b>Ctrl+S</b> salva. Ao fechar, o app usa o arquivo salvo.</p>
         <div class="row"><button id="slopen" class="pri sm" ${s.aberto || ocupado ? 'disabled' : ''}>Abrir sala no Blender</button>
           <button id="slredo" class="ghost sm" ${s.aberto || ocupado ? 'disabled' : ''} title="Cria a sala de novo com as opções acima. O arquivo atual fica guardado como sala-anterior.">Refazer a sala do zero</button></div>
         <div class="row" style="margin-top:6px"><label>Adicionar móvel do catálogo (Poly Haven, CC0)
             <select id="slcat"><option value="furniture">Móveis</option><option value="decorative">Decoração</option><option value="plants">Plantas</option><option value="lighting">Luminárias</option><option value="shelves">Prateleiras</option><option value="electronics">Eletrônicos</option></select></label>
           <select id="slitem" aria-label="Móvel"><option value="">carregando…</option></select><button id="sladd" class="sm" ${s.aberto || ocupado ? 'disabled' : ''}>Adicionar à sala</button></div>
         <div class="row" style="margin-top:6px"><label>Importar meus modelos (.glb, .stl, .3mf, .blend) <input id="slimp" type="file" accept=".glb,.gltf,.stl,.3mf,.blend"></label></div>
         <p class="mut" style="margin:4px 0">${s.objetos.length ? 'Na sala: ' + s.objetos.map(o => esc(o.id)).join(', ') + '.' : ''} O que você adiciona aparece no chão, à frente da câmera; abra o Blender para posicionar.</p>
         <span id="slbmsg" class="mut">${j && j.kind === 'sala' ? esc(j.msg) : ''}</span>`;
    const msg = t => { $('slbmsg').textContent = t; };
    if ($('slmake')) $('slmake').onclick = async () => { const r = await post('/api/cena/sala/gerar', {id: c.id, cena: this.get(), refazer: false}); if (r.error) return toast(r.error); msg('Montando a sala…'); this.poll(c); };
    if ($('slredo')) $('slredo').onclick = async () => { if (!confirm('Criar a sala de novo? O arquivo atual fica guardado como sala-anterior.')) return;
      const r = await post('/api/cena/sala/gerar', {id: c.id, cena: this.get(), refazer: true}); if (r.error) return toast(r.error); this.poll(c); };
    if ($('slopen')) $('slopen').onclick = async () => { const r = await post('/api/cena/sala/abrir', {id: c.id}); if (r.error) return toast(r.error); toast('Abrindo o Blender…'); setTimeout(() => this.poll(c), 1500); };
    if ($('slcat')) {
      const fill = async () => { const r = await (await fetch('/api/cena/catalogo?cat=' + $('slcat').value)).json();
        $('slitem').innerHTML = r.error ? `<option value="">${esc(r.error)}</option>` : r.itens.map(i => `<option value="${esc(i.id)}">${esc(i.nome)}${i.dimensoes_mm.length ? ' (' + i.dimensoes_mm.slice(0, 3).join('×') + ' mm)' : ''}</option>`).join(''); };
      $('slcat').onchange = fill; fill();
      $('sladd').onclick = async () => { if (!$('slitem').value) return; const r = await post('/api/cena/sala/adicionar', {id: c.id, itens: [{fonte: 'polyhaven:' + $('slitem').value}]}); if (r.error) return toast(r.error); msg('Baixando e adicionando…'); this.poll(c); };
      $('slimp').onchange = async e => { const f = e.target.files[0]; if (!f) return; msg('Enviando o modelo…');
        const up = await (await fetch(`/api/cena/sala/importar?id=${c.id}&name=${encodeURIComponent(f.name)}`, {method: 'POST', body: f})).json(); if (up.error) return toast(up.error);
        const r = await post('/api/cena/sala/adicionar', {id: c.id, itens: [{fonte: up.fonte}]}); if (r.error) return toast(r.error); this.poll(c); };
    }
    this.imp(c);
    if (s.aberto) { clearTimeout(this.tb); this.tb = setTimeout(() => this.blend(c), 4000); }  // quando o Blender fecha, o estado volta sozinho
  },
  poll(c) {
    clearTimeout(this.t);
    const go = async () => { const d = await (await fetch('/api/cena?id=' + c.id)).json(), j = d.job; if (!$('slmsg')) return;
      if (j && j.status === 'running') { $('slmsg').textContent = j.msg; this.t = setTimeout(go, 3000); return; }
      this.blend(c);
      if (j) { $('slmsg').textContent = j.msg; if (j.status === 'ok') { if (j.kind === 'video') { const v = $('slvideo'); v.style.display = ''; v.src = `/products/${c.id}/cena/video.mp4?t=${Date.now()}`; } load(); } } };
    go();
  },
};
