"""Tests de outils/tirer_jeux.py. Auteurs : Fakhrielddine Bader, Florent Autrusseau.
Lancement (dossier du dépôt) : python tests/test_tirer_jeux.py"""
import csv
import json
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "outils"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tirer_jeux as T   # noqa: E402


def read_playlist(path):
    """Mêmes règles que read_playlist de app_mpr.py : lignes non vides hors « # », « image ; segmentation »."""
    out = []
    for ln in Path(path).read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        parts = [x.strip() for x in ln.split(";")]
        assert len(parts) == 2 and all(parts), ln
        out.append(ln)
    return out


def fake(root: Path, n=146):
    ids = [f"RCAN_01_{i:03d}_S_0.4" for i in range(1, n + 1)]
    with open(root / "crops_manifest.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["analysis_id", "file_blebs"]); w.writeheader()
        for a in ids:
            w.writerow({"analysis_id": a, "file_blebs": f"{a}__ICA_1_blebs.seg.nii.gz"})
    lines = ["# playlist de l'étude"]
    for a in reversed(ids):                                  # ordre quelconque dans la playlist d'origine
        lines += [f"images/{a}__ICA_1.nii.gz ; images/{a}__ICA_1.seg.nii.gz",
                  f"images/{a}__ICA_1.nii.gz ; images/{a}__ICA_1_blebs.seg.nii.gz"]
    (root / "playlist_etude.txt").write_text("\n".join(lines) + "\n")
    (root / "calib.txt").write_text("\n".join(ids[:65]) + "\n")
    return ids


def run(root, out="out", **kw):
    return T.tirer(root / "playlist_etude.txt", root / "crops_manifest.csv", root / out, root / "calib.txt",
                   out=lambda *a: None, **kw)


def test_jeux_50_cas_20_communs_disjoints():
    with tempfile.TemporaryDirectory() as t:
        t = Path(t); ids = fake(t)
        info = run(t)
        com = set(info["communs"]); jeux = {k: set(v) for k, v in info["propres"].items()}
        assert len(com) == 20 and all(len(v) == 30 for v in jeux.values())
        assert not (jeux["JB"] & jeux["GG"]) and not (jeux["JB"] & jeux["VL"]) and not (jeux["GG"] & jeux["VL"])
        assert not any(com & v for v in jeux.values())
        assert len(info["non_tires"]) == 36 and set(info["non_tires"]) | com | set().union(*jeux.values()) == set(ids)
        for code in ("JB", "GG", "VL"):
            entries = read_playlist(t / "out" / f"playlist_{code}.txt")   # format de l'application
            assert len(entries) == 100
            got = {Path(e.split(";")[1].strip()).name.split("__")[0] for e in entries[1::2]}
            assert got == com | jeux[code]
            assert all("_blebs" not in e.split(";")[1] for e in entries[0::2])
            assert all("_blebs" in e.split(";")[1] for e in entries[1::2])
        rows = list(csv.DictReader(open(t / "out" / "tirage_jeux.csv")))
        assert len(rows) == 146 and sum(r["groupe"] == "commun" for r in rows) == 20
        assert sum(r["calibration"] == "oui" for r in rows) == 65
        js = json.loads((t / "out" / "tirage_jeux.json").read_text())
        assert js["graine"] == T.GRAINE and set(js["playlists_sha256"]) == {"playlist_JB.txt", "playlist_GG.txt",
                                                                            "playlist_VL.txt"}


def test_30_propres_meme_procedure_que_40():
    """v1.1.0 : même graine, mêmes communs ; avec n_propres=40, exactement le tirage v1.0.0."""
    with tempfile.TemporaryDirectory() as t:
        t = Path(t); fake(t)
        a30, a40 = run(t, "a30"), run(t, "a40", n_propres=40)
        assert a30["communs"] == a40["communs"]
        assert set(a30["propres"]["JB"]) <= set(a40["propres"]["JB"])     # le 1er jeu propre est un sous-ensemble
        cas = sorted(fake(t))
        import random
        tires = random.Random(T.GRAINE).sample(cas, 140)              # procédure v1.0.0, écrite à la main
        assert a40["communs"] == sorted(tires[:20]) and a40["propres"]["VL"] == sorted(tires[100:140])


def test_meme_graine_meme_tirage_autre_graine_autre():
    with tempfile.TemporaryDirectory() as t:
        t = Path(t); fake(t)
        a, b, c = run(t, "a"), run(t, "b"), run(t, "c", graine=1)
        assert a["communs"] == b["communs"] and a["propres"] == b["propres"]
        assert a["communs"] != c["communs"]
        assert (t / "a" / "playlist_JB.txt").read_text().splitlines()[3:] == \
               (t / "b" / "playlist_JB.txt").read_text().splitlines()[3:]


def test_refus():
    with tempfile.TemporaryDirectory() as t:
        t = Path(t); fake(t, n=100)
        for kw, frag in (({}, "110 nécessaires"), ({"n_propres": 40}, "140 nécessaires")):
            try:
                run(t, **kw); raise AssertionError("refus attendu")
            except T.TirageError as e:
                assert frag in str(e), e
        fake(t)
        (t / "out").mkdir()
        try:
            run(t); raise AssertionError("refus attendu")
        except T.TirageError as e:
            assert "existe déjà" in str(e)
        lines = (t / "playlist_etude.txt").read_text().splitlines()
        lines[1], lines[2] = lines[2], lines[1]                  # paire inversée : phase 2 avant phase 1
        (t / "playlist_etude.txt").write_text("\n".join(lines) + "\n")
        try:
            run(t, "o2"); raise AssertionError("refus attendu")
        except T.TirageError as e:
            assert "paire attendue" in str(e)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    ok = fail = 0
    for tst in tests:
        try:
            tst(); ok += 1; print(f"OK    {tst.__name__}")
        except Exception:
            fail += 1; print(f"FAIL  {tst.__name__}"); traceback.print_exc()
    print(f"RESUME : {ok} OK, {fail} FAIL")
    sys.exit(1 if fail else 0)
