// Pré-renderiza a roda (SVG) no build, executando graph.core.js + atlas.js num contexto sem DOM.
// Uso: node scripts/render_wheel.js build/graph.core.js web/atlas.js build/wheel.svg
const fs = require('fs'), vm = require('vm');
const [core, atlas, out] = process.argv.slice(2);
let captured = '';
const el = { set innerHTML(v) { captured = v; }, get innerHTML() { return captured; }, classList: { add(){}, remove(){}, toggle(){} }, setAttribute(){} };
const document = { getElementById: () => el, querySelector: () => null, querySelectorAll: () => [], addEventListener(){}, documentElement: { dataset: {} } };
const ctx = { window: {}, document, console, Math, JSON, Object, Array, String, Number, Set, Map };
ctx.window.document = document;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(core, 'utf8') + '\n' + fs.readFileSync(atlas, 'utf8') + '\ndraw();', ctx, { filename: 'atlas.js' });
if (!captured.includes('<svg')) { console.error('render_wheel: SVG não gerado'); process.exit(1); }
fs.writeFileSync(out, captured);
console.error(`render_wheel: ${(captured.length/1024).toFixed(0)} KB`);
