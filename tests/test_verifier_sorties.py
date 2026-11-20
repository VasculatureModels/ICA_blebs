"""Recette de bout en bout : l'application enregistre-t-elle exactement ce que fait l'observateur ?

Auteurs : Fakhrielddine Bader, Florent Autrusseau.

Une passation complète est jouée sur 5 cas synthétiques, avec tous les gestes possibles :
« 0 bleb », blebs gardés sans choix, « Supprimer », « Retoucher » avec pinceau et gomme, et un bleb ajouté.
Puis outils/verifier_sorties.py relit les fichiers et doit tout trouver conforme. On altère ensuite un
fichier résultat et une ligne du CSV : le vérificateur doit le signaler.

Lancement : uv run python tests/test_verifier_sorties.py
"""
import csv
import sys
import traceback
from pathlib import Path

import nibabel as nib
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent), str(HERE.parent / "outils")]

import test_app_mpr as T                     # noqa: E402  (fixtures de l'application)
import verifier_sorties as V                 # noqa: E402
from mpr_utils import load_case, pack        # noqa: E402


def displayed(at, w):
    """Nom du cas affiché. Le nom du patient n'est plus à l'écran depuis le 19/11/2026 : il est retrouvé à partir
    de la session (T.current_case)."""
    return T.current_case(at, w, "recette")


def viewer_case(w, name):
    root = w.root / "images"
    return load_case(str(root / f"{name}__ICA_1.nrrd"), str(root / f"{name}__ICA_1_blebs.seg.nrrd"),
                     margin=12, max_voxels=80_000_000)


def play_session(w):
    """Joue une passation complète ; chaque cas reçoit son scénario, quel que soit l'ordre aléatoire."""
    at = T.started_app("recette")
    done = set()
    for _ in range(20):                                             # garde-fou : jamais de boucle sans fin
        if len(done) == 5:
            break
        name = displayed(at, w)
        if name == "C":                                                   # « 0 bleb »
            T.answer(at, 0)
        elif name == "A":                                                 # aucun choix : blebs gardés
            T.answer(at, 2); T.save(at)
        elif name == "B":                                                 # bleb 2 : « Supprimer »
            T.answer(at, 1)
            lab = viewer_case(w, "B")["labels"].copy()
            old = np.argwhere(lab == 4)
            lab[lab == 4] = 2                                             # le viewer l'a déjà rendu à l'anévrisme
            lab[tuple(old[: len(old) // 2].T)] = 5                        # puis un bleb redessiné sur une partie de sa place
            T.viewer_sends(at, verdicts={"4": "supprime"}, edited=True, labels_gz=pack(lab), save=True)
        elif name == "D":                                                 # bleb 1 : pinceau puis gomme
            T.answer(at, 2)
            case = viewer_case(w, "D")
            lab = case["labels"].copy()
            grow = (lab == 2) & (np.roll(lab == 3, 1, axis=0) | np.roll(lab == 3, -1, axis=0))
            lab[grow] = 3                                                 # pinceau : le bleb 1 s'étend sur l'anévrisme
            first = np.argwhere(case["labels"] == 3)[0]
            lab[tuple(first)] = 2                                         # gomme : un voxel du bleb rendu à l'anévrisme
            T.viewer_sends(at, verdicts={"3": "retouche"}, edited=True,
                           labels_gz=pack(lab), save=True)
        elif name == "E":                                                 # pas de bleb pré-segmenté : on en ajoute un
            T.answer(at, 1)
            case = viewer_case(w, "E")
            lab = case["labels"].copy()
            idx = np.argwhere(lab == 2)[:6]
            lab[tuple(idx.T)] = 3
            T.viewer_sends(at, verdicts={}, edited=True, labels_gz=pack(lab), save=True)
        done.add(name)
    assert any("Merci" in t.value for t in at.title)


def setup(w):
    w.add("A__ICA_1", two_blebs=True); w.add("B__ICA_1", two_blebs=True); w.add("C__ICA_1", two_blebs=True)
    w.add("D__ICA_1", two_blebs=True); w.add("E__ICA_1", no_bleb=True)


def test_full_session_is_saved_exactly():
    with T.Workdir([]) as w:
        setup(w)
        play_session(w)
        res = V.verify(w.root / "sorties", "recette", out=lambda *a: None)
        assert res["n_bad"] == 0, [r for r in res["report"] if r["problemes"]]
        assert len(res["report"]) == 5
        rows = {Path(r["segmentation"]).name.split("__")[0]: r for r in w.rows() if r["phase"] == "segmentation"}
        assert rows["A"]["nb_blebs_final"] == "2" and rows["B"]["nb_blebs_final"] == "2"
        assert rows["C"]["nb_blebs_final"] == "0" and rows["E"]["nb_blebs_final"] == "1"
        assert rows["D"]["verdict_blebs"] == "3:retouche; 4:garde"
        assert rows["A"]["verdict_blebs"] == "3:garde; 4:garde" and rows["B"]["verdict_blebs"] == "3:garde; 4:supprime; 5:ajoute"
        assert rows["E"]["verdict_blebs"] == "3:ajoute"


def test_tampered_outputs_are_detected():
    with T.Workdir([]) as w:
        setup(w)
        play_session(w)
        rows = [r for r in w.rows()]
        seg = {Path(r["segmentation"]).name.split("__")[0]: r for r in rows if r["phase"] == "segmentation"}
        # 1) une artère effacée dans le fichier résultat de A
        f = seg["A"]["fichier_correction_nifti"]
        img = nib.load(f); arr = np.asarray(img.dataobj).copy()
        arr[tuple(np.argwhere(arr == 1)[0])] = 0
        nib.save(nib.Nifti1Image(arr, img.affine, img.header), f)
        # 2) un nombre final faux dans le CSV pour B
        path = w.root / "sorties" / "notes_observateurs.csv"
        for r in rows:
            if r is seg["B"]:
                r["nb_blebs_final"] = "3"
        with open(path, "w", newline="", encoding="utf-8") as fh:
            wr = csv.DictWriter(fh, fieldnames=list(rows[0])); wr.writeheader(); wr.writerows(rows)
        res = V.verify(w.root / "sorties", "recette", out=lambda *a: None)
        bad = {r["fichier"].split("__")[0]: r["problemes"] for r in res["report"] if r["problemes"]}
        assert set(bad) == {"A", "B"}, bad
        assert any(p.startswith("R3") for p in bad["A"]) and any(p.startswith("R7") for p in bad["B"])
        assert V.main(["--sorties", str(w.root / "sorties"), "--observateur", "recette"]) == 1


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    ok = fail = 0
    for t in tests:
        try:
            t(); ok += 1; print(f"OK    {t.__name__}")
        except Exception:
            fail += 1; print(f"FAIL  {t.__name__}"); traceback.print_exc()
    print(f"RESUME : {ok} OK, {fail} FAIL")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
