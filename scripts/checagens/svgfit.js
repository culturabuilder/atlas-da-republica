const { chromium } = require('playwright');
(async () => { const b=await chromium.launch(); const p=await b.newPage({viewport:{width:1280,height:900}});
  await p.goto('http://localhost:8767/do-zero/',{waitUntil:'networkidle'});
  await p.evaluate(()=>window.scrollTo(0,document.body.scrollHeight)); await p.waitForTimeout(1500);
  const r=await p.evaluate(()=>[...document.querySelectorAll('svg.viz, svg.art')].map(s=>{
    const vb=s.getAttribute('viewBox').split(/\s+/).map(Number); const bb=s.getBBox();
    const fora=[Math.round(vb[0]-bb.x), Math.round(vb[1]-bb.y), Math.round((bb.x+bb.width)-(vb[0]+vb[2])), Math.round((bb.y+bb.height)-(vb[1]+vb[3]))];
    return {cap:(s.closest('section')||{}).id||'hero', vb:vb.join(' '), estoura:fora.filter(x=>x>1).length?fora:null};}));
  r.forEach(x=>console.log(x.cap.padEnd(26), x.vb.padEnd(12), x.estoura?'ESTOURA '+JSON.stringify(x.estoura):'ok'));
  await b.close(); })();
