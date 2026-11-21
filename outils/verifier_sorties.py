#!/usr/bin/env python3
"""Vérifie, indépendamment de l'application, ce qu'une passation a réellement enregistré.

Auteurs : Fakhrielddine Bader, Florent Autrusseau.
Historique :
    17/11/2026, Fakhrielddine Bader : première version (recette de l'application avant l'annotation de calibration).

Lecture seule. Pour une passation (observateur + session), l'outil relit notes_observateurs.csv, chaque NIfTI
résultat et la pré-segmentation d'origine, puis contrôle cas par cas :

  R1  fichier    : la phase 2 a un NIfTI résultat (export_nifti = ok) et il existe sur le disque.
  R2  grille     : le résultat a la même taille que la pré-segmentation (et la même géométrie si NIfTI).
  R3  intact     : hors de l'anévrisme et des blebs d'origine (fond, artères), aucun voxel n'a changé.
  R4  labels     : le résultat ne contient que 0, 1, 2 et des blebs (>= 3).
  R5  0 bleb     : après « 0 bleb », le résultat est la pré-segmentation sans aucun bleb.
  R6  décisions  : chaque bleb pré-segmenté a une décision ; « garde » = bleb identique ; « retouche » = bleb
                   modifié ; « supprime » = bleb absent, ses voxels rendus à l'anévrisme (2) ou repris par un
                   bleb que l'observateur a dessiné ensuite (« ajoute » ou « retouche »). Tout bleb du résultat
                   absent de la pré-segmentation est noté « ajoute », et inversement.
  R7  tableau    : voxels_blebs_initial, voxels_blebs_corrige et nb_blebs_final concordent avec les fichiers.
  R8  complet    : chaque cas a ses deux lignes (comptage puis segmentation), avec un nombre de blebs en phase 1.

Exemple :
    uv run python outils/verifier_sorties.py --sorties ~/essais_app_04mm_20261116 --observateur test_fakhri
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np

BLEB, PARENT = 3, 2
DECISIONS = {"garde", "retouche", "supprime"}  # blebs pré-segmentés ; un bleb ajouté est noté « ajoute »


def read_labels(path: str):
    """(tableau de labels, affine ou None). NIfTI via nibabel, NRRD via pynrrd ; même ordre d'axes (x, y, z)."""
    p = Path(path)
    if p.name.endswith((".nii", ".nii.gz")):
        import nibabel as nib
        img = nib.load(str(p))
        return np.asarray(img.dataobj).astype(np.int32), np.asarray(img.affine)
    import nrrd
    data, _ = nrrd.read(str(p))
    return np.asarray(data).astype(np.int32), None


def counts_str(arr: np.ndarray) -> str:
    """Même format que l'application : « 3:215; 4:456 » (labels >= 3)."""
    vals, n = np.unique(arr[arr >= BLEB], return_counts=True)
    return "; ".join(f"{int(v)}:{int(c)}" for v, c in zip(vals, n))


def parse_verdicts(s: str) -> Dict[int, str]:
    out = {}
    for part in (s or "").split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[int(k)] = v.strip()
    return out


def check_case(r1: Optional[Dict], r2: Optional[Dict]) -> List[str]:
    """Liste des problèmes d'un cas (vide si tout est conforme)."""
    pb = []
    if r1 is None or r2 is None:
        return ["R8 : il manque la ligne " + ("comptage" if r1 is None else "segmentation") + " (cas inachevé ?)"]
    if r1.get("nb_blebs", "") == "":
        pb.append("R8 : pas de nombre de blebs en phase 1")
    if r2.get("export_nifti") != "ok":
        return pb + [f"R1 : export_nifti = {r2.get('export_nifti')!r}"]
    out_file = r2.get("fichier_correction_nifti", "")
    if not out_file or not Path(out_file).exists():
        return pb + [f"R1 : fichier résultat introuvable : {out_file or '(vide)'}"]
    pre, pre_aff = read_labels(r2["segmentation"])
    res, res_aff = read_labels(out_file)
    if pre.shape != res.shape:
        return pb + [f"R2 : taille {res.shape} au lieu de {pre.shape}"]
    if pre_aff is not None and res_aff is not None and not np.allclose(pre_aff, res_aff, atol=1e-4):
        pb.append("R2 : géométrie (affine) différente de la pré-segmentation")

    outside = pre < PARENT
    if not np.array_equal(res[outside], pre[outside]):
        pb.append(f"R3 : {int((res[outside] != pre[outside]).sum())} voxel(s) modifié(s) hors de l'anévrisme")
    if (res < 0).any() or ((res > PARENT) & (res < BLEB)).any():
        pb.append("R4 : labels inattendus")

    if r2.get("phase2_ignoree") == "oui":
        expected = np.where(pre >= BLEB, PARENT, pre)
        if not np.array_equal(res, expected):
            pb.append("R5 : après « 0 bleb », le résultat n'est pas la pré-segmentation sans bleb")
        if r1.get("nb_blebs") not in ("0", ""):
            pb.append(f"R5 : phase 2 ignorée alors que la phase 1 donne {r1.get('nb_blebs')} bleb(s)")
    else:
        verdicts = parse_verdicts(r2.get("verdict_blebs", ""))
        pre_labs = set(int(v) for v in np.unique(pre[pre >= BLEB]))
        res_labs = set(int(v) for v in np.unique(res[res >= BLEB]))
        for lab in sorted(pre_labs):
            v = verdicts.get(lab)
            before, after = pre == lab, res == lab
            if v not in DECISIONS:
                pb.append(f"R6 : bleb {lab} sans décision valide ({v!r})")
            elif v == "garde" and not np.array_equal(before, after):
                pb.append(f"R6 : bleb {lab} « garde » mais modifié ({int((before != after).sum())} voxels)")
            elif v == "retouche" and np.array_equal(before, after):
                pb.append(f"R6 : bleb {lab} « retouche » mais identique à la pré-segmentation")
            elif v == "supprime":
                if after.any():
                    pb.append(f"R6 : bleb {lab} « supprime » encore présent ({int(after.sum())} voxels)")
                drawn = [k for k, d in verdicts.items() if d in ("ajoute", "retouche")]
                if not np.isin(res[before], [PARENT] + drawn).all():
                    pb.append(f"R6 : bleb {lab} « supprime » : des voxels ne sont ni rendus à l'anévrisme, "
                              f"ni repris par un bleb dessiné")
        new = res_labs - pre_labs
        noted_new = {k for k, v in verdicts.items() if v == "ajoute"}
        if new != noted_new:
            pb.append(f"R6 : blebs ajoutés dans le fichier {sorted(new)} ≠ blebs notés « ajoute » {sorted(noted_new)}")
        unknown = set(verdicts) - pre_labs - noted_new
        if unknown:
            pb.append(f"R6 : décisions pour des blebs inconnus : {sorted(unknown)}")

    if r2.get("voxels_blebs_initial", "") != counts_str(pre):
        pb.append(f"R7 : voxels_blebs_initial {r2.get('voxels_blebs_initial')!r} ≠ fichier {counts_str(pre)!r}")
    if r2.get("voxels_blebs_corrige", "") != counts_str(res):
        pb.append(f"R7 : voxels_blebs_corrige {r2.get('voxels_blebs_corrige')!r} ≠ fichier {counts_str(res)!r}")
    n_final = len(np.unique(res[res >= BLEB]))
    if r2.get("nb_blebs_final", "") != str(n_final):
        pb.append(f"R7 : nb_blebs_final {r2.get('nb_blebs_final')!r} ≠ {n_final} bleb(s) dans le fichier")
    return pb


def verify(sorties: Path, observateur: str, session: Optional[str] = None, out=print) -> Dict:
    notes = Path(sorties).expanduser() / "notes_observateurs.csv"
    if not notes.exists():
        raise FileNotFoundError(f"introuvable : {notes}")
    with open(notes, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["observateur"] == observateur]
    if not rows:
        raise ValueError(f"aucune réponse pour l'observateur {observateur!r}")
    session = session or sorted({r["session"] for r in rows})[-1]
    rows = [r for r in rows if r["session"] == session]
    cases: Dict[str, Dict[str, Dict]] = {}
    for r in rows:
        cases.setdefault(r["cas_playlist"], {})[r["phase"]] = r
    report = []
    for no, ph in sorted(cases.items(), key=lambda kv: min(int(r["position"]) for r in kv[1].values())):
        r1, r2 = ph.get("comptage"), ph.get("segmentation")
        name = Path((r2 or r1)["segmentation"]).name
        pb = check_case(r1, r2)
        desc = ("0 bleb" if r2 and r2.get("phase2_ignoree") == "oui"
                else f"phase 1 : {r1.get('nb_blebs') if r1 else '?'} ; avis : {(r2 or {}).get('verdict_blebs') or '—'}"
                     f" ; final : {(r2 or {}).get('nb_blebs_final', '?')}")
        report.append({"cas": no, "fichier": name, "resume": desc, "problemes": pb})
        out(f"{'OK      ' if not pb else 'PROBLÈME'} cas {no:>3} {name} — {desc}")
        for p in pb:
            out(f"           {p}")
    n_bad = sum(bool(r["problemes"]) for r in report)
    out(f"\nPassation {observateur} / {session} : {len(report)} cas vérifiés, {len(report) - n_bad} conformes, {n_bad} avec problème.")
    return {"session": session, "report": report, "n_bad": n_bad}


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Vérifie ce qu'une passation a réellement enregistré (lecture seule).")
    ap.add_argument("--sorties", required=True, type=Path, help="dossier des sorties (BLEB_OUTPUT_DIR)")
    ap.add_argument("--observateur", required=True, help="identifiant saisi dans l'application")
    ap.add_argument("--session", default=None, help="session à vérifier (défaut : la dernière de l'observateur)")
    a = ap.parse_args(argv)
    try:
        res = verify(a.sorties, a.observateur, a.session)
    except (FileNotFoundError, ValueError) as e:
        print(f"REFUS : {e}", file=sys.stderr)
        return 2
    return 1 if res["n_bad"] else 0


if __name__ == "__main__":
    sys.exit(main())
