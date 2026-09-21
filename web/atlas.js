// Atlas da República — núcleo da roda (dados, geometria, layout radial, desenho). Carregado depois de graph.br.js.
// Declarações globais: G, N, E, L, SEC, COL, TYPE_NAME, SUB, REL, W, C, RING_R, ARC, angle, radius, posOf, xy, shape, draw, curve, esc…
const G = window.ATLAS; const N = G.nodes, E = G.edges, L = G.layout;
// núcleo leve: deriva listas por nó a partir das arestas e dos pais
if (G.detail_base) {
  for (const n of Object.values(N)) { n.edges = n.edges || []; n.connected = n.connected || []; n.children = n.children || []; n.positions = n.positions || []; }
  for (const e of Object.values(E)) { const a = N[e.from], b = N[e.to]; if (!a || !b) continue; a.edges.push(e.id); b.edges.push(e.id); if (!a.connected.includes(e.to)) a.connected.push(e.to); if (!b.connected.includes(e.from)) b.connected.push(e.from); }
  for (const n of Object.values(N)) { if (n.parent && N[n.parent]) N[n.parent].children.push(n.id); if (n.head_of && N[n.head_of]) N[n.head_of].positions.push(n.id); }
  for (const n of Object.values(N)) { n.children.sort(); n.positions.sort(); }
}
const SEC = {}; L.sectors.forEach(s => SEC[s.id] = s);
const COL = {legislativo:'var(--leg)', executivo:'var(--exe)', judiciario:'var(--jud)', essenciais:'var(--ess)'};
const TYPE_NAME = {constituency:'Eleitorado', elected:'Órgão eletivo', department:'Órgão', dept_head:'Cargo', commission:'Colegiado', advisory:'Conselho consultivo', pessoa:'Pessoa', group:'Grupo de unidades'};
const SUB = {orgao_presidencia:'Órgão da Presidência', ministerio:'Ministério', orgao_singular:'Órgão singular', autarquia:'Autarquia', agencia_reguladora:'Agência reguladora', fundacao:'Fundação pública', empresa_publica:'Empresa pública', sociedade_economia_mista:'Sociedade de economia mista', forca_armada:'Força Armada', tribunal:'Tribunal', casa_legislativa:'Casa legislativa', ministerio_publico:'Ministério Público', defensoria:'Defensoria', advocacia:'Advocacia pública', chefia_executivo:'Chefia do Executivo', instituicao_de_ensino:'Universidade ou instituto federal', orgao_autonomo:'Órgão autônomo', secao_judiciaria:'Seção judiciária'};
const REL = {elege:['Elege','Eleito por'], nomeia:['Nomeia','Nomeado por'], sabatina:['Sabatina e aprova','Sabatinado por'], fiscaliza:['Fiscaliza','Fiscalizado por'], supervisiona:['Supervisiona','Supervisionado por'], aconselha:['Aconselha','Aconselhado por'], chefia:['Chefia','Chefiado por'], membro_nato:['Membro nato de','Tem como membro nato'], integra:['Integra','Integrado por'], indica:['Indica','Indicado por']};

// ---------- layout radial ----------
const W = 920, C = W/2;
const RING_R = {0:0, 1:118, 2:205, 3:292, 4:378};
const R_IN = 78, R_OUT = 415;
// setores: [início, fim] em graus, 0 = topo, sentido horário
const ARC = {legislativo:[-28,28], executivo:[28,212], judiciario:[212,284], essenciais:[284,332]};
const rad = d => (d-90)*Math.PI/180;
const pt = (deg, r) => [C + r*Math.cos(rad(deg)), C + r*Math.sin(rad(deg))];
function arcPath(a0,a1,r0,r1){ const [x0,y0]=pt(a0,r1),[x1,y1]=pt(a1,r1),[x2,y2]=pt(a1,r0),[x3,y3]=pt(a0,r0); const big=(a1-a0)>180?1:0; return `M${x0},${y0} A${r1},${r1} 0 ${big} 1 ${x1},${y1} L${x2},${y2} A${r0},${r0} 0 ${big} 0 ${x3},${y3} Z`; }
function ringArc(a0,a1,r){ const [x0,y0]=pt(a0,r),[x1,y1]=pt(a1,r); const big=(a1-a0)>180?1:0; return `M${x0},${y0} A${r},${r} 0 ${big} 1 ${x1},${y1}`; }

const CLUSTER_SUB = 'instituicao_de_ensino';
const orgs = Object.values(N).filter(n => n.type !== 'dept_head' && n.type !== 'constituency');
const angle = {}, radius = {}, clusterOf = {};
// grupos recolhidos: unidades de um mesmo órgão (secretarias, colegiados, universidades) viram um marcador com
// contagem ao lado do pai; os pontos só aparecem quando o pai (ou um membro) é selecionado ou o marcador é tocado.
const GROUPS = {};
for (const sid of Object.keys(ARC)) {
  const [a0,a1] = ARC[sid]; const pad = 5;
  for (const ring of [1,2,3,4]) {
    let all = orgs.filter(n => n.sector === sid && n.ring === ring);
    if (!all.length) continue;
    const clusters = {}; const list = [];
    const grouped = !(sid === 'legislativo' && ring === 3); // comissões do Congresso ficam sempre abertas, em arcos
    for (const n of all) { if (n.cluster && grouped) { const k = n.parent || 'x'; (clusters[k] = clusters[k] || []).push(n); } else list.push(n); }
    for (const k of Object.keys(clusters)) list.push({id:'grp:'+k+':'+ring, parent:k, name:'~', _cluster:clusters[k]});
    list.sort((a,b) => { const pa = a.parent && angle[a.parent] != null ? angle[a.parent] : 999, pb = b.parent && angle[b.parent] != null ? angle[b.parent] : 999; return pa - pb || String(a.name).localeCompare(String(b.name),'pt'); });
    // cada item ocupa uma fatia angular proporcional ao que precisa: um nó = 1; uma grade de cluster = metade das colunas + 0,5
    // (antes cada cluster tinha a fatia de um nó só, e as grades de comissões e universidades se sobrepunham aos vizinhos)
    const span = (a1-a0) - 2*pad; const step = list.length > 1 ? span/(list.length-1) : 0;
    const dense = list.length > 48;
    list.forEach((n,i) => {
      const a = list.length > 1 ? a0+pad+i*step : (a0+a1)/2; const r = RING_R[ring] + (dense ? (i%2 ? 12 : -12) : 0);
      angle[n.id] = a; radius[n.id] = r;
      if (n._cluster) { // marcador no anel; membros num arco curto centrado nele (1 ou 2 fileiras), visíveis só com o grupo aberto
        const ms = n._cluster.slice().sort((x,y) => String(x.name).localeCompare(String(y.name),'pt'));
        const rows = ms.length > 14 ? 2 : 1; const per = Math.ceil(ms.length/rows); const stepA = (6.4/r)*180/Math.PI;
        GROUPS[n.id] = {id:n.id, type:'group', parent:n.parent, sector:sid, ring, members:ms.map(m=>m.id), name:(N[n.parent]?N[n.parent].name:'')};
        ms.forEach((m,j) => { const row = j%rows, col = Math.floor(j/rows); angle[m.id] = a + (col-(per-1)/2)*stepA; radius[m.id] = r + (rows === 2 ? (row ? 8 : -8) : 0); clusterOf[m.id] = n.id; });
      }
    });
  }
}
// comissões do Congresso (anel 3 do Legislativo): em vez de grades, três arcos concêntricos por Casa
// (Senado por dentro, mistas no meio, Câmara por fora), cada um com espaçamento uniforme ao longo do setor.
(function(){
  const [a0,a1] = ARC.legislativo; const pad = 4; const span = (a1-a0) - 2*pad;
  const all = orgs.filter(n => n.sector === 'legislativo' && n.ring === 3 && n.type === 'commission');
  if (!all.length) return;
  const groups = [['br-senado-federal', -26], ['br-congresso-nacional', 0], ['br-camara-dos-deputados', 26]];
  for (const [parent, dr] of groups) {
    const list = all.filter(n => n.parent === parent).sort((x,y) => (x.cluster?1:0)-(y.cluster?1:0) || (/^Mesa/.test(y.name)?1:0)-(/^Mesa/.test(x.name)?1:0) || String(x.name).localeCompare(String(y.name),'pt'));
    if (!list.length) continue;
    const step = list.length > 1 ? Math.min(span/(list.length-1), 6) : 0; const start = (a0+a1)/2 - step*(list.length-1)/2;
    list.forEach((n,i) => { angle[n.id] = start + i*step; radius[n.id] = RING_R[3] + dr; delete clusterOf[n.id]; n._arc = true; });
  }
})();
// cargos: mesmo ângulo do órgão, um pouco para dentro; vários cargos do mesmo órgão se espalham
const posOf = {};
for (const n of orgs) {
  const ps = n.positions || []; const rr = radius[n.id] != null ? radius[n.id] : RING_R[n.ring]; ps.forEach((pid,i) => { const off = (i-(ps.length-1)/2)*2.4; posOf[pid] = {a: angle[n.id]+off, r: rr-15}; });
}
function xy(id){ const n=N[id]; if(n.type==='constituency') return [C,C]; if(n.type==='dept_head'){ const p=posOf[id]; return pt(p.a,p.r);} return pt(angle[id], radius[id] != null ? radius[id] : RING_R[n.ring]); }

// ---------- desenho ----------
function shape(n, s){
  const t=n.type, k=(n.ring===1||n.ring===2)?1.25:1; s=s*k;
  if (t==='elected') return `<circle class="shape" r="${s}"/>`;
  if (t==='department') { const sub=n.subtype; if(n.cluster) return `<circle class="shape" r="2.2" style="fill:currentColor;fill-opacity:.55"/>`; if(sub==='tribunal') return `<polygon class="shape" points="${poly(5,s+1,-90)}"/>`; if(sub==='forca_armada') return `<polygon class="shape" points="${poly(3,s+2,-90)}"/>`; return `<rect class="shape" x="${-s}" y="${-s}" width="${2*s}" height="${2*s}" rx="1.5"/>`; }
  if (t==='commission') { if (n._arc) s = n.cluster ? 2.7 : 3.6; else if (n.cluster) s = 2.2; return `<polygon class="shape" points="${poly(5,s+1,-90)}" transform="rotate(180)"/>`; }
  if (t==='advisory') { if (n.cluster) s = 2.2; return `<polygon class="shape" points="${poly(6,s+1,0)}"/>`; }
  if (t==='dept_head') return `<circle class="shape" r="2.6"/>`;
  return '';
}
function poly(nn,r,rot){ const o=[]; for(let i=0;i<nn;i++){ const a=(rot+i*360/nn)*Math.PI/180; o.push((r*Math.cos(a)).toFixed(1)+','+(r*Math.sin(a)).toFixed(1)); } return o.join(' '); }
function burst(r){ const o=[]; for(let i=0;i<32;i++){ const a=i*Math.PI/16, rr=i%2?r:r*0.88; o.push((C+rr*Math.cos(a)).toFixed(1)+','+(C+rr*Math.sin(a)).toFixed(1)); } return o.join(' '); }

function draw(){
  let s = `<svg class="wheel" viewBox="0 0 ${W} ${W}" role="group" aria-label="Roda do governo federal: ${G.stats.nodes} nós em quatro setores">
  <defs>${Object.keys(REL).map(t=>`<marker id="m-${t}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="context-stroke"/></marker>`).join('')}</defs>`;
  for (const sid of Object.keys(ARC)) { const [a0,a1]=ARC[sid]; s += `<path class="sector-bg" d="${arcPath(a0,a1,R_IN,R_OUT)}" fill="${COL[sid]}"/>`; }
  for (const r of [1,2,3,4]) s += `<circle class="ring" cx="${C}" cy="${C}" r="${RING_R[r]}"/>`;
  // numerais dos anéis junto à divisa Legislativo/Funções essenciais (os nomes completos ficam na legenda: os rótulos em arco cruzavam os nós do setor Essenciais)
  for (const r of [1,2,3,4]) { const [x,y] = pt(ARC.legislativo[0]+1.2, RING_R[r]); s += `<text class="ring-num" x="${x.toFixed(1)}" y="${(y+2.5).toFixed(1)}" aria-hidden="true">${r}</text>`; }
  for (const sid of Object.keys(ARC)) { const [a0,a1]=ARC[sid]; const flip = (a0+a1)/2 > 90 && (a0+a1)/2 < 270; const d = flip ? ringArc(a1,a0,R_OUT+9).replace('0 0 1','0 0 0') : ringArc(a0,a1,R_OUT+12); const lbl=(SEC[sid].short||SEC[sid].name).toUpperCase();
    s += `<path id="sl-${sid}" d="${flip?ringArcRev(a0,a1,R_OUT+6):ringArc(a0,a1,R_OUT+13)}" fill="none"/><text class="sector-label" fill="${COL[sid]}"><textPath href="#sl-${sid}" startOffset="50%" text-anchor="middle">${lbl}</textPath></text>`; }
  // arcos de subgrupo (como "Cabinet"/"Congress" no CivLab)
  const SUBARCS = [['executivo',2,n=>n.subtype==='ministerio','ESPLANADA'],['judiciario',2,n=>n.subtype==='tribunal','TRIBUNAIS SUPERIORES'],['legislativo',3,n=>n.type==='commission','COMISSÕES'],['essenciais',3,n=>n.subtype==='ministerio_publico','RAMOS DO MPU']];
  SUBARCS.forEach(([sid,ring,f,label],i)=>{ const as = orgs.filter(n=>n.sector===sid&&n.ring===ring&&f(n)&&angle[n.id]!=null).map(n=>angle[n.id]); if (as.length<3) return; const a0=Math.min(...as)-1.5, a1=Math.max(...as)+1.5; const rs = orgs.filter(n=>n.sector===sid&&n.ring===ring&&f(n)&&radius[n.id]!=null).map(n=>radius[n.id]); const r=Math.max(RING_R[ring]+(ring>=3?26:22), (rs.length?Math.max(...rs):0)+18); const flip=(a0+a1)/2>90&&(a0+a1)/2<270; s += `<path d="${flip?ringArcRev(a0,a1,r):ringArc(a0,a1,r)}" fill="none" stroke="${COL[sid]}" stroke-opacity=".35" stroke-width="1"/><path id="sa${i}" d="${flip?ringArcRev(a0,a1,r+(flip?-4:6)):ringArc(a0,a1,r+6)}" fill="none"/><text class="ring-label" fill="${COL[sid]}" style="fill:${COL[sid]};fill-opacity:.85;font-size:8px"><textPath href="#sa${i}" startOffset="50%" text-anchor="middle">${label}</textPath></text>`; });
  s += `<g id="edges"></g>`;
  s += `<a class="node center" href="#br-eleitorado" data-id="br-eleitorado" aria-label="Povo brasileiro, eleitorado"><polygon class="shape" points="${burst(52)}" style="fill:var(--povo);stroke:var(--povo)"/><text class="center-label" x="${C}" y="${C-3}">Povo</text><text class="center-label" x="${C}" y="${C+9}">brasileiro</text></a>`;
  const nodeTag = (n, cls) => { const [x,y]=xy(n.id); return `<a class="node${cls?' '+cls:''}" href="#${n.id}" data-id="${n.id}" aria-label="${esc(n.name)}, ${n.type==='dept_head'?'cargo':TYPE_NAME[n.type]}" style="color:${COL[n.sector]}" transform="translate(${x.toFixed(1)},${y.toFixed(1)})"><g style="stroke:${COL[n.sector]}">${shape(n, n.type==='dept_head'?0:(n.ring<=2?6:4.6))}</g></a>`; };
  for (const n of orgs) if (!clusterOf[n.id]) s += nodeTag(n, '');
  for (const n of Object.values(N)) if (n.type==='dept_head' && !(n.head_of && clusterOf[n.head_of])) s += nodeTag(n, 'pos');
  // grupos recolhidos: marcador com contagem + membros (e seus cargos) escondidos até abrir
  for (const g of Object.values(GROUPS)) { const [gx,gy]=pt(angle[g.id], radius[g.id]); const col = COL[g.sector];
    let inner = ''; for (const mid of g.members) { const m = N[mid]; inner += nodeTag(m, 'member'); for (const pid of (m.positions||[])) if (N[pid]) inner += nodeTag(N[pid], 'pos'); }
    s += `<g class="grpwrap" data-group="${g.id}"><a class="node group" href="#${g.parent}" data-id="${g.id}" aria-label="${g.members.length} unidades: ${esc(g.name)}, abrir" style="color:${col}" transform="translate(${gx.toFixed(1)},${gy.toFixed(1)})"><g style="stroke:${col}"><circle class="shape" r="${g.members.length>=100?7.4:g.members.length>=10?6.2:5.4}"/><text class="gcount" y="2.1"${g.members.length>=100?' style="font-size:5px"':''}>${g.members.length}</text></g></a><g class="grp">${inner}</g></g>`; }
  s += `</svg>`;
  document.getElementById('graph').innerHTML = s;
}
function ringArcRev(a0,a1,r){ const [x0,y0]=pt(a1,r),[x1,y1]=pt(a0,r); const big=(a1-a0)>180?1:0; return `M${x0},${y0} A${r},${r} 0 ${big} 0 ${x1},${y1}`; }
function esc(t){ return String(t).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;'); }
function curve(x1,y1,x2,y2){ const mx=(x1+x2)/2, my=(y1+y2)/2; const dx=x2-x1, dy=y2-y1; const k=0.12; const cx=mx-dy*k, cy=my+dx*k; return `M${x1.toFixed(1)},${y1.toFixed(1)} Q${cx.toFixed(1)},${cy.toFixed(1)} ${x2.toFixed(1)},${y2.toFixed(1)}`; }
