# De dónde sale lo que hay en esta carpeta

Nada de esto es obra propia. Se guarda aquí, junto a los ficheros, porque una
atribución que vive en otro repositorio no acompaña al fichero cuando el
fichero se mueve.

## `cuerpo.glb` — Z-Anatomy · CC BY-SA 4.0

El modelo anatómico. Deriva de [Z-Anatomy](https://www.z-anatomy.com/), un
atlas anatómico libre, a través del visor de
[hpfrei/body-anatomy-3d-viewer](https://github.com/hpfrei/body-anatomy-3d-viewer),
que es quien lo simplificó y comprimió a un `.glb` de 8,2 MB manejable en un
navegador.

Licencia: **Creative Commons Attribution-ShareAlike 4.0 International**
(<http://creativecommons.org/licenses/by-sa/4.0/>).

Lo que obliga, si esta app llega a repartirse:

* **Atribución** — hay que citar el origen, enlazar la licencia y decir que se
  cambió. La app lo hace en la ayuda de «Series semanales por músculo».
* **Compartir igual** — cualquier obra derivada del modelo va bajo la misma
  licencia. Afecta al `.glb`, no al código de la app.

**Qué se cambió**: `scripts/forja.mjs` funde las 826 mallas del original en
quince —los catorce grupos musculares que la app calcula, más el resto del
cuerpo—, tira todo lo que no es posición y normal, simplifica la geometría al
35 % de sus triángulos y vuelve a comprimir con Draco. De 8,2 MB a 0,44 MB.
Para rehacerlo:

```
npm install @gltf-transform/core @gltf-transform/extensions \
            @gltf-transform/functions meshoptimizer draco3dgltf
node scripts/forja.mjs body.glb scripts/claves.json anatomia/cuerpo.glb 0.35
```

`body.glb` es el original, que **no** está en este repositorio: se baja de
`hpfrei/body-anatomy-3d-viewer`, en `public/body.glb`.

## `lib/` — three.js r160 · MIT

`three.module.js`, `GLTFLoader.js`, `DRACOLoader.js`, `OrbitControls.js` y
`utils/BufferGeometryUtils.js` son de [three.js](https://threejs.org/),
copyright 2010-2026 three.js authors, licencia MIT. Van copiados y no por CDN
porque el visor tiene que funcionar sin red, dentro del móvil.

Un solo cambio sobre el original: en `GLTFLoader.js`, el import de
`BufferGeometryUtils` pasó de `../utils/` a `./utils/`, porque aquí todo cuelga
de la misma carpeta y un salto hacia atrás se salía del directorio servido.

## `lib/draco/` — Draco · Apache 2.0

`draco_decoder.wasm` y `draco_wasm_wrapper.js` son de
[google/draco](https://github.com/google/draco), copyright The Draco Authors,
licencia Apache 2.0. Descomprimen la geometría del `.glb`.
