// Contenção do painel: nada dentro dele pode passar da borda. Treze telas, cinco larguras.
// Reescrito em 27/09/2026 porque a versão original vivia num diretório temporário e evaporou.
const { chromium } = require('playwright');
const BASE = process.argv[2] || 'http://localhost:8767';
const TELAS = [
  ['home', '/', null], ['home-dinheiro', '/', 'dinheiro'], ['home-parado', '/', 'parado'],
  ['home-mudou', '/', 'mudou'], ['home-imprensa', '/', 'imprensa'],
  ['stf', '/#br-supremo-tribunal-federal-ministro', null], ['saude', '/#br-ministerio-da-saude', null],
  ['cmn', '/#br-conselho-monetario-nacional', null], ['fazenda', '/#br-ministro-de-estado-da-fazenda', null],
  ['pessoa', '/#br-p-luiz-inacio-lula-da-silva', null], ['camara', '/#br-camara-dos-deputados', null],
  ['senador', '/#br-senador', null], ['anatel', '/#br-anatel', null],
];
const LARGURAS = [[1600, 950], [1440, 950], [1180, 900], [1000, 900], [920, 900]];
(async () => {
  const b = await chromium.launch();
  let ruins = 0, erros = [];
  for (const [w, h] of LARGURAS) {
    const p = await b.newPage({ viewport: { width: w, height: h } });
    p.on('pageerror', x => erros.push(`${w}px: ${String(x).slice(0, 110)}`));
    for (const [nome, url, aba] of TELAS) {
      await p.goto(BASE + url, { waitUntil: 'networkidle' }).catch(() => {});
      await p.waitForTimeout(500);
      if (aba) { await p.click('#tab-' + aba).catch(() => {}); await p.waitForTimeout(400); }
      const maus = await p.evaluate(() => {
        // no celular o painel é display:contents e quem manda na largura é .app
        const alvo = document.querySelector('.panel');
        if (!alvo) return [];
        const host = getComputedStyle(alvo).display === 'contents' ? document.querySelector('.app') : alvo;
        if (!host) return [];
        const hr = host.getBoundingClientRect(); const out = []; const vistos = new Set();
        for (const el of host.querySelectorAll('*')) {
          if (el.closest('svg')) continue;
          const r = el.getBoundingClientRect(); if (!r.width) continue;
          const passou = Math.round(Math.max(r.right - hr.right, hr.left - r.left));
          const proprio = Math.round(el.scrollWidth - el.clientWidth);
          const s = getComputedStyle(el);
          const podeCortar = s.textOverflow === 'ellipsis' || s.overflowX !== 'visible';
          if (passou > 1 || (proprio > 1 && !podeCortar)) {
            const sig = el.className + '|' + el.tagName;
            if (vistos.has(sig)) continue; vistos.add(sig);
            out.push(`${el.tagName}.${String(el.className).slice(0, 30)} +${Math.max(passou, proprio)}`);
          }
        }
        return out.slice(0, 4);
      });
      if (maus.length) { ruins++; console.log(`  ${w}px ${nome}: ${JSON.stringify(maus)}`); }
    }
    await p.close();
  }
  await b.close();
  if (erros.length) console.log('erros de script:', [...new Set(erros)].slice(0, 4));
  console.log(ruins || erros.length ? `FALHAS ${ruins} tela(s)` : 'contenção ok em todas as larguras');
})();
