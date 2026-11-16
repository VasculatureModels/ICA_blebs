"""
Tests de l'application app_mpr.py sur des volumes synthétiques : aucun fichier patient requis.

Auteurs : Fakhrielddine Bader, Florent Autrusseau.
Fichier ajouté le 16/11/2026 par Fakhrielddine Bader.

Lancement (dossier du dépôt) :
    python tests/test_app_mpr.py

Vérifie : enregistrement des réponses et colonnes du CSV ; ordre aléatoire des cas (propre à chaque passation,
phase 1 toujours avant phase 2, conservé à la reprise) ; « 0 bleb » : phase 2 ignorée et NIfTI sans bleb
enregistré ; reprise d'une passation interrompue ; refus de reprise si la playlist a changé ; aucune réponse
modifiable après coup ; bouton de démarrage masqué pendant le test.
Imprime RESUME : X OK, Y FAIL ; code de sortie 1 si au moins un échec. Les lignes « missing ScriptRunContext »
affichées par Streamlit pendant les tests sont normales (application lancée sans serveur).
"""

import csv
import os
import sys
import tempfile
import traceback
from pathlib import Path

import nrrd
import numpy as np
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app_mpr.py")
HEADER = {"space": "left-posterior-superior", "space directions": np.eye(3), "space origin": np.zeros(3),
          "kinds": ["domain"] * 3, "encoding": "raw"}


def write_case(folder: Path, name: str, n: int = 24, two_blebs: bool = False, no_bleb: bool = False) -> list[str]:
    """Un cas synthétique : image, segmentation (artère 1, anévrisme 2) et segmentation avec blebs (3, 4).
    Renvoie les deux lignes de playlist du cas."""
    x, y, z = np.mgrid[:n, :n, :n]
    seg = np.zeros((n, n, n), np.uint16)
    seg[(y - n // 2) ** 2 + (z - n // 2) ** 2 <= 4] = 1
    seg[(x - n // 2) ** 2 + (y - n // 2 - 5) ** 2 + (z - n // 2) ** 2 <= 16] = 2
    blebs = seg.copy()
    if not no_bleb:
        blebs[((x - n // 2) ** 2 + (y - n // 2 - 9) ** 2 + (z - n // 2) ** 2 <= 4) & (seg == 2)] = 3
    if two_blebs:
        blebs[((x - n // 2 - 4) ** 2 + (y - n // 2 - 5) ** 2 + (z - n // 2) ** 2 <= 4) & (seg == 2)] = 4
    nrrd.write(str(folder / f"{name}.nrrd"), (100.0 * (seg > 0) + x).astype(np.float32), HEADER)
    nrrd.write(str(folder / f"{name}.seg.nrrd"), seg, HEADER)
    nrrd.write(str(folder / f"{name}_blebs.seg.nrrd"), blebs, HEADER)
    return [f"images/{name}.nrrd ; images/{name}.seg.nrrd", f"images/{name}.nrrd ; images/{name}_blebs.seg.nrrd"]


class Workdir:
    """Dossier temporaire : images/, playlist.txt et sorties de l'application (BLEB_OUTPUT_DIR)."""

    def __init__(self, cases, **kw):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "images").mkdir()
        self.lines = []
        for c in cases:
            self.add(c, **kw)
        self._old = (list(sys.argv), os.environ.get("BLEB_OUTPUT_DIR"))

    def add(self, name, **kw):
        self.lines += write_case(self.root / "images", name, **kw)
        (self.root / "playlist.txt").write_text("\n".join(self.lines) + "\n", encoding="utf-8")

    def remove(self, name):
        self.lines = [ln for ln in self.lines if f"/{name}." not in ln and f"/{name}_blebs." not in ln]
        (self.root / "playlist.txt").write_text("\n".join(self.lines) + "\n", encoding="utf-8")

    def __enter__(self):
        sys.argv = ["app_mpr.py", str(self.root / "playlist.txt")]
        os.environ["BLEB_OUTPUT_DIR"] = str(self.root / "sorties")
        return self

    def __exit__(self, *exc):
        sys.argv = self._old[0]
        if self._old[1] is None:
            os.environ.pop("BLEB_OUTPUT_DIR", None)
        else:
            os.environ["BLEB_OUTPUT_DIR"] = self._old[1]
        self._tmp.cleanup()

    def rows(self):
        with open(self.root / "sorties" / "notes_observateurs.csv", newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))


def new_app(observer="obs"):
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    assert not at.exception, at.exception
    at.sidebar.text_input[0].set_value(observer).run()
    return at


def button(at, text):
    found = [b for b in at.button if text in b.label]
    assert len(found) == 1, f"bouton « {text} » : {[b.label for b in at.button]}"
    return found[0]


def started_app(observer="obs"):
    at = new_app(observer)
    button(at, "Démarrer le test").click().run()
    assert not at.exception, at.exception
    return at


def save(at):
    button(at, "Enregistrer").click().run()
    assert not at.exception, at.exception


def phase(at):
    return at.subheader[0].value


def answer(at, n_blebs):
    """Phase 1 : choisit un nombre de blebs et enregistre."""
    assert "Phase 1/2" in phase(at), phase(at)
    at.radio[0].set_value(n_blebs).run()
    save(at)


def corrected(w):
    import nibabel as nib
    files = sorted((w.root / "sorties" / "resultats").glob("corrections_*/*.nii.gz"))
    return {f.name: np.asarray(nib.load(str(f)).dataobj) for f in files}


def test_full_case_and_csv_columns_unchanged():
    with Workdir(["P1__ICA_1"], two_blebs=True) as w:
        at = started_app()
        assert "Cas 1 / 1" in phase(at) and "Phase 1/2" in phase(at)
        assert button(at, "Enregistrer").disabled                 # pas de réponse : bouton inactif
        answer(at, 2)
        assert "Phase 2/2" in phase(at)
        save(at)                                                  # pré-segmentation validée sans modification
        assert any("Merci" in t.value for t in at.title)
        rows = w.rows()
        assert [r["phase"] for r in rows] == ["comptage", "segmentation"] and rows[0]["nb_blebs"] == "2"
        assert rows[1]["segmentation"].endswith("P1__ICA_1_blebs.seg.nrrd") and rows[1]["irm"].endswith("P1__ICA_1.nrrd")
        assert rows[1]["voxels_blebs_initial"] == rows[1]["voxels_blebs_corrige"] and rows[1]["phase2_ignoree"] == ""
        assert rows[1]["fichier_correction_nifti"] == "" and corrected(w) == {}   # rien de modifié : pas de NIfTI
        assert list(rows[0]) == [
            "horodatage", "observateur", "session", "position", "cas_playlist", "phase", "irm", "segmentation",
            "nb_blebs", "voxels_blebs_initial", "voxels_blebs_corrige", "fichier_correction_nifti", "export_nifti",
            "phase2_ignoree"]                                     # exactement les colonnes de la version d'origine


def test_zero_bleb_skips_phase_2_and_saves_bleb_free_mask():
    with Workdir([]) as w:
        w.add("A__ICA_1", two_blebs=True)                         # pré-segmentation avec 2 blebs
        w.add("B__ICA_1", no_bleb=True)                           # pré-segmentation sans bleb
        at = started_app()
        answer(at, 0)
        answer(at, 0)                                             # phase 2 ignorée : on est passé au cas suivant
        assert any("Merci" in t.value for t in at.title)
        rows = {(Path(r["segmentation"]).name, r["phase"]): r for r in w.rows()}
        assert len(rows) == 4
        for name in ("A__ICA_1", "B__ICA_1"):
            r = rows[(f"{name}_blebs.seg.nrrd", "segmentation")]
            base = nrrd.read(str(w.root / "images" / f"{name}.seg.nrrd"))[0]
            assert r["phase2_ignoree"] == "oui" and r["export_nifti"] == "ok" and r["voxels_blebs_corrige"] == ""
            out = corrected(w)[Path(r["fichier_correction_nifti"]).name]
            assert out.max() == 2                                 # plus aucun bleb
            assert np.array_equal(out, base)                      # = la segmentation d'origine, sans bleb
        assert rows[("A__ICA_1_blebs.seg.nrrd", "segmentation")]["voxels_blebs_initial"].count(":") == 2
        assert rows[("B__ICA_1_blebs.seg.nrrd", "segmentation")]["voxels_blebs_initial"] == ""


def run_all_with_zero(at, n_cases):
    for _ in range(n_cases):
        answer(at, 0)


def test_random_order_per_session_phase_1_first():
    names = [f"N{i}__ICA_1" for i in range(6)]
    with Workdir(names) as w:
        orders = []
        for obs in ("obs_a", "obs_b", "obs_c"):
            at = started_app(obs)
            run_all_with_zero(at, 6)
            rows = [r for r in w.rows() if r["observateur"] == obs]
            assert [int(r["position"]) for r in rows] == list(range(12))              # on avance toujours
            assert [r["phase"] for r in rows] == ["comptage", "segmentation"] * 6    # phase 1 avant phase 2
            seq = [int(r["cas_playlist"]) for r in rows]
            assert seq[0::2] == seq[1::2] and sorted(seq[0::2]) == [1, 2, 3, 4, 5, 6]   # chaque cas une fois
            orders.append(seq[0::2])
        assert any(o != [1, 2, 3, 4, 5, 6] for o in orders), orders   # l'ordre de la playlist n'est pas suivi
        assert len({tuple(o) for o in orders}) > 1, orders             # et il diffère d'une passation à l'autre


def test_resume_keeps_the_same_random_order():
    names = [f"N{i}__ICA_1" for i in range(5)]
    with Workdir(names) as w:
        at = started_app()
        answer(at, 1)
        save(at)                                                  # 1er cas terminé
        answer(at, 2)                                             # 2e cas : phase 1 seulement
        session = w.rows()[0]["session"]
        shown = at.subheader[0].value

        at2 = new_app()                                           # page rechargée / navigateur rouvert
        assert not [b for b in at2.button if "Démarrer" in b.label]
        resume = button(at2, "Reprendre le test")
        assert "3 / 10" in resume.label, resume.label
        resume.click().run()
        assert at2.subheader[0].value == shown                    # même cas, même phase qu'avant l'interruption
        save(at2)
        run_all_with_zero(at2, 3)
        assert any("Merci" in t.value for t in at2.title)
        rows = w.rows()
        assert {r["session"] for r in rows} == {session}          # même passation, pas une nouvelle
        assert [int(r["position"]) for r in rows] == list(range(10))
        cases = [int(r["cas_playlist"]) for r in rows]
        assert cases[0::2] == cases[1::2] and sorted(cases[0::2]) == [1, 2, 3, 4, 5]   # ordre tiré au départ conservé
        assert not [b for b in new_app("autre").button if "Reprendre" in b.label]     # autre observateur : rien à reprendre


def test_new_run_instead_of_resume():
    with Workdir(["A__ICA_1", "B__ICA_1"]) as w:
        at = started_app()
        answer(at, 1)
        at2 = new_app()
        button(at2, "Nouveau test").click().run()
        assert "Cas 1 / 2" in phase(at2) and "Phase 1/2" in phase(at2)
        answer(at2, 1)
        assert len({r["session"] for r in w.rows()}) == 2         # deux passations distinctes, rien d'écrasé


def test_resume_refused_when_playlist_changed():
    with Workdir(["A__ICA_1", "B__ICA_1"]) as w:
        at = started_app()
        answer(at, 1)
        rated = Path(w.rows()[0]["segmentation"]).name.replace(".seg.nrrd", "")
        w.remove(rated)                                           # le cas déjà noté sort de la playlist
        w.add("D__ICA_1")
        at2 = new_app()
        assert not [b for b in at2.button if "Reprendre" in b.label], [b.label for b in at2.button]
        button(at2, "Démarrer le test").click().run()
        assert "Cas 1 / 2" in phase(at2) and "Phase 1/2" in phase(at2)


def test_no_way_back_and_no_start_button_during_test():
    with Workdir(["A__ICA_1", "B__ICA_1"]) as w:
        at = started_app()
        labels = lambda a: [b.label for b in a.button]
        assert not any("Démarrer" in x or "Reprendre" in x or "Nouveau test" in x for x in labels(at))   # test en cours
        assert labels(at) == ["💾 Enregistrer"] and not at.sidebar.button      # aucun bouton de navigation
        answer(at, 1)
        assert labels(at) == ["💾 Enregistrer"] and "Phase 2/2" in phase(at)   # impossible de revenir à la phase 1
        save(at)
        assert "Cas 2 / 2" in phase(at) and labels(at) == ["💾 Enregistrer"]   # impossible de revenir au cas 1
        assert len(w.rows()) == 2


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    ok = fail = 0
    for t in tests:
        try:
            t()
            ok += 1
            print(f"OK    {t.__name__}")
        except Exception:
            fail += 1
            print(f"FAIL  {t.__name__}")
            traceback.print_exc()
    print(f"RESUME : {ok} OK, {fail} FAIL")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
