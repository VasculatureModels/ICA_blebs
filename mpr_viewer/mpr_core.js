/*
 * Noyau du viewer MPR (sans DOM) : géométrie des coupes, rendu d'une coupe, pinceau / gomme sur les voxels,
 * annulation, extraction de surface 3D (surface nets) et (dé)compression gzip.
 *
 * Convention des volumes : tableau 1D, x le plus rapide : idx = i + nx * (j + ny * k), axes en RAS+
 * (i : vers la droite du patient, j : vers l'avant, k : vers le haut).
 * Affichage radiologique : la droite du patient est à gauche de l'écran ; en axial l'avant est en haut ;
 * en sagittal l'avant est à gauche.
 */
(function (root) {
  "use strict";
  const MPR = {};

  // ------------------------------------------------------------------ base64 / gzip
  MPR.b64ToBytes = function (b64) {
    const bin = atob(b64), u8 = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
    return u8;
  };
  MPR.bytesToB64 = function (u8) {
    let s = "";
    const CH = 0x8000;
    for (let i = 0; i < u8.length; i += CH) s += String.fromCharCode.apply(null, u8.subarray(i, i + CH));
    return btoa(s);
  };
  async function pipe(u8, transform) {
    const stream = new Blob([u8]).stream().pipeThrough(transform);
    return new Uint8Array(await new Response(stream).arrayBuffer());
  }
  MPR.gunzip = (b64) => pipe(MPR.b64ToBytes(b64), new DecompressionStream("gzip"));
  MPR.gzip = (u8) => pipe(u8, new CompressionStream("gzip"));

  // ------------------------------------------------------------------ géométrie des coupes
  // d : { nx, ny, nz, sx, sy, sz }
  MPR.planeInfo = function (plane, d) {
    if (plane === "axial") return { w: d.nx, h: d.ny, psx: d.sx, psy: d.sy, fixed: 2 };
    if (plane === "coronal") return { w: d.nx, h: d.nz, psx: d.sx, psy: d.sz, fixed: 1 };
    return { w: d.ny, h: d.nz, psx: d.sy, psy: d.sz, fixed: 0 }; // sagittal
  };
  MPR.voxelToPixel = function (plane, d, i, j, k) {
    if (plane === "axial") return [d.nx - 1 - i, d.ny - 1 - j];
    if (plane === "coronal") return [d.nx - 1 - i, d.nz - 1 - k];
    return [d.ny - 1 - j, d.nz - 1 - k];
  };
  MPR.pixelToVoxel = function (plane, d, col, row, cur) {
    if (plane === "axial") return [d.nx - 1 - col, d.ny - 1 - row, cur[2]];
    if (plane === "coronal") return [d.nx - 1 - col, cur[1], d.nz - 1 - row];
    return [cur[0], d.ny - 1 - col, d.nz - 1 - row];
  };
  // idx(col, row) = base + col * sc + row * sr
  MPR.planeStrides = function (plane, d, cur) {
    const { nx, ny, nz } = d;
    if (plane === "axial") return { base: nx - 1 + nx * (ny - 1) + nx * ny * cur[2], sc: -1, sr: -nx };
    if (plane === "coronal") return { base: nx - 1 + nx * cur[1] + nx * ny * (nz - 1), sc: -1, sr: -nx * ny };
    return { base: cur[0] + nx * (ny - 1) + nx * ny * (nz - 1), sc: -nx, sr: -nx * ny };
  };

  MPR.makeLut = function (center, width) {
    const lut = new Uint8Array(256), lo = center - width / 2, w = Math.max(1, width);
    for (let i = 0; i < 256; i++) lut[i] = Math.max(0, Math.min(255, Math.round(((i - lo) / w) * 255)));
    return lut;
  };

  // colors : tableau de 256 entrées [r,g,b] ou null (label masqué) ; alpha : 0..1 ; out : Uint8ClampedArray w*h*4
  MPR.renderSlice = function (plane, d, cur, image, labels, lut, colors, alpha, out) {
    const { w, h } = MPR.planeInfo(plane, d);
    const { base, sc, sr } = MPR.planeStrides(plane, d, cur);
    const ia = 1 - alpha;
    let p = 0;
    for (let row = 0; row < h; row++) {
      let idx = base + row * sr;
      for (let col = 0; col < w; col++, idx += sc, p += 4) {
        const g = image ? lut[image[idx]] : 0;
        let r = g, gg = g, b = g;
        const lab = labels[idx];
        if (lab) {
          const c = colors[lab];
          if (c) { r = r * ia + c[0] * alpha; gg = gg * ia + c[1] * alpha; b = b * ia + c[2] * alpha; }
        }
        out[p] = r; out[p + 1] = gg; out[p + 2] = b; out[p + 3] = 255;
      }
    }
  };

  // ------------------------------------------------------------------ volume éditable
  // opts : { bleb, parent } ; tout label >= bleb est un bleb (chacun garde son label)
  MPR.createVol = function (dims, spacing, image, labels, opts) {
    const [nx, ny, nz] = dims;
    const v = {
      nx, ny, nz, sx: spacing[0], sy: spacing[1], sz: spacing[2], n: nx * ny * nz,
      image, labels, init: Uint8Array.from(labels), BLEB: opts.bleb, PARENT: opts.parent,
      stroke: null, undoStack: [],
    };
    v.base = new Uint8Array(v.n);      // ce que rend la gomme : bleb d'origine -> anévrisme, fond -> fond
    for (let i = 0; i < v.n; i++) v.base[i] = v.init[i] >= v.BLEB ? v.PARENT : v.init[i];
    return v;
  };

  // zone peignable : "aneurysm" (anévrisme + blebs), "mask" (tout le masque), "everywhere" (fond compris)
  MPR.canPaint = function (v, c, zone) {
    if (zone === "everywhere") return true;
    if (zone === "mask") return c > 0;
    if (zone === "parent") return c === v.PARENT;   // phase 2 guidée : le pinceau ne prend que sur l'anévrisme, jamais sur un autre bleb
    return c === v.PARENT || c >= v.BLEB;
  };

  MPR.beginStroke = function (v) { v.stroke = new Map(); };
  MPR.endStroke = function (v) {
    const s = v.stroke;
    v.stroke = null;
    if (s && s.size) { v.undoStack.push(s); return s.size; }
    return 0;
  };
  function setVoxel(v, idx, label) {
    if (v.stroke && !v.stroke.has(idx)) v.stroke.set(idx, v.labels[idx]);
    v.labels[idx] = label;
  }
  // o : { label, erase, zone, eraseSel }
  function applyVoxel(v, idx, o) {
    const c = v.labels[idx];
    if (o.erase) {
      if (c >= v.BLEB && (!o.eraseSel || c === o.label)) setVoxel(v, idx, v.base[idx]);
    } else if (c !== o.label && MPR.canPaint(v, c, o.zone)) {
      setVoxel(v, idx, o.label);
    }
  }
  // Tampon du pinceau centré sur le voxel (ci,cj,ck) : disque dans le plan de la coupe, ou sphère 3D
  MPR.stamp = function (v, plane, ci, cj, ck, radiusMm, sphere, o) {
    const fixed = MPR.planeInfo(plane, v).fixed, r2 = radiusMm * radiusMm;
    const ri = Math.ceil(radiusMm / v.sx), rj = Math.ceil(radiusMm / v.sy), rk = Math.ceil(radiusMm / v.sz);
    const di = !sphere && fixed === 0 ? 0 : ri, dj = !sphere && fixed === 1 ? 0 : rj, dk = !sphere && fixed === 2 ? 0 : rk;
    for (let k = Math.max(0, ck - dk); k <= Math.min(v.nz - 1, ck + dk); k++) {
      const ez = (k - ck) * v.sz;
      for (let j = Math.max(0, cj - dj); j <= Math.min(v.ny - 1, cj + dj); j++) {
        const ey = (j - cj) * v.sy;
        for (let i = Math.max(0, ci - di); i <= Math.min(v.nx - 1, ci + di); i++) {
          const ex = (i - ci) * v.sx;
          if (ex * ex + ey * ey + ez * ez > r2) continue;
          applyVoxel(v, i + v.nx * (j + v.ny * k), o);
        }
      }
    }
  };
  // Trait continu entre deux voxels a et b (interpolation, pour ne pas laisser de trous)
  MPR.segment = function (v, plane, a, b, radiusMm, sphere, o) {
    const dist = Math.hypot((b[0] - a[0]) * v.sx, (b[1] - a[1]) * v.sy, (b[2] - a[2]) * v.sz);
    const step = Math.max(0.5, radiusMm * 0.5), n = Math.max(1, Math.ceil(dist / step));
    for (let s = (a === b ? 0 : 1); s <= n; s++) {
      const t = s / n;
      MPR.stamp(v, plane, Math.round(a[0] + (b[0] - a[0]) * t), Math.round(a[1] + (b[1] - a[1]) * t),
        Math.round(a[2] + (b[2] - a[2]) * t), radiusMm, sphere, o);
    }
  };
  MPR.undo = function (v) {
    const s = v.undoStack.pop();
    if (!s) return false;
    for (const [idx, old] of s) v.labels[idx] = old;
    return true;
  };
  MPR.resetAll = function (v) { v.labels.set(v.init); v.undoStack.length = 0; };
  // Remet un seul bleb dans son état d'origine (un bleb ajouté disparaît) ; les autres blebs ne bougent pas, sauf
  // là où ils occupaient un voxel d'origine de ce bleb. Compte comme un trait : « Annuler » peut le défaire.
  MPR.resetLabel = function (v, id) {
    MPR.beginStroke(v);
    for (let i = 0; i < v.n; i++) {
      const was = v.init[i] === id, is = v.labels[i] === id;
      if (was && !is) setVoxel(v, i, id);
      else if (!was && is) setVoxel(v, i, v.base[i]);
    }
    return MPR.endStroke(v);
  };
  // « Supprimer » un bleb pré-segmenté (phase 2) : ses voxels sont rendus tout de suite à l'anévrisme, à l'écran
  // comme dans le masque envoyé. Hors historique « Annuler » (vidé), pour qu'un « Annuler » ne le fasse pas revenir.
  // Auteurs de ce bloc : Fakhrielddine Bader, Florent Autrusseau (17/11/2026).
  MPR.hideLabel = function (v, id) {
    let n = 0;
    for (let i = 0; i < v.n; i++) if (v.labels[i] === id) { v.labels[i] = v.base[i]; n++; }
    v.undoStack.length = 0;
    return n;
  };
  // Annule la suppression : le bleb retrouve ses voxels d'origine (là où ils sont encore à l'anévrisme).
  MPR.restoreLabel = function (v, id) {
    let n = 0;
    for (let i = 0; i < v.n; i++) if (v.init[i] === id && v.labels[i] === v.base[i]) { v.labels[i] = id; n++; }
    v.undoStack.length = 0;
    return n;
  };
  // Nombre de voxels par lesquels chaque bleb diffère de son état d'origine : { label: n }.
  MPR.changedByLabel = function (v) {
    const m = {};
    for (let i = 0; i < v.n; i++) {
      const a = v.init[i], b = v.labels[i];
      if (a === b) continue;
      if (a >= v.BLEB) m[a] = (m[a] || 0) + 1;
      if (b >= v.BLEB) m[b] = (m[b] || 0) + 1;
    }
    return m;
  };
  MPR.isEdited = function (v) {
    for (let i = 0; i < v.n; i++) if (v.labels[i] !== v.init[i]) return true;
    return false;
  };
  MPR.countByLabel = function (labels, minLabel) {
    const m = {};
    for (let i = 0; i < labels.length; i++) { const c = labels[i]; if (c >= minLabel) m[c] = (m[c] || 0) + 1; }
    return m;
  };

  // ------------------------------------------------------------------ surface 3D (surface nets, binaire)
  const EDGES = [];
  for (let bit = 0; bit < 3; bit++) for (let a = 0; a < 8; a++) if (!((a >> bit) & 1)) EDGES.push([a, a | (1 << bit)]);

  // Surface de l'union des labels non nuls ; chaque sommet porte le label majoritaire de sa cellule.
  // Coordonnées en mm (x = i * sx, ...). Triangles orientés vers l'extérieur.
  MPR.surfaceNets = function (labels, nx, ny, nz, sx, sy, sz) {
    let x0 = nx, y0 = ny, z0 = nz, x1 = -1, y1 = -1, z1 = -1;
    for (let k = 0; k < nz; k++) for (let j = 0; j < ny; j++) {
      const o = nx * (j + ny * k);
      for (let i = 0; i < nx; i++) if (labels[o + i]) {
        if (i < x0) x0 = i; if (i > x1) x1 = i; if (j < y0) y0 = j; if (j > y1) y1 = j; if (k < z0) z0 = k; if (k > z1) z1 = k;
      }
    }
    if (x1 < 0) return { positions: new Float32Array(0), indices: new Uint32Array(0), vlabels: new Uint8Array(0) };

    const cx0 = x0 - 1, cy0 = y0 - 1, cz0 = z0 - 1;
    const cnx = x1 - x0 + 2, cny = y1 - y0 + 2, cnz = z1 - z0 + 2;
    const vmap = new Int32Array(cnx * cny * cnz).fill(-1);
    const get = (x, y, z) => (x < 0 || y < 0 || z < 0 || x >= nx || y >= ny || z >= nz ? 0 : labels[x + nx * (y + ny * z)]);
    const pos = [], vl = [], cv = new Uint8Array(8), cnt = new Uint16Array(256);
    let nv = 0;

    for (let cz = cz0; cz <= z1; cz++) for (let cy = cy0; cy <= y1; cy++) for (let cx = cx0; cx <= x1; cx++) {
      let mask = 0;
      for (let b = 0; b < 8; b++) {
        const val = get(cx + (b & 1), cy + ((b >> 1) & 1), cz + ((b >> 2) & 1));
        cv[b] = val; if (val) mask |= 1 << b;
      }
      if (mask === 0 || mask === 255) continue;
      let ax = 0, ay = 0, az = 0, ne = 0;
      for (const e of EDGES) {
        const a = e[0], b = e[1];
        if (((mask >> a) & 1) !== ((mask >> b) & 1)) {
          ax += ((a & 1) + (b & 1)) / 2; ay += (((a >> 1) & 1) + ((b >> 1) & 1)) / 2; az += (((a >> 2) & 1) + ((b >> 2) & 1)) / 2; ne++;
        }
      }
      pos.push((cx + ax / ne) * sx, (cy + ay / ne) * sy, (cz + az / ne) * sz);
      let best = 0, bc = 0;                           // label majoritaire parmi les coins non nuls
      for (let b = 0; b < 8; b++) if (cv[b]) { const c = ++cnt[cv[b]]; if (c > bc) { bc = c; best = cv[b]; } }
      for (let b = 0; b < 8; b++) cnt[cv[b]] = 0;
      vl.push(best);
      vmap[cx - cx0 + cnx * (cy - cy0 + cny * (cz - cz0))] = nv++;
    }

    const idxs = [], c3 = [0, 0, 0];
    const cell = (x, y, z) => (x < cx0 || y < cy0 || z < cz0 || x > x1 || y > y1 || z > z1 ? -1 : vmap[x - cx0 + cnx * (y - cy0 + cny * (z - cz0))]);
    for (let z = cz0; z <= z1; z++) for (let y = cy0; y <= y1; y++) for (let x = cx0; x <= x1; x++) {
      const s0 = get(x, y, z) ? 1 : 0;
      for (let a = 0; a < 3; a++) {
        const s1 = get(x + (a === 0), y + (a === 1), z + (a === 2)) ? 1 : 0;
        if (s0 === s1) continue;
        const bAx = (a + 1) % 3, cAx = (a + 2) % 3;
        const q = (db, dc) => { c3[0] = x; c3[1] = y; c3[2] = z; c3[bAx] += db; c3[cAx] += dc; return cell(c3[0], c3[1], c3[2]); };
        const v00 = q(-1, -1), v10 = q(0, -1), v11 = q(0, 0), v01 = q(-1, 0);
        if (v00 < 0 || v10 < 0 || v11 < 0 || v01 < 0) continue;
        const o = s0 ? [v00, v10, v11, v01] : [v00, v01, v11, v10];   // normale vers l'extérieur
        idxs.push(o[0], o[1], o[2], o[0], o[2], o[3]);
      }
    }
    return { positions: new Float32Array(pos), indices: new Uint32Array(idxs), vlabels: Uint8Array.from(vl) };
  };

  // Lissage de Taubin (lambda | mu) : adoucit les marches d'escalier sans réduire le volume
  MPR.smooth = function (positions, indices, iters, lambda, mu) {
    const nv = positions.length / 3;
    if (!nv || !iters) return positions;
    const sum = new Float32Array(positions.length), cnt = new Uint16Array(nv);
    const pass = (f) => {
      sum.fill(0); cnt.fill(0);
      for (let t = 0; t < indices.length; t += 3) {
        for (let e = 0; e < 3; e++) {
          const a = indices[t + e], b = indices[t + (e + 1) % 3];
          sum[3 * a] += positions[3 * b]; sum[3 * a + 1] += positions[3 * b + 1]; sum[3 * a + 2] += positions[3 * b + 2]; cnt[a]++;
          sum[3 * b] += positions[3 * a]; sum[3 * b + 1] += positions[3 * a + 1]; sum[3 * b + 2] += positions[3 * a + 2]; cnt[b]++;
        }
      }
      for (let i = 0; i < nv; i++) if (cnt[i]) for (let k = 0; k < 3; k++) {
        positions[3 * i + k] += f * (sum[3 * i + k] / cnt[i] - positions[3 * i + k]);
      }
    };
    for (let it = 0; it < iters; it++) { pass(lambda); pass(mu); }
    return positions;
  };

  root.MPR = MPR;
  if (typeof module !== "undefined" && module.exports) module.exports = MPR;
})(typeof globalThis !== "undefined" ? globalThis : this);
