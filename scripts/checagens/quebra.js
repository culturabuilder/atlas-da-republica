const { chromium } = require('playwright');
// O teto de 8s no goto não é impaciência: as páginas pedem fonte ao Google com carregamento
// diferido, e em runner de CI a rede pode nunca 'aquietar'. Sem o teto, cada carregamento custa
// os 30s padrão do Playwright — 65 deles aqui davam mais de meia hora, e o eval agendado batia
// no limite de 60 minutos sem terminar. Passado o teto a página já está desenhada; seguir é certo.
(async () => { const b=await chromium.launch(); let ruim=0;
  for (const w of [360,390,540,700,820,1000,1280,1600]) {
    const p=await b.newPage({viewport:{width:w,height:900}});
    await p.goto('http://localhost:8767/do-zero/',{ waitUntil: 'networkidle', timeout: 8000 });
    await p.evaluate(()=>window.scrollTo(0,document.body.scrollHeight)); await p.waitForTimeout(700);
    const r=await p.evaluate(()=>{ const out=[]; const R=document.createRange();
      const it=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
      let n; while((n=it.nextNode())){ const t=n.nodeValue; if(!t||!t.trim()) continue;
        if(n.parentElement.closest('svg')) continue;
        // mede cada palavra: se uma palavra sozinha ocupa mais de uma caixa de linha, ela foi partida
        let i=0; for (const m of t.matchAll(/\S+/g)) {
          const pal=m[0]; if(pal.length<4) continue;
          R.setStart(n,m.index); R.setEnd(n,m.index+pal.length);
          if(R.getClientRects().length>1 && !/[-\u2013\u2014/]/.test(pal)) out.push(pal.slice(0,30));
          if(++i>40) break; }
      } return [...new Set(out)].slice(0,8); });
    if(r.length) ruim++;
    console.log(w, r.length?JSON.stringify(r):'sem palavra quebrada');
    await p.close(); }
  console.log(ruim?'FALHAS '+ruim:'nenhuma palavra quebrada em nenhuma largura'); await b.close(); })();
