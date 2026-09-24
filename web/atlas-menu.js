/* Atlas da República — menu geral (MIT). Injeta um botão fixo no canto superior direito e uma gaveta
   com tudo o que o site faz: explorar, acompanhar, dados, ajustes da roda e como participar.
   Funciona em qualquer página do site (home, guia, comparador, dados, metodologia): o que não existe
   na página vira um link normal; o que existe (abas da home, modos da roda, tema) age na própria página. */
(function () {
  'use strict';
  if (typeof document === 'undefined' || document.getElementById('atlas-menu')) return;
  var P = (window.ATLAS_PREFIX || '');           // prefixo de caminho (prévia publicada em subpasta)
  var isHome = !!document.getElementById('graph');
  var u = function (p) { return P + p; };

  var SECTIONS = [
    { h: 'Explorar', items: [
      { t: 'Roda do governo federal', d: 'Todos os órgãos, cargos e colegiados da União', href: u('/'), act: 'home' },
      { t: 'Buscar', d: 'Órgão, cargo, pessoa, sigla ou combinação', act: 'busca', href: u('/') },
      { t: 'Do zero', d: 'O governo explicado em palavras simples, para quem nunca estudou isso', href: u('/do-zero/') },
      { t: 'Como funciona a República', d: 'Visita guiada de 9 minutos pela roda', href: u('/como-funciona/') },
      { t: 'Comparar parlamentares', d: 'Rankings e comparação lado a lado', href: u('/comparar/') }
    ] },
    { h: 'Acompanhar', items: [
      { t: 'O que mudou', d: 'Posses, saídas, sabatinas e a transição de 2027', act: 'tab:mudou', href: u('/') },
      { t: 'O que está parado', d: 'Medidas provisórias, vetos, pedidos de CPI e temas', act: 'tab:parado', href: u('/') },
      { t: 'Para onde vai o dinheiro', d: 'Arrecadação, emendas, renúncias, viagens e cartão', act: 'tab:dinheiro', href: u('/') },
      { t: 'Na imprensa', d: 'Notícias do dia e quem mais é citado', act: 'tab:imprensa', href: u('/') }
    ] },
    { h: 'Receber por RSS', items: [
      { t: 'Mudanças de ocupante', href: u('/feeds/mudancas.xml'), ext: true },
      { t: 'Prazos que vencem', href: u('/feeds/prazos.xml'), ext: true },
      { t: 'Temas em acompanhamento', href: u('/feeds/temas.xml'), ext: true },
      { t: 'Notícias', href: u('/feeds/noticias.xml'), ext: true }
    ] },
    { h: 'Dados e método', items: [
      { t: 'Dados abertos', d: 'Planilhas e JSON de tudo que o site mostra, CC BY 4.0', href: u('/dados/') },
      { t: 'Metodologia', d: 'Fonte, regra e limite de cada bloco', href: u('/metodologia/') }
    ] },
    { h: 'A roda', items: [
      { t: 'Movimento', d: 'Como a roda responde ao clique', act: 'modo', home: true },
      { t: 'Tema', d: 'Automático, claro ou escuro', act: 'tema' },
      { t: 'O que significam anéis e formas', d: 'Convenções de leitura', act: 'legenda', home: true }
    ] },
    { h: 'Participar', items: [
      { t: 'Corrigir um dado', d: 'Abre um issue com a página e o campo', href: 'https://github.com/culturabuilder/atlas-da-republica/issues/new?labels=correcao&title=Corre%C3%A7%C3%A3o%3A%20', ext: true },
      { t: 'Pedir o grafo do seu estado ou cidade', href: 'https://github.com/culturabuilder/atlas-da-republica/issues/new?title=Pe%C3%A7o%20um%20grafo%3A%20', ext: true },
      { t: 'Código e dados no GitHub', href: 'https://github.com/culturabuilder/atlas-da-republica', ext: true },
      { t: 'Projeto apartidário e aberto', d: 'Sem partido, sem ideologia, sem financiamento de campanha', href: u('/metodologia/') }
    ] }
  ];

  var css = document.createElement('style');
  css.textContent =
    '.menu-btn{position:fixed;top:calc(env(safe-area-inset-top,0px) + 14px);right:14px;z-index:30;display:inline-flex;align-items:center;gap:7px;font:600 13.5px var(--sans,system-ui,sans-serif);color:var(--ink,#111);background:var(--card,#fff);border:1px solid var(--line,#ccc);border-radius:999px;padding:9px 14px;cursor:pointer;box-shadow:0 2px 10px rgba(0,0,0,.10)}' +
    '.menu-btn:hover{border-color:var(--accent,#1F5F4A)}.menu-btn:focus-visible{outline:2px solid var(--focus,#1F5F4A);outline-offset:2px}' +
    '.menu-btn .bars{display:inline-block;width:14px;height:10px;border-top:2px solid currentColor;border-bottom:2px solid currentColor;position:relative}.menu-btn .bars:after{content:"";position:absolute;left:0;top:3px;width:14px;height:2px;background:currentColor}' +
    '.menu-scrim{position:fixed;inset:0;background:rgba(0,0,0,.42);z-index:40;opacity:0;transition:opacity .18s}.menu-scrim.on{opacity:1}' +
    '.menu-drawer{position:fixed;top:0;right:0;bottom:0;width:min(380px,92vw);background:var(--panel,#fff);border-left:1px solid var(--line,#ccc);z-index:41;display:flex;flex-direction:column;transform:translateX(100%);transition:transform .22s ease;padding-bottom:env(safe-area-inset-bottom,0px)}' +
    '.menu-drawer.on{transform:none}.menu-drawer[hidden],.menu-scrim[hidden]{display:none!important}@media (prefers-reduced-motion:reduce){.menu-drawer,.menu-scrim{transition:none}}' +
    '.menu-drawer header{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:14px 16px;border-bottom:1px solid var(--line-2,#eee)}' +
    '.menu-drawer header b{font:700 16px var(--disp,system-ui,sans-serif)}' +
    '.menu-x{font:inherit;font-size:20px;line-height:1;background:none;border:1px solid var(--line,#ccc);border-radius:8px;color:var(--ink-2,#444);width:36px;height:36px;cursor:pointer}' +
    '.menu-x:focus-visible{outline:2px solid var(--focus,#1F5F4A)}' +
    '.menu-body{overflow-y:auto;padding:8px 10px 24px;-webkit-overflow-scrolling:touch}' +
    '.menu-body h3{font:600 11px var(--mono,monospace);letter-spacing:.12em;text-transform:uppercase;color:var(--ink-3,#777);margin:16px 8px 6px}' +
    '.menu-body a.mi,.menu-body button.mi{display:block;width:100%;text-align:left;font:inherit;background:none;border:0;border-radius:9px;padding:9px 10px;color:var(--ink,#111);text-decoration:none;cursor:pointer}' +
    '.menu-body .mi:hover{background:var(--accent-soft,#eee)}.menu-body .mi:focus-visible{outline:2px solid var(--focus,#1F5F4A);outline-offset:-2px}' +
    '.menu-body .mi b{display:block;font-weight:600;font-size:14.5px;line-height:1.25}.menu-body .mi span{display:block;font-size:12.5px;color:var(--ink-3,#777);line-height:1.35;margin-top:1px}' +
    '.menu-body .mi .ext{display:inline;color:var(--ink-3,#777);font-size:12px}' +
    '.menu-seg{display:flex;gap:4px;margin:2px 10px 4px;flex-wrap:wrap}' +
    '.menu-seg button{font:inherit;font-size:12.5px;padding:7px 10px;border:1px solid var(--line,#ccc);border-radius:999px;background:var(--card,#fff);color:var(--ink-2,#444);cursor:pointer}' +
    '.menu-seg button[aria-pressed=true]{background:var(--accent,#1F5F4A);border-color:var(--accent,#1F5F4A);color:var(--card,#fff)}' +
    '.menu-seg button:focus-visible{outline:2px solid var(--focus,#1F5F4A);outline-offset:2px}' +
    '.menu-foot{font-size:12px;color:var(--ink-3,#777);padding:14px 12px 0;border-top:1px solid var(--line-2,#eee);margin:14px 6px 0}' +
    'body.has-menu .topbar{right:132px}@media (max-width:900px){body.has-menu .topbar{right:auto}body.has-menu .brand{padding-right:104px}.menu-btn{padding:8px 12px}}';
  document.head.appendChild(css);
  document.body.classList.add('has-menu');

  var btn = document.createElement('button');
  btn.type = 'button'; btn.className = 'menu-btn'; btn.id = 'atlas-menu';
  btn.setAttribute('aria-haspopup', 'dialog'); btn.setAttribute('aria-expanded', 'false');
  btn.innerHTML = '<span class="bars" aria-hidden="true"></span>Menu';
  document.body.appendChild(btn);

  var scrim = document.createElement('div'); scrim.className = 'menu-scrim'; scrim.hidden = true;
  var drawer = document.createElement('div'); drawer.className = 'menu-drawer'; drawer.hidden = true;
  drawer.setAttribute('role', 'dialog'); drawer.setAttribute('aria-modal', 'true'); drawer.setAttribute('aria-label', 'Menu do Atlas');

  function item(it) {
    var inner = '<b>' + it.t + (it.ext ? ' <span class="ext">↗</span>' : '') + '</b>' + (it.d ? '<span>' + it.d + '</span>' : '');
    if (it.act) return '<button type="button" class="mi" data-act="' + it.act + '"' + (it.href ? ' data-href="' + it.href + '"' : '') + '>' + inner + '</button>';
    return '<a class="mi" href="' + it.href + '"' + (it.ext ? ' target="_blank" rel="noopener"' : '') + '>' + inner + '</a>';
  }
  var html = '<header><b>Tudo o que dá para fazer aqui</b><button type="button" class="menu-x" aria-label="Fechar menu">×</button></header><div class="menu-body">';
  SECTIONS.forEach(function (s) {
    var items = s.items.filter(function (it) { return !it.home || isHome; });
    if (!items.length) return;
    html += '<h3>' + s.h + '</h3>' + items.map(item).join('');
    if (s.h === 'A roda' && isHome) html += '<div class="menu-seg" id="menu-modo" role="group" aria-label="Movimento da roda"></div><div class="menu-seg" id="menu-tema" role="group" aria-label="Tema"></div>';
  });
  html += '<p class="menu-foot">Dados públicos com a fonte ao lado de cada número. Texto e código sob licença aberta; dados sob CC BY 4.0.</p></div>';
  drawer.innerHTML = html;
  document.body.appendChild(scrim); document.body.appendChild(drawer);

  // botões de movimento e tema espelham os controles da página
  function seg(hostId, defs) {
    var host = drawer.querySelector('#' + hostId); if (!host) return;
    host.innerHTML = defs.map(function (d) { return '<button type="button" data-v="' + d[0] + '" aria-pressed="false">' + d[1] + '</button>'; }).join('');
  }
  function syncSegs() {
    var m = drawer.querySelector('#menu-modo');
    if (m && window.AtlasCamera) m.querySelectorAll('[data-v]').forEach(function (b) { b.setAttribute('aria-pressed', String(window.AtlasCamera.state.mode === b.dataset.v)); });
    var t = drawer.querySelector('#menu-tema');
    if (t) { var cur = document.documentElement.dataset.theme || 'auto'; t.querySelectorAll('[data-v]').forEach(function (b) { b.setAttribute('aria-pressed', String(cur === b.dataset.v)); }); }
  }
  if (isHome) {
    seg('menu-modo', [['none', 'Sem movimento'], ['focus', 'Foco suave'], ['rotate', 'Rotação']]);
    seg('menu-tema', [['auto', 'Tema automático'], ['light', 'Claro'], ['dark', 'Escuro']]);
  }

  var lastFocus = null;
  function open() {
    lastFocus = document.activeElement;
    scrim.hidden = false; drawer.hidden = false; btn.setAttribute('aria-expanded', 'true');
    requestAnimationFrame(function () { scrim.classList.add('on'); drawer.classList.add('on'); });
    syncSegs(); drawer.querySelector('.menu-x').focus();
    document.addEventListener('keydown', onKey, true);
  }
  function close() {
    scrim.classList.remove('on'); drawer.classList.remove('on'); btn.setAttribute('aria-expanded', 'false');
    document.removeEventListener('keydown', onKey, true);
    setTimeout(function () { scrim.hidden = true; drawer.hidden = true; }, 200);
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }
  function onKey(e) {
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); return; }
    if (e.key !== 'Tab') return;
    var f = [].slice.call(drawer.querySelectorAll('a[href],button:not([disabled])')).filter(function (el) { return el.offsetParent !== null; });
    if (!f.length) return; var first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }
  btn.addEventListener('click', function () { drawer.hidden ? open() : close(); });
  scrim.addEventListener('click', close);
  drawer.querySelector('.menu-x').addEventListener('click', close);

  drawer.addEventListener('click', function (e) {
    var seg = e.target.closest('.menu-seg [data-v]');
    if (seg) {
      var host = seg.closest('.menu-seg').id;
      if (host === 'menu-modo' && window.AtlasCamera) window.AtlasCamera.setMode(seg.dataset.v);
      if (host === 'menu-tema') { var v = seg.dataset.v; if (v === 'auto') delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = v; try { localStorage.setItem('atlas-theme', v); } catch (err) {} }
      syncSegs(); return;
    }
    var mi = e.target.closest('.mi[data-act]'); if (!mi) { if (e.target.closest('a.mi')) close(); return; }
    var act = mi.dataset.act;
    if (!isHome && mi.dataset.href) { // fora da home, as ações viram navegação com âncora
      location.href = mi.dataset.href + (act.indexOf('tab:') === 0 ? '#painel=' + act.slice(4) : ''); return;
    }
    close();
    if (act === 'home') { if (location.hash) location.hash = ''; window.scrollTo({ top: 0, behavior: 'smooth' }); }
    else if (act === 'busca') { if (location.hash) location.hash = ''; var q = document.getElementById('q'); if (q) { q.scrollIntoView({ block: 'center' }); q.focus(); } }
    else if (act.indexOf('tab:') === 0) { if (location.hash) location.hash = ''; setTimeout(function () { var t = document.getElementById('tab-' + act.slice(4)); if (t) { t.click(); t.scrollIntoView({ block: 'center' }); } }, 60); }
    else if (act === 'legenda') { var lb = document.getElementById('legend-btn') || document.querySelector('.legend button'); if (lb) { if (lb.getAttribute('aria-expanded') !== 'true') lb.click(); var d = document.querySelector('.legend .conv'); if (d) { d.open = true; d.scrollIntoView({ block: 'center' }); } } }
    else if (act === 'modo' || act === 'tema') { /* os botões logo abaixo fazem a troca */ }
  });

  // abre o painel certo quando se chega de outra página (…/#painel=parado)
  if (isHome && /^#painel=/.test(location.hash)) {
    var want = location.hash.slice(8); history.replaceState(null, '', location.pathname);
    setTimeout(function () { var t = document.getElementById('tab-' + want); if (t) { t.click(); t.scrollIntoView({ block: 'center' }); } }, 300);
  }
})();
