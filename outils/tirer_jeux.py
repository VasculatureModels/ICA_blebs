#!/usr/bin/env python3
"""Tirage des jeux de l'étude des observateurs : une playlist par observateur.

Auteurs : Fakhrielddine Bader, Florent Autrusseau.
Historique : 19/11/2026, v1.0.0.

Chaque observateur reçoit 60 cas : 20 cas COMMUNS aux trois observateurs (accord entre médecins) et 40 cas PROPRES
(jamais vus par les deux autres). Les cas sont tirés au hasard parmi les cas éligibles (playlist de l'étude) :
liste triée par analysis_id, puis random.Random(graine).sample ; les 20 premiers tirés sont les communs, les 40
suivants vont au 1er observateur, les 40 suivants au 2e, puis au 3e. Les cas non tirés sont listés.

Entrées (lecture seule) :
    --playlist-etude   playlist des cas éligibles, deux lignes par cas : « image ; segmentation » (phase 1) puis
                       « image ; segmentation_blebs » (phase 2), chemins relatifs (images/...) ;
    --manifeste        crops_manifest.csv des découpes (analysis_id <-> file_blebs) ; ce fichier ne doit JAMAIS être
                       donné aux observateurs (il contient le nombre de blebs pré-segmentés) ;
    --calibration      (facultatif) analysis_id des cas de calibration : seulement signalés dans le tirage.
Sorties (dossier NEUF) : playlist_<ID>.txt (format de l'application, mêmes chemins que la playlist de l'étude),
tirage_jeux.csv (groupe de chaque cas, cas de calibration), tirage_jeux.json (graine, effectifs, empreintes).
Les playlists se copient ensuite à côté de app_mpr.py (ou dans BLEB_PLAYLIST_DIR) ; les découpes vont dans images/.

Les découpes peuvent être régénérées (nouvelle pré-segmentation) SOUS LES MÊMES NOMS sans refaire le tirage.

Exemple :
    uv run python outils/tirer_jeux.py --playlist-etude ~/crops/playlist_etude_20261117.txt \\
        --manifeste ~/crops/crops_manifest.csv --calibration analyses_calibration.txt --sortie ~/tirage_jeux_20261119
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sys
from datetime import datetime
from pathlib import Path

VERSION = "tirer_jeux_v1.0.0"
OBSERVATEURS = (("JB", "Julien Boucherit"), ("GG", "Guillaume Geffroy"), ("VL", "Vincent L'Allinec"))
GRAINE = 20261119
N_COMMUNS, N_PROPRES = 20, 40


class TirageError(Exception):
    pass


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def lire_paires(playlist: Path) -> list[tuple[str, str]]:
    """Paires (ligne phase 1, ligne phase 2) de la playlist, dans l'ordre ; contrôle de leur forme."""
    lignes = [ln.strip() for ln in playlist.read_text(encoding="utf-8").splitlines()
              if ln.strip() and not ln.lstrip().startswith("#")]
    if len(lignes) % 2:
        raise TirageError(f"{playlist} : nombre impair de lignes ({len(lignes)})")
    paires = []
    for k in range(0, len(lignes), 2):
        a, b = lignes[k], lignes[k + 1]
        pa, pb = [x.strip() for x in a.split(";")], [x.strip() for x in b.split(";")]
        if len(pa) != 2 or len(pb) != 2 or pa[0] != pb[0] or "_blebs" in pa[1] or "_blebs" not in pb[1]:
            raise TirageError(f"{playlist}, lignes {k + 1}-{k + 2} : paire attendue « image ; seg » puis "
                              f"« image ; seg_blebs » de la même image, reçu : {a!r} / {b!r}")
        paires.append((a, b))
    return paires


def tirer(playlist: Path, manifeste: Path, sortie: Path, calibration: Path | None = None, graine: int = GRAINE,
          n_communs: int = N_COMMUNS, n_propres: int = N_PROPRES, observateurs=OBSERVATEURS, out=print) -> dict:
    playlist, manifeste, sortie = playlist.expanduser(), manifeste.expanduser(), sortie.expanduser()
    if sortie.exists():
        raise TirageError(f"--sortie existe déjà (aucun écrasement) : {sortie}")
    par_fichier = {r["file_blebs"]: r["analysis_id"] for r in csv.DictReader(open(manifeste, encoding="utf-8"))}
    cas = {}
    for a, b in lire_paires(playlist):
        f = Path(b.split(";")[1].strip()).name
        if f not in par_fichier:
            raise TirageError(f"{f} absent de {manifeste}")
        aid = par_fichier[f]
        if aid in cas:
            raise TirageError(f"cas en double dans la playlist : {aid}")
        cas[aid] = (a, b)
    calib = set()
    if calibration is not None:
        calib = {ln.strip() for ln in calibration.expanduser().read_text(encoding="utf-8").splitlines() if ln.strip()}
    besoin = n_communs + len(observateurs) * n_propres
    ids = sorted(cas)
    if len(ids) < besoin:
        raise TirageError(f"{len(ids)} cas éligibles, {besoin} nécessaires")
    tires = random.Random(graine).sample(ids, besoin)
    communs = sorted(tires[:n_communs])
    propres = {code: sorted(tires[n_communs + k * n_propres: n_communs + (k + 1) * n_propres])
               for k, (code, _) in enumerate(observateurs)}
    groupe = {a: "commun" for a in communs}
    for code, lst in propres.items():
        groupe.update({a: code for a in lst})

    sortie.mkdir(parents=True)
    date = datetime.now()
    fichiers = {}
    for code, nom in observateurs:
        jeu = sorted(communs + propres[code])
        p = sortie / f"playlist_{code}.txt"
        lignes = [f"# Étude des observateurs : jeu {code} ({nom}), {len(jeu)} cas = {n_communs} communs + "
                  f"{n_propres} propres.",
                  f"# Tirage {VERSION}, graine {graine}, {date:%d/%m/%Y %H:%M}. Ne pas modifier : refaire le tirage.",
                  "# L'application mélange l'ordre des cas pour chaque passation."]
        for a in jeu:
            lignes += list(cas[a])
        p.write_text("\n".join(lignes) + "\n", encoding="utf-8")
        fichiers[p.name] = sha256(p)
    with open(sortie / "tirage_jeux.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["analysis_id", "fichier_blebs", "groupe", "calibration"])
        w.writeheader()
        for a in ids:
            w.writerow({"analysis_id": a, "fichier_blebs": Path(cas[a][1].split(";")[1].strip()).name,
                        "groupe": groupe.get(a, "non_tire"), "calibration": "oui" if a in calib else "non"})
    info = {
        "version": VERSION, "date": date.isoformat(timespec="seconds"), "graine": graine,
        "n_eligibles": len(ids), "n_communs": n_communs, "n_propres": n_propres,
        "observateurs": {code: nom for code, nom in observateurs},
        "communs": communs, "propres": propres, "non_tires": sorted(set(ids) - set(tires)),
        "calibration_par_groupe": {g: sum(1 for a, x in groupe.items() if x == g and a in calib)
                                   for g in ["commun", *propres]},
        "entrees": {str(playlist): sha256(playlist), str(manifeste): sha256(manifeste),
                    **({str(calibration): sha256(calibration.expanduser())} if calibration else {})},
        "playlists_sha256": fichiers,
    }
    (sortie / "tirage_jeux.json").write_text(json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    out(f"{len(ids)} cas éligibles ; tirés : {besoin} ({n_communs} communs + {len(observateurs)} × {n_propres} propres) ;"
        f" non tirés : {len(ids) - besoin} ; graine {graine}")
    for code, nom in observateurs:
        out(f"  playlist_{code}.txt ({nom}) : {n_communs + n_propres} cas, dont "
            f"{info['calibration_par_groupe'][code] + info['calibration_par_groupe']['commun']} de calibration")
    out(f"Cas communs : {' '.join(communs)}")
    out(f"Sorties : {sortie}")
    return info


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Tirage des jeux de l'étude des observateurs (une playlist par observateur).")
    ap.add_argument("--playlist-etude", required=True, type=Path)
    ap.add_argument("--manifeste", required=True, type=Path, help="crops_manifest.csv (jamais donné aux observateurs)")
    ap.add_argument("--calibration", type=Path, default=None)
    ap.add_argument("--graine", type=int, default=GRAINE)
    ap.add_argument("--sortie", required=True, type=Path)
    a = ap.parse_args(argv)
    try:
        tirer(a.playlist_etude, a.manifeste, a.sortie, a.calibration, a.graine)
    except (TirageError, FileNotFoundError, KeyError) as e:
        print(f"ERREUR : {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
