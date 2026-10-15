const { chromium } = require('playwright');
// O teto de 8s no goto não é impaciência: as páginas pedem fonte ao Google com carregamento
// diferido, e em runner de CI a rede pode nunca 'aquietar'. Sem o teto, cada carregamento custa
// os 30s padrão do Playwright — 65 deles aqui davam mais de meia hora, e o eval agendado batia
// no limite de 60 minutos sem terminar. Passado o teto a página já está desenhada; seguir é certo.
(async () => { const b=await chromium.launch(); let ruim=0;
  for (const w of [360,390,540,700,820,1000,1280,1600]) {
    const p=await b.newPage({viewport:{width:w,height:900}});
    await p.goto('http://localhost:8767/do-zero/',{ waitUntil: 'networkidle', timeout: 8000 });
    await p.evaluate(()=>window.scrollTo(0,document.body.scrollHeight)); await p.waitForTimeout(800);
    const r=await p.evaluate(()=>{ const m=document.querySelector('main'); const hr=m.getBoundingClientRect(); const out=[];
      for (const el of m.querySelectorAll('*')) { if (el.closest('svg')) continue;
        const b=el.getBoundingClientRect(); if(!b.width) continue;
        const over=Math.round(Math.max(b.right-hr.right, hr.left-b.left));
        const self=Math.round(el.scrollWidth-el.clientWidth);
        const corta=getComputedStyle(el).overflowX!=='visible';
        if (over>1 || (self>1 && !corta)) out.push((el.className||el.tagName)+' +'+Math.max(over,self)); }
      return {sw:document.documentElement.scrollWidth, out:[...new Set(out)].slice(0,6)}; });
    if (r.sw>w || r.out.length) ruim++;
    console.log(w, 'scrollW', r.sw, r.out.length? JSON.stringify(r.out):'ok');
    await p.close(); }
  console.log(ruim? 'FALHAS '+ruim : 'contenção ok em todas as larguras'); await b.close(); })();
