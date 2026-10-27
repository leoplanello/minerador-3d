// Seleção de produtos (método do vídeo de Helton Gramari): filtros, vendas por dia, tese, famílias, funil, margem e foto real.
// Usa globais de app.js ($, esc, post, toast, price, num, load, S) só em tempo de execução.
const SEL = {
  sig: {},
  // chips de uma linha da lista de produtos
  chip(c) {
    const f = c.filtros || {};
    const out = [];
    if (f.status === 'reprovado') out.push(`<span class="chip error" title="${esc(f.reasons.join('; '))}">Reprovado: ${esc(f.reasons[0])}</span>`);
    if (c.champion) out.push(`<span class="chip ok" title="Mais de uma unidade por dia">Campeão · ${String(c.per_day).replace('.', ',')}/dia</span>`);
    else if (c.per_day != null) out.push(`<span class="chip" title="Vendidos ÷ idade do anúncio">${String(c.per_day).replace('.', ',')}/dia</span>`);
    return out.join(' ');
  },
  // ---------- Configurações: filtros de produto ----------
  async bindConfig() {
    const box = $('selconf'); if (!box) return;
    const {values: v, labels} = await (await fetch('/api/filtros')).json();
    const printers = v.printers.map(p => ({...p}));
    const draw = () => {
      box.innerHTML = `<h2>Filtros de produto</h2>
        <p class="small mut" style="margin-top:0">O que você aceita imprimir. Vale para toda a lista: o produto que não passa aparece como “Reprovado” com o motivo. Fragilidade só avisa; não bloqueia.</p>
        <div class="form">
          <label>Impressora usada nos filtros<select id="fprinter">${printers.map(p => `<option ${p.name === v.printer ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select></label>
          <div class="small mut">Volume de impressão (mm) de cada impressora. Edite ou adicione a sua.</div>
          ${printers.map((p, i) => `<div class="row" data-pr="${i}"><input class="grow" data-f="name" value="${esc(p.name)}" aria-label="Nome da impressora">
            ${['x', 'y', 'z'].map(k => `<input data-f="${k}" type="number" min="30" max="2000" value="${p[k]}" style="width:78px" aria-label="${k.toUpperCase()} em mm">`).join('')}
            <button class="sm ghost" data-delpr="${i}" ${printers.length < 2 ? 'disabled' : ''}>Remover</button></div>`).join('')}
          <div class="row"><button id="faddpr" class="sm">Adicionar impressora</button></div>
          ${['max_hours', 'min_thickness_mm', 'max_colors', 'champion_per_day'].map(k => `<label>${esc(labels[k])}<input data-k="${k}" type="number" step="0.1" min="0" value="${v[k]}"></label>`).join('')}
          <label>Cores de filamento em estoque (separe por vírgula; vazio = qualquer cor)<input id="fstock" value="${esc(v.stock_colors.join(', '))}" placeholder="preto, branco, cinza"></label>
          <label class="chk"><input type="checkbox" id="fsup" ${v.allow_support ? 'checked' : ''}> Aceito produto que precisa de suporte de impressão</label>
          <label class="chk"><input type="checkbox" id="fasm" ${v.allow_assembly ? 'checked' : ''}> Aceito produto que pede montagem ou acabamento</label>
          <div class="row"><button id="fsave" class="pri">Salvar filtros</button></div></div>`;
      box.querySelectorAll('[data-pr]').forEach(r => r.querySelectorAll('[data-f]').forEach(i => i.oninput = () => { printers[+r.dataset.pr][i.dataset.f] = i.dataset.f === 'name' ? i.value : +i.value; }));
      box.querySelectorAll('[data-delpr]').forEach(b => b.onclick = () => { printers.splice(+b.dataset.delpr, 1); if (!printers.some(p => p.name === v.printer)) v.printer = printers[0].name; draw(); });
      $('faddpr').onclick = () => { printers.push({name: 'Minha impressora', x: 256, y: 256, z: 256}); draw(); };
      $('fprinter').onchange = e => { v.printer = e.target.value; };
      $('fsave').onclick = async () => {
        const d = {printers, printer: $('fprinter').value, allow_support: $('fsup').checked, allow_assembly: $('fasm').checked, stock_colors: $('fstock').value.split(',').map(s => s.trim()).filter(Boolean)};
        box.querySelectorAll('[data-k]').forEach(i => d[i.dataset.k] = i.value);
        const r = await post('/api/filtros', d); toast(r.error || 'Filtros salvos'); if (!r.error) load(); };
    };
    draw();
  },
  // ---------- cartão do produto ----------
  render(c) {
    const el = $('selcard'); if (!el) return;
    const sig = JSON.stringify([c.filtros, c.per_day, c.age_days, c.created, c.price, c.sold]);
    if (this.sig[c.id] === sig && el.dataset.id === String(c.id)) return;       // nada mudou: não apaga o que se digita
    if (el.contains(document.activeElement) && document.activeElement.matches('input,textarea')) return;
    this.sig[c.id] = sig; el.dataset.id = c.id; el.hidden = false;
    const f = c.filtros, st = f.status, s = f.stats;
    const chipCls = st === 'reprovado' ? 'error' : st === 'aprovado' ? 'ok' : '';
    const label = {reprovado: 'Reprovado nos filtros', aprovado: 'Passou nos filtros', pendente: 'Filtros ainda não testados'}[st];
    el.innerHTML = `<div class="card-h"><h2>Filtros e vendas por dia</h2><span class="chip ${chipCls}">${label}</span></div>
      ${f.reasons.length ? `<ul class="small" style="color:var(--red);margin:0 0 8px 18px">${f.reasons.map(r => `<li>${esc(r)}</li>`).join('')}</ul>` : ''}
      ${f.warnings.length ? `<ul class="small" style="margin:0 0 8px 18px">${f.warnings.map(r => `<li>Aviso: ${esc(r)}</li>`).join('')}</ul>` : ''}
      ${f.pending.length ? `<p class="small mut" style="margin:0 0 8px">Falta testar: ${esc(f.pending.join(', '))}.</p>` : ''}
      ${s ? `<p class="small mut" style="margin:0 0 8px">Peça de ${s.dims.map(d => String(d).replace('.', ',')).join(' × ')} mm, espessura média de ${String(s.thickness).replace('.', ',')} mm.</p>` : ''}
      ${f.mesh_msg ? `<p class="small mut" style="margin:0 0 8px">${esc(f.mesh_msg)}</p>` : ''}
      <div class="row"><button id="seleval" class="sm" ${f.mesh_status === 'running' ? 'disabled' : ''}>${f.mesh_status === 'running' ? 'Testando…' : 'Medir o modelo e testar suporte'}</button>
        <span class="small mut">Mede o STL e fatia uma vez com suporte ligado.</span></div>
      <div class="sel-sales" style="margin-top:12px"><h3 style="margin:0 0 6px">Vendas por dia</h3>
        <div class="row"><label class="small">Data de publicação do anúncio<input id="selcreated" type="date" value="${esc(c.created || '')}"></label>
          <button id="selsave" class="sm">Salvar data</button></div>
        <p class="small" style="margin:6px 0">${c.per_day == null ? 'Sem a data de publicação não dá para calcular. O Mercado Livre não mostra a data na página; informe a que você vê no anúncio ou no seu complemento do navegador.'
          : `<b>${String(c.per_day).replace('.', ',')} vendas por dia</b> (${num(c.sold)} vendidos em ${num(c.age_days)} dias)${c.champion ? ' · <span class="chip ok">campeão</span>' : ''}`}</p>
        <div id="selsim" class="small mut">Procurando anúncios parecidos…</div></div>`;
    $('seleval').onclick = async () => { const r = await post('/api/filtros/avaliar', {id: c.id}); toast(r.error || 'Medindo e fatiando…'); load(); };
    $('selsave').onclick = async () => { const r = await post('/api/listing/created', {id: c.id, created: $('selcreated').value}); toast(r.error || 'Data salva'); if (!r.error) { delete this.sig[c.id]; load(); } };
    fetch('/api/similares?id=' + c.id).then(r => r.json()).then(r => { const box = $('selsim'); if (!box || r.error) return;
      const rows = r.rows.filter(x => x.id !== c.id);
      box.innerHTML = rows.length ? `<b>Anúncios parecidos lidos (${rows.length})</b>
        <table class="small" style="width:100%;margin-top:4px"><tr><th align="left">Anúncio</th><th>Idade</th><th>Vendidos</th><th>Por dia</th><th align="left">Leitura</th></tr>
        ${r.rows.map(x => `<tr><td>${esc(x.title.slice(0, 48))}${x.id === c.id ? ' (este)' : ''}</td><td align="center">${x.age_days == null ? '—' : num(x.age_days) + ' d'}</td><td align="center">${num(x.sold)}</td>
          <td align="center">${x.per_day == null ? '—' : String(x.per_day).replace('.', ',')}</td><td>${esc(x.note || '')}</td></tr>`).join('')}</table>
        ${r.price ? `<div style="margin-top:6px">Preço dos concorrentes: ${price(r.price.min)} a ${price(r.price.max)} (mediana ${price(r.price.median)}, ${r.price.n} anúncios).</div>` : ''}`
        : 'Nenhum outro anúncio parecido entre os já lidos.'; });
  },
};
