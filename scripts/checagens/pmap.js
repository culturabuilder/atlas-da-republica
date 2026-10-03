const { chromium } = require('playwright');
(async () => { const b=await chromium.launch();
  for (const [w,h,n] of [[1440,1100,'d'],[390,900,'m']]) {
    const p=await b.newPage({viewport:{width:w,height:h},deviceScaleFactor:1.5});
    const e=[]; p.on('pageerror',x=>e.push(String(x).slice(0,150)));
    await p.goto('http://localhost:8767/',{waitUntil:'networkidle'}); await p.waitForTimeout(600);
    await p.click('#tab-imprensa'); await p.waitForTimeout(400);
    await p.click('[data-imp="pessoas"]'); await p.waitForTimeout(1200);
    const r=await p.evaluate(()=>{ const box=document.getElementById('pmap'); if(!box) return {erro:'sem pmap'};
      const svg=box.querySelector('.pmfios');
      const host=(getComputedStyle(document.querySelector('.panel')).display==='contents')?document.querySelector('.app'):document.querySelector('.panel'); const hr=host.getBoundingClientRect();
      let estouro=0; for(const el of box.querySelectorAll('*')){ if(el.closest('svg'))continue; const r=el.getBoundingClientRect(); if(r.width&&r.right-hr.right>1)estouro++; }
      return {cartoes:box.querySelectorAll('.pc').length, fios:svg?svg.querySelectorAll('path').length:0,
              faixas:box.querySelectorAll('.pmt').length, estouro, fotos:box.querySelectorAll('.pc img').length}; });
    console.log(w, JSON.stringify(r), 'erros', e);
    const el=await p.locator('#pmap').first(); const bb=await el.boundingBox();
    if(bb) await p.screenshot({path:`${process.env.ATLAS_SHOTS||'/tmp/atlas-shots'}/pmap-${n}.png`,clip:{x:0,y:Math.max(0,bb.y-150),width:Math.min(w,760),height:Math.min(h-20,bb.height+200)}});
    await p.close(); }
  await b.close(); })();
