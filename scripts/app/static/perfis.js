// Perfis do Chrome: os do app (onde você entra nas contas) e, só para consulta, os do seu Chrome. O app nunca copia senha nem cookie.
const PERFIS = {
  data: null,
  async load() { this.data = await (await fetch('/api/perfis')).json(); this.draw(); },
  async bind() { const box = $('perfcard'); if (!box) return; await this.load();
    clearInterval(this.t); this.t = setInterval(() => { if (!$('perfcard')) return clearInterval(this.t); if ((this.data.app || []).some(p => p.login && p.login.estado === 'aberto')) this.load(); }, 4000); },
  // dropdown do topo: perfis do app e, por último, "+ Adicionar perfil"; sem perfil nenhum, só o botão grande
  menu(force) {
    const sel = $('profile'), names = S.profiles;
    if (force || sel.options.length !== names.length) {
      const saved = store('profile'), cur = names.includes(saved) ? saved : names[0];
      sel.innerHTML = names.map(p => `<option ${p === cur ? 'selected' : ''}>${esc(p)}</option>`).join('');
      $('profpop').innerHTML = names.map(p => `<button data-p="${esc(p)}" aria-current="${p === sel.value}">${esc(p)}</button>`).join('') + '<button class="add" data-add="1">+ Adicionar perfil</button>';
      $('profbtn').textContent = sel.value;
    }
    $('profbig').hidden = names.length > 0; $('profbtn').hidden = !names.length;
    if (!names.length) $('profpop').hidden = true;
  },
  async dialog() {
    if (!this.data) this.data = await (await fetch('/api/perfis')).json();
    const old = $('pfdlg'); if (old) old.remove();
    const d = document.createElement('dialog'); d.id = 'pfdlg';
    d.innerHTML = `<h2 style="margin-top:0">Adicionar perfil do Chrome</h2>
      <p class="small mut">Abre uma janela nova do Chrome só desse perfil, na página de login. Entre e feche a janela: o perfil fica salvo na lista. Nenhuma senha nem cookie de outro perfil é copiado.</p>
      <div class="form"><label class="small">Apelido<input id="pdnick" maxlength="40" placeholder="ex.: Loja principal" autofocus></label>
        <label class="small">Entrar em<select id="pdserv">${Object.entries(this.data.servicos).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join('')}</select></label>
        <div class="row"><button id="pdok" class="pri">Abrir o Chrome para entrar</button><button id="pdcancel" class="ghost">Cancelar</button></div></div>`;
    document.body.appendChild(d); d.showModal();
    $('pdcancel').onclick = () => d.close();
    $('pdok').onclick = async () => { const r = await post('/api/perfis/adicionar', {apelido: $('pdnick').value, servico: $('pdserv').value}); if (r.error) return toast(r.error);
      d.close(); toast('Chrome aberto. Entre na conta e feche a janela.'); await this.load(); load(); };
  },
  draw() {
    const box = $('perfcard'); if (!box || !this.data) return;
    const d = this.data, cur = $('profile') && $('profile').value;
    box.innerHTML = `<h2>Perfis do Chrome</h2>
      <p class="small mut" style="margin-top:0">A leitura de lojas e a busca de modelos usam um <b>perfil do app</b>: uma pasta só do Minerador 3D, onde você entra nas contas uma vez. Nenhuma senha nem cookie de outro perfil é copiado.</p>
      <h3 style="margin:8px 0 4px">Perfis do app</h3>
      ${d.app.length ? d.app.map(p => `<div class="row" style="align-items:center"><span class="grow"><b>${esc(p.apelido)}</b>${p.dedicado ? '' : ' <span class="small mut">(perfil antigo)</span>'}
          ${p.login ? `<span class="chip ${p.login.estado === 'pronto' ? 'ok' : ''}">${p.login.estado === 'aberto' ? 'Chrome aberto em ' + esc(p.login.servico) + ': entre na conta e feche a janela' : 'Pronto (' + esc(p.login.servico) + ')'}</span>` : ''}
          ${p.nome === cur ? ' <span class="chip ok">em uso</span>' : ''}</span>
          <button class="sm ${p.nome === cur ? 'ghost' : ''}" data-use="${esc(p.nome)}" ${p.nome === cur ? 'disabled' : ''}>Usar este</button></div>`).join('') : '<p class="small mut">Nenhum perfil do app ainda.</p>'}
      <h3 style="margin:12px 0 4px">Adicionar perfil</h3>
      <div class="row"><label class="small grow">Apelido<input id="pfnick" maxlength="40" placeholder="ex.: Loja principal"></label>
        <label class="small">Entrar em<select id="pfserv">${Object.entries(d.servicos).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join('')}</select></label>
        <button id="pfadd" class="pri sm">Abrir o Chrome para entrar</button></div>
      <p class="small mut" style="margin:4px 0">Abre uma janela nova do Chrome só desse perfil, na página de login. Entre e feche a janela: o perfil fica salvo na lista.</p>
      <details style="margin-top:12px"><summary class="small"><b>Perfis do seu Chrome</b> (${d.chrome.length}, só consulta)</summary>
        <p class="small mut">Desde o Chrome 136 o Chrome não deixa programas controlarem a pasta padrão dele, então o app não consegue usar estes perfis diretamente. Use o botão para criar um perfil do app com o mesmo nome e entrar nas contas nele.</p>
        ${d.chrome.map(p => `<div class="row small" style="align-items:center"><span class="grow"><b>${esc(p.nome)}</b> <span class="mut">${esc(p.email || p.conta || p.pasta)}${p.ultimo ? ' · o último que você usou' : ''}</span></span>
          <button class="sm ghost" data-clone="${esc(p.nome)}">Criar perfil do app com este nome</button></div>`).join('') || '<p class="small mut">Não achei a pasta do Chrome.</p>'}</details>`;
    box.querySelectorAll('[data-use]').forEach(b => b.onclick = () => { const s = $('profile'); s.value = b.dataset.use; s.dispatchEvent(new Event('change')); this.draw(); });
    box.querySelectorAll('[data-clone]').forEach(b => b.onclick = () => { $('pfnick').value = b.dataset.clone; $('pfnick').focus(); });
    $('pfadd').onclick = async () => { const r = await post('/api/perfis/adicionar', {apelido: $('pfnick').value, servico: $('pfserv').value}); if (r.error) return toast(r.error);
      toast('Chrome aberto. Entre na conta e feche a janela.'); await this.load(); load(); };
  },
};

// dropdown do topo: abrir e fechar, escolher um perfil ou adicionar (a opção extra nunca vira o perfil escolhido)
document.addEventListener('click', e => {
  const pop = $('profpop'); if (!pop) return;
  if (e.target.closest('#profbig')) return PERFIS.dialog();
  if (e.target.closest('#profbtn')) { pop.hidden = !pop.hidden; $('profbtn').setAttribute('aria-expanded', String(!pop.hidden)); return; }
  const b = e.target.closest('#profpop button');
  if (b) { pop.hidden = true; if (b.dataset.add) return PERFIS.dialog(); const s = $('profile'); s.value = b.dataset.p; s.dispatchEvent(new Event('change')); return; }
  pop.hidden = true;
});
