// Convierte el atlas anatomico de 826 mallas en un modelo de quince, uno por
// grupo muscular de los que la app ya calcula. Se ejecuta en el PC, nunca en
// el movil: lo que viaja en la APK es el resultado.
import { NodeIO } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import { flatten, dedup, prune, weld, simplify, draco, joinPrimitives } from '@gltf-transform/functions';
import { MeshoptSimplifier } from 'meshoptimizer';
import draco3d from 'draco3dgltf';
import fs from 'node:fs';

const CLAVES = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const FUERA = ['bursa', 'tendon sheath', 'sheath of', 'cartilage', 'trochlea',
               'aponeurosis', 'adductor hallucis', 'adductor pollicis',
               'flexor hallucis brevis'];

function grupoDe(nombre) {
  const b = (nombre || '').toLowerCase();
  if (FUERA.some((f) => b.includes(f))) return 'resto';
  for (const [k, palabras] of Object.entries(CLAVES)) {
    for (const p of palabras) if (b.includes(p)) return k;
  }
  return 'resto';
}

const io = new NodeIO()
  .registerExtensions(ALL_EXTENSIONS)
  .registerDependencies({
    'draco3d.decoder': await draco3d.createDecoderModule(),
    'draco3d.encoder': await draco3d.createEncoderModule(),
  });

const doc = await io.read(process.argv[2]);
const raiz = doc.getRoot();
console.log('entrada: mallas', raiz.listMeshes().length, '| nodos', raiz.listNodes().length);

// El grupo se decide ANTES de aplanar, con el nombre del nodo original: al
// aplanar se pierde la jerarquia y con ella el nombre anatomico.
const grupoPorMalla = new Map();
for (const n of raiz.listNodes()) {
  const m = n.getMesh();
  if (!m) continue;
  const g = grupoDe(n.getName() || m.getName());
  const previo = grupoPorMalla.get(m);
  // Una malla compartida por nodos de grupos distintos no se puede repartir.
  grupoPorMalla.set(m, previo && previo !== g ? 'resto' : g);
}

await doc.transform(flatten(), dedup());

// Un material por grupo: joinPrimitives exige que las piezas lo compartan.
const materiales = new Map();
for (const g of [...Object.keys(CLAVES), 'resto']) {
  materiales.set(g, doc.createMaterial(g).setRoughnessFactor(0.85).setMetallicFactor(0.0));
}

const porGrupo = new Map();
for (const m of raiz.listMeshes()) {
  const g = grupoPorMalla.get(m) || 'resto';
  for (const p of m.listPrimitives()) {
    // Fuera todo lo que no sea geometria: el color lo pone la app en marcha.
    for (const sem of p.listSemantics()) {
      if (sem !== 'POSITION' && sem !== 'NORMAL') p.setAttribute(sem, null);
    }
    p.setMaterial(materiales.get(g));
    if (!porGrupo.has(g)) porGrupo.set(g, []);
    porGrupo.get(g).push(p);
  }
}

const escena = raiz.listScenes()[0];
for (const n of raiz.listNodes()) n.dispose();

let total = 0;
for (const [g, prims] of porGrupo) {
  const unida = prims.length === 1 ? prims[0] : joinPrimitives(prims);
  const malla = doc.createMesh(g).addPrimitive(unida);
  escena.addChild(doc.createNode(g).setMesh(malla));
  const n = unida.getIndices()
    ? unida.getIndices().getCount() / 3
    : unida.getAttribute('POSITION').getCount() / 3;
  total += n;
  console.log('  ' + g.padEnd(12) + prims.length.toString().padStart(5) + ' piezas  ' +
              Math.round(n).toString().padStart(7) + ' triangulos');
}
console.log('total triangulos:', Math.round(total));

await doc.transform(prune(), weld());

const objetivo = Number(process.argv[5] || 0.35);
await MeshoptSimplifier.ready;
await doc.transform(simplify({ simplifier: MeshoptSimplifier, ratio: objetivo, error: 0.002 }));

let tras = 0;
for (const m of raiz.listMeshes()) {
  for (const p of m.listPrimitives()) {
    tras += (p.getIndices() ? p.getIndices().getCount() : p.getAttribute('POSITION').getCount()) / 3;
  }
}
console.log('tras simplificar:', Math.round(tras), 'triangulos');

await doc.transform(draco({ method: 'edgebreaker' }));
await io.write(process.argv[4], doc);
console.log('escrito', process.argv[4], (fs.statSync(process.argv[4]).size / 1048576).toFixed(2), 'MB');
