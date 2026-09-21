/* Atlas da República — câmera reversível da roda (MIT).
   Camada só de navegador: envolve o conteúdo do <svg class="wheel"> em um grupo e aplica
   translação, escala e rotação nele. Não altera ids, posições locais nem dados; atlas.js e
   render_wheel.js (Node) continuam iguais. Desligar o módulo (ou o modo "Sem movimento")
   devolve exatamente a roda de antes.
   Modos: none (sem movimento) · focus (aproxima e desloca em direção à seleção, 18%) ·
   rotate (gira a roda para trazer a seleção ao alto à esquerda). Gestos: arraste (mouse/toque),
   pinça, roda do mouse com Ctrl/⌘, botões − + e "Visão geral". Respeita prefers-reduced-motion. */
(function () {
  'use strict';
  if (typeof window === 'undefined' || typeof document === 'undefined') return;
  var KEY = 'atlas-camera';
  var DUR = 340;             // ms da transição (ponto de partida; ajustar com testes)
  var FOCUS_ZOOM = 1.18;     // aproximação do modo foco
  var FOCUS_PULL = 0.35;     // fração do deslocamento do nó até o centro
  var ROT_ZOOM = 1.0;        // rotação pura: a roda não sai do quadro
  var TARGET_ANGLE = 225;    // graus (0 = 3h, sentido horário na tela): alto à esquerda
  var MIN_S = 0.6, MAX_S = 4;
  var TAP = 10;              // px: abaixo disso é toque/clique, não arraste

  var state = { mode: 'none', s: 1, tx: 0, ty: 0, rot: 0 };
  var C = 0, svg = null, cam = null, anim = null, reduced = false, stage = null, ui = null;

  function pref() { try { return JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) { return {}; } }
  function save() { try { localStorage.setItem(KEY, JSON.stringify({ mode: state.mode })); } catch (e) {} }

  function wrap() {
    svg = document.querySelector('svg.wheel');
    if (!svg || svg.querySelector('#cam')) return !!svg;
    var vb = (svg.getAttribute('viewBox') || '0 0 1000 1000').split(/\s+/).map(Number); C = vb[2] / 2;
    var g = document.createElementNS('http://www.w3.org/2000/svg', 'g'); g.setAttribute('id', 'cam');
    var kids = Array.prototype.slice.call(svg.childNodes);
    kids.forEach(function (k) { if (k.nodeType === 1 && k.tagName.toLowerCase() === 'defs') return; g.appendChild(k); });
    svg.appendChild(g); cam = g;
    return true;
  }

  function apply(st) {
    if (!cam) return;
    var t = 'translate(' + C + ' ' + C + ') rotate(' + st.rot.toFixed(3) + ') scale(' + st.s.toFixed(4) + ') translate(' + (-C + st.tx).toFixed(2) + ' ' + (-C + st.ty).toFixed(2) + ')';
    cam.setAttribute('transform', t);
    // o texto do centro não deve virar de cabeça para baixo
    var labels = cam.querySelectorAll('.center-label');
    for (var i = 0; i < labels.length; i++) labels[i].setAttribute('transform', st.rot ? 'rotate(' + (-st.rot).toFixed(3) + ' ' + C + ' ' + C + ')' : '');
    svg.classList.toggle('cam-rot', Math.abs(st.rot) > 0.5);
  }

  function ease(t) { return t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t; }
  function go(target) {
    // uma nova ação interrompe a anterior: sem fila de movimentos
    if (anim) { cancelAnimationFrame(anim); anim = null; }
    var from = { s: state.s, tx: state.tx, ty: state.ty, rot: state.rot };
    var to = { s: target.s, tx: target.tx, ty: target.ty, rot: target.rot };
    // menor deslocamento angular
    var d = ((to.rot - from.rot) % 360 + 540) % 360 - 180; to.rot = from.rot + d;
    if (reduced || DUR <= 0) { state.s = to.s; state.tx = to.tx; state.ty = to.ty; state.rot = ((to.rot % 360) + 360) % 360; apply(state); return; }
    var t0 = performance.now();
    function step(now) {
      var k = Math.min(1, (now - t0) / DUR), e = ease(k);
      state.s = from.s + (to.s - from.s) * e; state.tx = from.tx + (to.tx - from.tx) * e; state.ty = from.ty + (to.ty - from.ty) * e; state.rot = from.rot + (to.rot - from.rot) * e;
      apply(state);
      if (k < 1) anim = requestAnimationFrame(step); else { anim = null; state.rot = ((state.rot % 360) + 360) % 360; }
    }
    anim = requestAnimationFrame(step);
  }

  function nodePos(id) {
    var a = svg && svg.querySelector('.node[data-id="' + id + '"]'); if (!a) return null;
    var m = /translate\(([-\d.]+),([-\d.]+)\)/.exec(a.getAttribute('transform') || '');
    if (!m) return a.classList.contains('center') ? { x: C, y: C } : null;
    return { x: parseFloat(m[1]), y: parseFloat(m[2]) };
  }

  function frame(id) {
    if (!cam) return;
    var p = id ? nodePos(id) : null;
    if (!p || state.mode === 'none') { go({ s: 1, tx: 0, ty: 0, rot: 0 }); return; }
    var dx = p.x - C, dy = p.y - C;
    if (state.mode === 'focus') {
      // aproxima e puxa o nó em direção ao centro, sem girar
      var s = FOCUS_ZOOM; go({ s: s, tx: -dx * FOCUS_PULL * s / s, ty: -dy * FOCUS_PULL, rot: 0 });
    } else {
      var ang = Math.atan2(dy, dx) * 180 / Math.PI; // ângulo do nó (0 = 3h)
      var rot = TARGET_ANGLE - ang;                  // gira para levá-lo ao alvo
      go({ s: ROT_ZOOM, tx: 0, ty: 0, rot: rot });
    }
  }

  // ---- gestos: arraste, pinça, roda com Ctrl/⌘ ----
  var ptrs = {}, drag = null, moved = 0, pinch = null;
  function pt(e) { return { x: e.clientX, y: e.clientY }; }
  function screenScale() { var r = svg.getBoundingClientRect(); return (2 * C) / Math.max(1, r.width); } // unidades SVG por px
  function center() { var r = svg.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; }
  function angTo(p) { var c = center(); return Math.atan2(p.y - c.y, p.x - c.x) * 180 / Math.PI; }
  function onDown(e) {
    if (e.button != null && e.button !== 0) return;
    ptrs[e.pointerId] = pt(e); var keys = Object.keys(ptrs);
    if (keys.length === 1) { drag = { x: e.clientX, y: e.clientY, tx: state.tx, ty: state.ty, rot: state.rot, a0: angTo(pt(e)) }; moved = 0; }
    else if (keys.length === 2) { var a = ptrs[keys[0]], b = ptrs[keys[1]]; pinch = { d: Math.hypot(a.x - b.x, a.y - b.y), s: state.s, a0: Math.atan2(b.y - a.y, b.x - a.x) * 180 / Math.PI, rot: state.rot }; drag = null; }
    // sem captura aqui: capturar no pointerdown faz o clique cair no contêiner e o <a> do nó deixa de navegar.
    if (keys.length === 2) capture(e.pointerId);
  }
  var captured = {};
  function capture(id) { if (captured[id]) return; try { (document.getElementById('graph') || svg).setPointerCapture(id); captured[id] = true; } catch (err) {} }
  function onMove(e) {
    if (!(e.pointerId in ptrs)) return; ptrs[e.pointerId] = pt(e); var keys = Object.keys(ptrs);
    if (keys.length === 2 && pinch) {
      var a = ptrs[keys[0]], b = ptrs[keys[1]]; var d = Math.hypot(a.x - b.x, a.y - b.y);
      state.s = Math.max(MIN_S, Math.min(MAX_S, pinch.s * d / Math.max(1, pinch.d)));
      // dois dedos girando = gira a roda (em qualquer modo)
      var a1 = Math.atan2(b.y - a.y, b.x - a.x) * 180 / Math.PI; state.rot = pinch.rot + (a1 - pinch.a0);
      apply(state); moved = 99; e.preventDefault(); return;
    }
    if (!drag) return;
    var k = screenScale(); var dx = e.clientX - drag.x, dy = e.clientY - drag.y; moved = Math.max(moved, Math.hypot(dx, dy));
    if (moved > TAP) capture(e.pointerId); // só a partir daqui é arraste: captura para seguir fora da roda
    if (moved > TAP && state.mode === 'rotate') { // no modo rotação, segurar e mover gira a roda em torno do centro
      if (anim) { cancelAnimationFrame(anim); anim = null; }
      state.rot = drag.rot + (angTo(pt(e)) - drag.a0); apply(state); e.preventDefault(); return; }
    if (moved > TAP) { if (anim) { cancelAnimationFrame(anim); anim = null; }
      // desloca no referencial da tela: desfaz rotação/escala do grupo
      var rad = -state.rot * Math.PI / 180; var ux = dx * k, uy = dy * k;
      state.tx = drag.tx + (ux * Math.cos(rad) - uy * Math.sin(rad)) / state.s; state.ty = drag.ty + (ux * Math.sin(rad) + uy * Math.cos(rad)) / state.s; apply(state); e.preventDefault(); }
  }
  function onUp(e) { delete ptrs[e.pointerId]; delete captured[e.pointerId]; if (!Object.keys(ptrs).length) { drag = null; pinch = null; } else pinch = null; }
  function onClick(e) { if (moved > TAP) { e.preventDefault(); e.stopPropagation(); moved = 0; } }
  function onWheel(e) { if (!(e.ctrlKey || e.metaKey)) return; e.preventDefault(); zoom(e.deltaY < 0 ? 1.15 : 1 / 1.15); }
  function zoom(f) { if (anim) { cancelAnimationFrame(anim); anim = null; } state.s = Math.max(MIN_S, Math.min(MAX_S, state.s * f)); apply(state); }

  // ---- interface ----
  var hintEl = null, hintT = null;
  function hint(msg) {
    if (!stage) return; if (!hintEl) { hintEl = document.createElement('div'); hintEl.className = 'cam-hint'; hintEl.setAttribute('role', 'status'); stage.appendChild(hintEl); }
    hintEl.textContent = msg; hintEl.classList.add('show'); clearTimeout(hintT); hintT = setTimeout(function () { hintEl.classList.remove('show'); }, 2600);
  }
  function setMode(m, silent) {
    state.mode = m; save();
    if (!silent && m !== 'none' && !nodePos(currentId())) hint(m === 'rotate' ? 'Toque num órgão para girar a roda até ele. Segure e arraste para girar à mão.' : 'Toque num órgão para aproximar. Arraste para mover, pince para ampliar.');
    if (ui) { var bs = ui.querySelectorAll('[data-mode]'); for (var i = 0; i < bs.length; i++) { var on = bs[i].getAttribute('data-mode') === m; bs[i].classList.toggle('on', on); bs[i].setAttribute('aria-pressed', on ? 'true' : 'false'); } }
    if (!silent) frame(currentId());
  }
  function currentId() { var h = (location.hash || '').slice(1); if (!h || h.indexOf('news:') === 0) return window.ATLAS_PAGE_ID || ''; return h; }
  function buildUI() {
    stage = document.querySelector('.stage') || (svg && svg.parentElement); if (!stage) return;
    var css = document.createElement('style'); css.textContent =
      '.cam-ui{position:absolute;left:16px;top:16px;z-index:5;display:flex;flex-wrap:wrap;gap:6px;align-items:center;font:12.5px/1 var(--sans,system-ui,sans-serif)}' +
      '.cam-ui .grp{display:inline-flex;border:1px solid var(--line-2,#8883);border-radius:999px;background:var(--card,#fff);overflow:hidden}' +
      '.cam-ui button{border:0;background:transparent;color:var(--ink-2,#444);padding:7px 10px;cursor:pointer;font:inherit;min-height:32px}' +
      '.cam-ui button.on{background:var(--accent,#e07a3f);color:var(--card,#fff)}.cam-ui button:focus-visible{outline:2px solid var(--accent,#e07a3f);outline-offset:-2px}' +
      '.cam-ui .z button{min-width:32px;font-size:15px}' +
      'svg.wheel.cam-rot .ring-label{opacity:.35}' +
      '.cam-stage{overflow:hidden}@media (max-width:900px){.cam-stage{border:1px solid var(--line-2,#8883);border-radius:14px;padding:8px}.cam-ui{position:relative;z-index:5;margin:0 0 6px}.previa-banner{font-size:11.5px;padding:5px 12px}}' +
      '.cam-hint{position:absolute;left:50%;bottom:14px;transform:translateX(-50%);background:var(--card,#fff);color:var(--ink-2,#444);border:1px solid var(--line-2,#8883);border-radius:999px;padding:6px 12px;font-size:12.5px;white-space:nowrap;pointer-events:none;opacity:0;transition:opacity .2s}.cam-hint.show{opacity:1}' +
      '.previa-banner{background:#b45309;color:#fff;font:13px/1.3 system-ui,sans-serif;padding:8px 16px;text-align:center}.previa-banner a{color:#fff}';
    document.head.appendChild(css);
    ui = document.createElement('div'); ui.className = 'cam-ui'; ui.setAttribute('role', 'group'); ui.setAttribute('aria-label', 'Movimento da roda');
    ui.innerHTML = '<div class="grp" role="group" aria-label="Modo"><button type="button" data-mode="none" aria-pressed="false" title="A roda fica parada">Sem movimento</button><button type="button" data-mode="focus" aria-pressed="false" title="Aproxima a seleção sem girar">Foco suave</button><button type="button" data-mode="rotate" aria-pressed="false" title="Experimental: gira a roda para orientar a seleção">Rotação</button></div>' +
      '<div class="grp z" role="group" aria-label="Zoom"><button type="button" data-z="out" aria-label="Afastar">−</button><button type="button" data-z="in" aria-label="Aproximar">+</button><button type="button" data-z="reset">Visão geral</button></div>';
    stage.insertBefore(ui, stage.firstChild);
    ui.addEventListener('click', function (e) {
      var b = e.target.closest('button'); if (!b) return;
      if (b.dataset.mode) setMode(b.dataset.mode);
      else if (b.dataset.z === 'in') zoom(1.25); else if (b.dataset.z === 'out') zoom(1 / 1.25); else go({ s: 1, tx: 0, ty: 0, rot: 0 });
    });
    if (window.ATLAS_PREVIA) {
      var bn = document.createElement('div'); bn.className = 'previa-banner';
      bn.innerHTML = 'Prévia de testes do Atlas da República, não é o site oficial: <a href="https://atlasdarepublica.org">atlasdarepublica.org</a>. Dados e páginas podem estar incompletos.';
      document.body.insertBefore(bn, document.body.firstChild);
    }
  }

  function init() {
    if (!wrap()) return false;
    try { reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) { reduced = false; }
    var p = pref(); state.mode = (p.mode === 'focus' || p.mode === 'rotate' || p.mode === 'none') ? p.mode : (window.ATLAS_CAMERA_DEFAULT || 'focus');
    buildUI(); setMode(state.mode, true);
    var h = document.getElementById('graph') || svg;
    h.addEventListener('pointerdown', onDown); h.addEventListener('pointermove', onMove, { passive: false });
    h.addEventListener('pointerup', onUp); h.addEventListener('pointercancel', onUp); h.addEventListener('lostpointercapture', onUp);
    h.addEventListener('click', onClick, true); h.addEventListener('wheel', onWheel, { passive: false });
    // Safari/iOS: sem isto a pinça vira zoom da página inteira em vez de zoom da roda
    ['gesturestart', 'gesturechange', 'gestureend'].forEach(function (t) { h.addEventListener(t, function (e) { e.preventDefault(); }, { passive: false }); });
    svg.style.touchAction = 'none'; svg.style.overflow = 'visible';
    if (stage) { stage.classList.add('cam-stage'); }
    window.addEventListener('hashchange', function () { frame(currentId()); });
    frame(currentId());
    window.AtlasCamera = { setMode: setMode, frame: frame, reset: function () { go({ s: 1, tx: 0, ty: 0, rot: 0 }); }, state: state, disable: function () { if (cam) cam.removeAttribute('transform'); if (ui) ui.remove(); } };
    return true;
  }
  // a roda pode ser desenhada pelo script da página depois deste módulo carregar (celular lento: até 60 s)
  var tries = 0; (function wait() { if (init()) return; if (++tries < 240) setTimeout(wait, 250); })();
  // se a página redesenhar o <svg>, envolve de novo e reaplica o estado
  var host = document.getElementById('graph');
  if (host && window.MutationObserver) new MutationObserver(function () {
    var s2 = document.querySelector('svg.wheel'); if (s2 && s2 !== svg) { cam = null; if (wrap()) { svg.style.touchAction = 'none'; svg.style.overflow = 'visible'; apply(state); } }
  }).observe(host, { childList: true });
})();
