// O painel da esquerda não pode virar uma parede de rolagem, e nenhuma lista pode despejar
// centenas de linhas iguais.
//
// Escrita em 04/11/2026, depois de o usuário dizer "o scroll do lado esquerdo tá muito longo".
// Medido no ar antes de mexer: o painel da home tinha 58.793px, 97,7 telas — e uma única lista,
// "Quem sai com a posse de 2027", despejava 459 cargos do Executivo em 43.140px: 95% de toda a
// rolagem. Ficou lá semanas porque nada media isso. Agora mede.
//
// Dois limites, e o segundo é o que pega o estrago cedo:
//   TETO_TELAS   — altura total do painel, em telas de 900px. Pega crescimento geral.
//   TETO_BLOCO   — altura de um bloco VISÍVEL só (o que está dentro de <details> fechado não conta,
//                  porque não custa rolagem a quem não abriu). A lista de 459 media 48 telas por si
//                  e cairia aqui no primeiro dia. O critério é ALTURA, não número de filhos: uma
//                  faixa de 96 barrinhas de gráfico tem 96 filhos e 44px — não é parede de rolagem.
const { chromium } = require('playwright');
const BASE = process.argv[2] || 'http://localhost:8767';
// Os tetos ficam ACIMA do pior caso de hoje, com folga: a checagem existe para pegar CRESCIMENTO,
// não para forçar corte de conteúdo editorial, que é decisão do dono do projeto. Medido em
// 04/11/2026, com viewport de 900px: painel mais alto = home na aba "parado", 27,8 telas; bloco mais
// alto = o painel dessa aba, 12,8 telas (8 MPs, 6 pedidos de CPI, 1 caso acompanhado, 6 vetos e 9
// temas, cada um com resumo em linguagem simples). A parede de 459 cargos media 48 telas num bloco
// só e 97,7 no painel: qualquer coisa parecida cai nos dois limites no primeiro dia.
const TETO_TELAS = 35;
const TETO_BLOCO = 15;
// uma de cada forma de painel: home (as quatro abas), órgão grande, Casa, cargo, pessoa
const VISTAS = [
  { nome: 'home',              hash: '',                          abas: ['mudou', 'parado', 'dinheiro', 'imprensa'] },
  { nome: 'ministério',        hash: '#br-ministerio-da-fazenda' },
  { nome: 'Câmara',            hash: '#br-camara-dos-deputados' },
  { nome: 'autarquia grande',  hash: '#br-inss' },
  { nome: 'cargo',             hash: '#br-supremo-tribunal-federal-ministro' },
  { nome: 'pessoa',            hash: '#br-p-cd-204379' },
];

const medir = () => {
  const p = document.getElementById('panel');
  if (!p) return { erro: 'sem #panel' };
  // lista visível: elemento com muitos filhos que não está dentro de <details> fechado
  const visivel = el => !el.closest('details:not([open])') && el.offsetParent !== null;
  // Invólucro não é bloco: #content tem a altura do painel inteiro, e culpá-lo não diz nada. Um
  // invólucro se reconhece por ter um filho com quase toda a sua altura; a lista de 459 cargos tinha
  // 459 filhos de 94px cada, nenhum perto do total — é ela que se quer acusar.
  const envoltorio = el => {
    const h = el.offsetHeight;
    if (!h) return true;
    for (const c of el.children) if (c.offsetHeight > h * 0.7) return true;
    return false;
  };
  let pior = { telas: 0, itens: 0, cls: '' };
  for (const el of document.querySelectorAll('#panel div, #panel ul, #panel ol')) {
    // #content é o próprio conteúdo do painel: tem a altura de tudo e não é o culpado de nada.
    // O teto do painel já responde por ele.
    if (el.id === 'content' || el.id === 'panel') continue;
    if (el.children.length < 6 || !visivel(el) || envoltorio(el)) continue;
    const t = +(el.offsetHeight / 900).toFixed(1);
    if (t > pior.telas) pior = { telas: t, itens: el.children.length, cls: (el.className || '').toString().slice(0, 24) || el.id || '(sem classe)' };
  }
  return { telas: +(p.scrollHeight / 900).toFixed(1), px: p.scrollHeight, pior };
};

(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
  const erros = [];
  p.on('pageerror', x => erros.push(String(x).slice(0, 110)));
  let ruins = 0, linhas = [];
  for (const v of VISTAS) {
    // goto devolve null quando só o hash muda (navegação no mesmo documento): não dá para usar o
    // retorno como prova de carregamento. Carrega-se a página limpa e confere-se o painel depois.
    let falhou = false;
    await p.goto(BASE + '/' + v.hash, { waitUntil: 'domcontentloaded', timeout: 15000 }).catch(() => { falhou = true; });
    if (falhou) { console.log(`  ${v.nome}: não carregou`); ruins++; continue; }
    await p.waitForTimeout(2400);
    const titulo = await p.evaluate(() => (document.querySelector('#panel h1')?.textContent || '').trim().slice(0, 40));
    if (v.hash && /Quem manda em quê/.test(titulo)) { console.log(`  ${v.nome}: ${v.hash} caiu na home (nó não existe?)`); ruins++; continue; }
    for (const aba of (v.abas || [null])) {
      if (aba) { await p.evaluate(a => document.getElementById('tab-' + a)?.click(), aba); await p.waitForTimeout(700); }
      const d = await p.evaluate(medir);
      const rot = v.nome + (aba ? ` · ${aba}` : '');
      if (d.erro) { console.log(`  ${rot}: ${d.erro}`); ruins++; continue; }
      const mal = [];
      if (d.telas > TETO_TELAS) mal.push(`${d.telas} telas de rolagem (teto ${TETO_TELAS})`);
      if (d.pior.telas > TETO_BLOCO) mal.push(`bloco visível de ${d.pior.telas} telas em .${d.pior.cls} com ${d.pior.itens} itens (teto ${TETO_BLOCO})`);
      linhas.push(`  ${rot.padEnd(22)} ${String(d.telas).padStart(5)} telas · maior bloco ${String(d.pior.telas).padStart(5)} telas${mal.length ? '  ← ' + mal.join('; ') : ''}`);
      if (mal.length) ruins++;
    }
  }
  console.log(linhas.join('\n'));
  if (erros.length) { console.log('  erro de página: ' + erros.slice(0, 2).join(' | ')); ruins++; }
  await b.close();
  if (ruins) { console.log(`${ruins} vista(s) acima do limite de rolagem`); process.exit(1); }
  console.log(`rolagem dentro do limite em ${linhas.length} vistas (teto ${TETO_TELAS} telas no painel, ${TETO_BLOCO} por bloco)`);
})();
