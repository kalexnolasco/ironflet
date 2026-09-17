# scripts/

Developer tooling. None of it runs at app start-up; all of it is invoked by
hand or by `make`.

| file | what it does |
|---|---|
| `build_exercise_bundle.py` | Rebuilds the exercise-image tarball published on a GitHub Release, and records the source manifest the tests read. |
| `exercise_sources.json` | Generated data — which slugs the published release and the upstream catalog actually hold. **Committed on purpose**; `tests/test_asset_manager.py` reads it. |
| `vendor_canvaskit.py` | Fetches CanvasKit into the installed `flet_web`. Run *after* `uv sync` — `make deps` orders them correctly. |
| `make_timer_sounds.py` | Generates the rest-timer audio in `assets/sounds/`. |
| `probar_en_emulador.sh` | Builds and installs the APK on a running Android emulator. |
| `forja.mjs` | Turns the 826-mesh anatomy atlas into the 15-mesh `anatomia/cuerpo.glb` the app ships. Node, not Python — the glTF toolchain lives there. |
| `claves.json` | Which anatomical names belong to which muscle group. **Committed on purpose**: it is the whole mapping, and `forja.mjs` is useless without it. |

---

## Exercise images

### How the app gets them

Images are not in the APK and not in git (`.gitignore` excludes
`assets/exercises/`). `asset_manager.py` installs them at runtime from **two**
sources:

1. **The release tarball** — one request for the whole set. Fast path.
2. **Upstream Free Exercise DB**, one file at a time — repair path, for
   whatever the tarball did not deliver.

The repair path exists because the tarball is a *snapshot* of
`exercise_images.EXERCISE_IMAGE` as it stood the day it was built. `v0.1.0`
holds 68 slugs; the catalog now needs 70. `Barbell_Hip_Thrust` and
`Full_Range-Of-Motion_Lat_Pulldown` were added afterwards and hand-copied into
a local `assets/` directory, so they showed on the developer's PC and were
missing on the phone — which installs from the tarball and nothing else.

That is now repaired automatically at runtime, and Profile can report
`missing_summary()` when anything is short. But 70 individual requests over gym
Wi-Fi is not how the bundle should be delivered. Publishing a complete tarball
puts every image back in the one-request path.

### Rebuilding the bundle

```bash
# Is every slug in the catalog obtainable? Writes nothing.
.venv/bin/python scripts/build_exercise_bundle.py --check

# Build it. Frames come from ./assets/exercises or the cache when they are
# already there, and from upstream otherwise, so a rebuild on a machine with
# the images installed is offline and instant.
.venv/bin/python scripts/build_exercise_bundle.py
# → build/exercises.tar.gz  (70 slugs, ~9.2 MB)

# Force a fresh fetch of everything.
.venv/bin/python scripts/build_exercise_bundle.py --clean
```

The script re-opens what it wrote and fails if the archive is short of the
catalog. Building and trusting the build is how the two slugs went missing.

### Publishing it

```bash
gh release create v0.2.0 build/exercises.tar.gz \
    --repo kalexnolasco/ironflet --title v0.2.0 --notes "Exercise images"
```

Then **bump `asset_manager.RELEASE_VERSION` to `v0.2.0`**. It is baked into
the marker file that records "this release's tarball was already extracted
here", so without the bump every phone on the old bundle assumes it is done
and never fetches the new one.

Finally, re-record the manifest so the tests describe reality:

```bash
.venv/bin/python scripts/build_exercise_bundle.py --refresh-manifest
git add scripts/exercise_sources.json
```

### Adding an exercise image

1. Add the name → slug entry to `exercise_images.EXERCISE_IMAGE`. The slug is
   the `id` field in
   [free-exercise-db](https://github.com/yuhonas/free-exercise-db)'s
   `dist/exercises.json`.
2. Check the slug is also present in `exercise_details.py` — `EXERCISE_IMAGE`
   is the key into it, so a slug the details table does not carry drops that
   exercise out of `sets_per_muscle_group`.
3. Run `pytest tests/test_asset_manager.py`. If the slug is new upstream, the
   coverage test fails until you refresh the manifest — that failure is the
   point: it is what would otherwise have been a silent hole on the phone.
4. Optionally rebuild and publish the bundle so it arrives in one request
   instead of being repaired file by file.

The app keeps working without step 4: the repair path fetches it.

### Licensing

Content is [Free Exercise DB](https://github.com/yuhonas/free-exercise-db),
Unlicense / public domain. We redistribute the subset this app maps.

---

## The 3D body

`anatomia/cuerpo.glb` is **generated**, and this is how. The source is an
8.2 MB, 826-mesh anatomical atlas — Z-Anatomy via
[hpfrei/body-anatomy-3d-viewer](https://github.com/hpfrei/body-anatomy-3d-viewer),
`public/body.glb`, CC BY-SA 4.0. It is *not* in this repository: download it
when you need to rebuild.

```bash
npm install @gltf-transform/core @gltf-transform/extensions \
            @gltf-transform/functions meshoptimizer draco3dgltf
node scripts/forja.mjs body.glb scripts/claves.json anatomia/cuerpo.glb 0.35
```

The last argument is how much geometry to keep (0.35 = 35 % of the triangles).
The script prints how many source pieces landed in each group and the triangle
count before and after, which is the only way to notice that a keyword in
`claves.json` stopped matching anything.

Two things to know before touching `claves.json`:

* **Order matters.** The first group whose keyword matches wins, and several
  names collide across the body — `extensor digitorum longus` is a calf muscle
  and `extensor digitorum` is a forearm one. `calves` is listed first for
  exactly that reason.
* **The group names are the app's muscle keys**, the English strings
  `analytics.sets_per_muscle_group` returns. They become the mesh names, and
  the page colours by `mesh.name === key`. Rename one and that muscle silently
  stops taking colour; `tests/test_cuerpo3d.py` is what catches it.

Attribution and the share-alike obligation: `anatomia/CREDITOS.md`.
