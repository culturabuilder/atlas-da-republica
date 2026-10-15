// As páginas autônomas do site (as que não são o app da roda) não podem rolar de lado no celular.
//
// Escrita em 15/10/2026 porque /dados/, /metodologia/ e /como-funciona/ rolavam de lado a 390px desde
// sempre, e nenhuma checagem pegava: scripts/checagens/overflow.js só visita as telas do app. A causa
// na barra era um `min-width:0` que existia só em comparar.html; em como-funciona era um <select> que
// cresce com a opção mais longa. São páginas públicas, e celular é a maior parte do acesso.
const { chromium } = require('playwright');
// O teto de 8s no goto não é impaciência: as páginas pedem fonte ao Google com carregamento
// diferido, e em runner de CI a rede pode nunca 'aquietar'. Sem o teto, cada carregamento custa
// os 30s padrão do Playwright — 65 deles aqui davam mais de meia hora, e o eval agendado batia
// no limite de 60 minutos sem terminar. Passado o teto a página já está desenhada; seguir é certo.
const BASE = process.argv[2] || 'http://localhost:8767';
const PAGINAS = ['/', '/dados/', '/metodologia/', '/comparar/', '/do-zero/', '/como-funciona/', '/novidades/'];
const LARGURAS = [360, 390, 520, 768];
(async () => {
  const b = await chromium.launch();
  let ruins = 0;
  for (const w of LARGURAS) {
    const p = await b.newPage({ viewport: { width: w, height: 900 } });
    const erros = [];
    p.on('pageerror', x => erros.push(String(x).slice(0, 110)));
    for (const u of PAGINAS) {
      const r = await p.goto(BASE + u, { waitUntil: 'networkidle', timeout: 8000 }).catch(() => null);
      if (!r) { console.log(`  ${w}px ${u}: não carregou`); ruins++; continue; }
      await p.waitForTimeout(600);
      const d = await p.evaluate(() => {
        const cw = document.documentElement.clientWidth;
        const sw = document.documentElement.scrollWidth;
        if (sw <= cw + 1) return null;
        const culpados = [];
        for (const el of document.querySelectorAll('*')) {
          const r = el.getBoundingClientRect();
          if (!r.width || r.right <= cw + 1) continue;
          if (el.closest('[style*="overflow-x"],.tbl,pre,table')) continue;   // caixa que rola de propósito
          culpados.push(`${el.tagName}.${String(el.className).slice(0, 24)} +${Math.round(r.right - cw)}`);
        }
        return { sw, cw, culpados: [...new Set(culpados)].slice(0, 3) };
      });
      if (d) { console.log(`  ${w}px ${u}: rola de lado (${d.sw} > ${d.cw}) ${JSON.stringify(d.culpados)}`); ruins++; }
    }
    if (erros.length) { console.log(`  ${w}px erros de página: ${JSON.stringify([...new Set(erros)].slice(0, 3))}`); ruins++; }
    await p.close();
  }
  await b.close();
  if (ruins) { console.log(`FALHAS ${ruins}`); process.exit(1); }
  console.log(`nenhuma página rola de lado (${PAGINAS.length} páginas x ${LARGURAS.length} larguras)`);
})();
