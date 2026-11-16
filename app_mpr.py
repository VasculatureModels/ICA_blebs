"""
Évaluation de segmentations d'anévrismes cérébraux avec un viewer de type PACS :
coupes axiale / coronale / sagittale (défilement, zoom, fenêtrage), vue 3D, et pinceau / gomme sur les voxels
dans les trois plans pour corriger la segmentation des blebs.

Fichiers (dans le même dossier) :
    app_mpr.py   mpr_utils.py   mpr_viewer/index.html   mpr_viewer/mpr_core.js   playlist.txt

Installation :  pip install streamlit numpy nibabel pynrrd      (pynrrd : seulement pour les .nrrd)
Lancement    :  streamlit run app_mpr.py            (ou :  streamlit run app_mpr.py -- ma_playlist.txt)

Playlist (.txt) : une entrée par ligne, au format « image ; segmentation » (la segmentation seule est acceptée).
Les entrées vont PAR PAIRES consécutives pour un même cas :
    1re entrée (phase 1) : segmentation artères (1) + anévrismes (2)            -> comptage des blebs
    2e  entrée (phase 2) : segmentation artères (1) + anévrismes (2) + blebs (3, 4, 5...) -> correction possible
Exemple :
    data/p01_mra.nii.gz ; data/p01_sans_blebs.seg.nrrd
    data/p01_mra.nii.gz ; data/p01_avec_blebs.seg.nrrd
    data/p02_mra.nii.gz ; data/p02_sans_blebs.seg.nrrd
    data/p02_mra.nii.gz ; data/p02_avec_blebs.seg.nrrd

Image et segmentation doivent avoir la même grille (mêmes dimensions et même géométrie). Formats : .nii, .nii.gz, .nrrd.
Chaque bleb a son propre label (3, 4, 5...) et sa couleur ; le pinceau peint avec le bleb choisi.
Ordre : les cas (paires) sont mélangés pour chaque passation (SHUFFLE_CASES), phase 1 toujours avant phase 2.
Si la phase 1 répond « 0 bleb », la phase 2 du cas est ignorée (SKIP_PHASE2_IF_ZERO_BLEBS) et notée comme telle dans le CSV.
Sortie : un NIfTI (labels, orientation et espace du fichier d'origine) par segmentation corrigée.

Reprise : une passation interrompue (page rechargée, navigateur fermé) est reprise là où elle s'était arrêtée, avec le
même identifiant d'observateur (« Reprendre le test »). L'ordre aléatoire des cas est celui tiré au début de la
passation. Une réponse enregistrée n'est plus modifiable : on avance toujours, sans retour en arrière.

« 0 bleb » en phase 1 : la phase 2 est ignorée, et un NIfTI sans aucun bleb (la pré-segmentation dont les blebs
sont rendus à l'anévrisme) est enregistré comme résultat du cas.

Auteurs : Fakhrielddine Bader, Florent Autrusseau.
Historique :
    Version d'origine (viewer MPR, pinceau / gomme sur les voxels, export NIfTI, ordre aléatoire) : Florent Autrusseau.
    Modifications du 16/11/2026, Fakhrielddine Bader : reprise d'une passation interrompue, identifiant de
    passation unique, bouton de démarrage masqué pendant le test, NIfTI sans bleb enregistré après « 0 bleb ».
    Les colonnes du CSV et les noms des fichiers de sortie sont inchangés.
"""

import csv
import hashlib
import os
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import streamlit as st
import streamlit.components.v1 as components

from mpr_utils import (
    counts_to_str,
    label_counts,
    load_case,
    restore_native,
    save_labels_nifti,
    unpack,
)

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
# Dossier de sortie : à côté du script (et NON relatif au dossier courant, qui peut changer ou disparaître).
# Peut être changé avec la variable d'environnement BLEB_OUTPUT_DIR.
BASE_DIR = Path(os.path.abspath(__file__)).parent
OUTPUT_DIR = Path(os.path.abspath(os.path.expanduser(os.environ.get("BLEB_OUTPUT_DIR", str(BASE_DIR)))))
RATINGS_FILE = OUTPUT_DIR / "notes_observateurs.csv"  # journal commun, mis à jour à chaque note
RESULTS_DIR = OUTPUT_DIR / "resultats"  # récapitulatifs CSV par passation + segmentations corrigées

PLAYLIST_PATH = str(Path(sys.argv[1]).resolve()) if len(sys.argv) > 1 else str(BASE_DIR / "playlist.txt")

SHUFFLE_CASES = True  # ordre des cas aléatoire pour chaque passation (False : ordre de la playlist)
# « 0 bleb » en phase 1 : la phase 2 du cas est ignorée (rien à corriger) et notée comme telle dans le CSV
SKIP_PHASE2_IF_ZERO_BLEBS = True
EXPORT_NIFTI = True  # écrire le masque corrigé en NIfTI
CROP_MARGIN_VOX = 12  # marge (voxels) autour de la segmentation : seule cette région est envoyée au navigateur
MAX_VOXELS = 80_000_000  # au-delà (après recadrage), le cas est refusé

CSV_FIELDS = [
    "horodatage", "observateur", "session", "position", "cas_playlist", "phase", "irm", "segmentation",
    "nb_blebs", "voxels_blebs_initial", "voxels_blebs_corrige", "fichier_correction_nifti", "export_nifti",
    "phase2_ignoree",
]

# label -> (nom affiché, couleur par défaut)
LABELS = {
    1: ("Artères", "#d62728"),
    2: ("Anévrismes", "#1f77b4"),
}
# Chaque bleb a son propre label (3, 4, 5...), son nom (« Bleb 1 », « Bleb 2 »...) et sa couleur.
BLEB_COLORS = ["#ffd700", "#00e5ff", "#ff4dd2", "#7cfc00", "#ff8c00", "#b388ff", "#ff5252", "#40e0b0"]
MIN_BLEB_CHOICES = 2  # nombre minimal de couleurs de pinceau proposées en phase 2
MAX_BLEB_LABELS = 8  # nombre maximal de blebs distincts (bouton « + Nouveau bleb »)
PARENT_LABEL = 2  # classe que retrouve un voxel quand on gomme un bleb
BLEB_LABEL = 3  # premier label de bleb : tout label >= 3 est un bleb, et chaque bleb garde son label
FALLBACK_COLOR = "#999999"
VIEWER_HEIGHT = 820

BLEB_OPTIONS = {0: "0 bleb", 1: "1 bleb", 2: "2 blebs", 3: "3 blebs", 4: "> 3 blebs"}
PHASE_COUNT = "comptage"  # entrées 0, 2, 4... de la playlist
PHASE_SEG = "segmentation"  # entrées 1, 3, 5...


def phase_of(idx: int) -> str:
    return PHASE_COUNT if idx % 2 == 0 else PHASE_SEG


st.set_page_config(page_title="Évaluation de segmentations artérielles", layout="wide")

# Le nom du composant dépend du contenu des fichiers du viewer : le navigateur recharge donc le viewer dès
# qu'il change, au lieu de garder une ancienne version en cache.
_VIEWER_DIR = BASE_DIR / "mpr_viewer"
_VIEWER_VERSION = hashlib.md5(
    (_VIEWER_DIR / "index.html").read_bytes() + (_VIEWER_DIR / "mpr_core.js").read_bytes()
).hexdigest()[:8]
_viewer = components.declare_component(f"mpr_viewer_{_VIEWER_VERSION}", path=str(_VIEWER_DIR))


def label_info(lab: int) -> tuple[str, str]:
    if lab >= BLEB_LABEL:
        k = lab - BLEB_LABEL
        return f"Bleb {k + 1}", BLEB_COLORS[k % len(BLEB_COLORS)]
    return LABELS.get(lab, (f"Label {lab}", FALLBACK_COLOR))


# --------------------------------------------------------------------------- #
# Playlist
# --------------------------------------------------------------------------- #
SEP = " ; "


def read_playlist(path: str) -> list[str]:
    """Une entrée par ligne : « image ; segmentation » ou « segmentation ». Chemins relatifs : dossier de la playlist."""
    base = Path(path).parent
    entries = []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(";")]
        if len(parts) > 2 or not all(parts):
            raise ValueError(f"playlist, ligne {n} : attendu « image ; segmentation » (ou « segmentation »), reçu : {line!r}")
        resolved = [str(Path(p) if Path(p).is_absolute() else (base / p).resolve()) for p in parts]
        entries.append(SEP.join(resolved))
    return entries


def split_entry(entry: str) -> tuple[str | None, str]:
    parts = [p.strip() for p in entry.split(";")]
    return (parts[0], parts[1]) if len(parts) == 2 else (None, parts[0])


def display_name(entry: str) -> str:
    return Path(split_entry(entry)[1]).name


def clean_stem(path: str) -> str:
    """Nom de fichier sans extension(s) : « x.seg.nrrd » -> « x », « x.nii.gz » -> « x »."""
    return re.sub(r"(\.seg)?\.(nii(\.gz)?|nrrd)$", "", Path(path).name, flags=re.IGNORECASE)


def ordered_cases(playlist: list[str], observer: str, run_id: str) -> tuple[list[str], list[int]]:
    """Réordonne les CAS (paires phase 1 / phase 2) de façon aléatoire pour chaque passation.

    La phase 1 reste toujours juste avant la phase 2 du même cas. L'ordre est reproductible à partir
    de (observateur, session), qui figurent dans le CSV. Renvoie la playlist réordonnée et, pour
    chaque position, le numéro du cas d'origine (0, 1, 2... dans la playlist non mélangée)."""
    order = list(range(len(playlist) // 2))
    if SHUFFLE_CASES:
        random.Random(f"{observer}|{run_id}").shuffle(order)
    shuffled = [playlist[2 * c + k] for c in order for k in (0, 1)]
    case_ids = [c for c in order for _ in (0, 1)]
    return shuffled, case_ids


@st.cache_resource(show_spinner="Chargement et préparation des volumes…", max_entries=3)
def build_case(entry: str) -> dict:
    image, seg = split_entry(entry)
    return load_case(image, seg, margin=CROP_MARGIN_VOX, max_voxels=MAX_VOXELS)


def export_edited(observer: str, run_id: str, case_no: int, entry: str, labels_gz, case: dict) -> dict:
    """Écrit la segmentation corrigée en NIfTI (orientation et espace du fichier d'origine).

    Ne lève jamais d'exception : renvoie {"statut", "fichier", "counts"} pour que l'échec de l'export
    n'empêche pas d'enregistrer la note."""
    if not EXPORT_NIFTI:
        return {"statut": "désactivé (EXPORT_NIFTI = False)"}
    try:
        # labels_gz : volume compressé renvoyé par le viewer, ou directement un tableau de labels (recadré, RAS+)
        edited = unpack(labels_gz, case["dims"]) if isinstance(labels_gz, str) else np.asarray(labels_gz, dtype=np.uint8)
        native = restore_native(edited, case)
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in observer)
        out = RESULTS_DIR / f"corrections_{safe}_{run_id}" / f"cas{case_no:03d}_{clean_stem(split_entry(entry)[1])}_corrige.nii.gz"
        save_labels_nifti(native, case, out)
        return {"statut": "ok", "fichier": str(out), "counts": label_counts(edited)}
    except ImportError as e:
        pkg = {"nrrd": "pynrrd"}.get(e.name, e.name or "module requis")
        return {"statut": f"erreur : {pkg} non installé (pip install {pkg})"}
    except Exception as e:
        return {"statut": f"erreur : {e}"}


# --------------------------------------------------------------------------- #
# Enregistrement des notes
# --------------------------------------------------------------------------- #
def new_run(observer: str):
    """Démarre une nouvelle passation, avec un identifiant horodaté jamais utilisé par cet observateur."""
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    while load_ratings(observer, run_id):  # deux passations dans la même seconde : on attend la suivante
        time.sleep(1.0)
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    st.session_state["started_by"] = observer
    st.session_state["run_id"] = run_id


def archive_if_outdated():
    """Archive un journal dont l'en-tête ne correspond plus au format actuel."""
    p = Path(RATINGS_FILE)
    if not p.exists():
        return
    with open(p, newline="", encoding="utf-8") as f:
        header = next(csv.reader(f), [])
    if header != CSV_FIELDS:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        p.rename(p.with_name(f"{p.stem}_ancien_{stamp}{p.suffix}"))


def load_ratings(observer: str, run_id: str) -> dict:
    archive_if_outdated()
    ratings = {}
    if Path(RATINGS_FILE).exists():
        with open(RATINGS_FILE, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row["observateur"] == observer and row["session"] == run_id:
                    ratings[int(row["position"])] = row
    return ratings


def resumable_run(observer: str, playlist: list[str]) -> tuple[str, int] | None:
    """Dernière passation inachevée de l'observateur sur ces mêmes cas : (session, nb d'images notées).

    L'ordre aléatoire d'une passation est recalculé à partir de (observateur, session) : il est donc le même à la
    reprise. La reprise n'est proposée que si chaque réponse déjà enregistrée correspond à la segmentation attendue
    à sa position (même playlist, donc même ordre) ; sinon une nouvelle passation démarre."""
    archive_if_outdated()
    if not Path(RATINGS_FILE).exists():
        return None
    with open(RATINGS_FILE, newline="", encoding="utf-8") as f:
        sessions = sorted({r["session"] for r in csv.DictReader(f) if r["observateur"] == observer})
    if not sessions:
        return None
    run_id = sessions[-1]  # identifiants horodatés : le dernier est le plus récent
    ratings = load_ratings(observer, run_id)
    expected, _ = ordered_cases(playlist, observer, run_id)
    same_cases = all(
        pos < len(expected) and Path(row["segmentation"]).name == Path(split_entry(expected[pos])[1]).name
        for pos, row in ratings.items()
    )
    return (run_id, len(ratings)) if same_cases and 0 < len(ratings) < len(expected) else None


def bleb_free_result(observer: str, run_id: str, case_no: int, entry: str) -> dict:
    """Résultat d'un cas déclaré « 0 bleb » en phase 1 : un NIfTI sans aucun bleb.

    La pré-segmentation de la phase 2 est chargée, tous ses blebs (labels >= BLEB_LABEL) redeviennent
    « anévrisme », et le masque est écrit comme une correction ordinaire. Renvoie les champs du CSV."""
    fields = {"phase2_ignoree": "oui"}
    try:
        case = build_case(entry)
    except Exception as e:
        return {**fields, "export_nifti": f"erreur : {e}"}
    initial = {k: v for k, v in label_counts(case["labels"]).items() if k >= BLEB_LABEL}
    cleaned = np.array(case["labels"], dtype=np.uint8, copy=True)
    cleaned[cleaned >= BLEB_LABEL] = PARENT_LABEL
    res = export_edited(observer, run_id, case_no, entry, cleaned, case)
    remaining = {k: v for k, v in res.get("counts", {}).items() if k >= BLEB_LABEL}
    return {**fields, "voxels_blebs_initial": counts_to_str(initial), "voxels_blebs_corrige": counts_to_str(remaining),
            "fichier_correction_nifti": res.get("fichier", ""), "export_nifti": res["statut"]}


def save_rating(
    observer: str, run_id: str, position: int, case_no: int, phase: str, entry: str,
    n_blebs: int | None, extra: dict | None = None,
):
    archive_if_outdated()
    image, seg = split_entry(entry)
    new_file = not Path(RATINGS_FILE).exists()
    row = {
        "horodatage": datetime.now().isoformat(timespec="seconds"),
        "observateur": observer,
        "session": run_id,
        "position": position,
        "cas_playlist": case_no,
        "phase": phase,
        "irm": image or "",
        "segmentation": seg,
        "nb_blebs": "" if n_blebs is None else n_blebs,
    }
    row.update(extra or {})
    Path(RATINGS_FILE).parent.mkdir(parents=True, exist_ok=True)
    with open(RATINGS_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, restval="")
        if new_file:
            w.writeheader()
        w.writerow(row)


def save_final_csv(observer: str, run_id: str, playlist: list[str], ratings: dict) -> Path:
    Path(RESULTS_DIR).mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in observer)
    out = Path(RESULTS_DIR) / f"resultats_{safe}_{run_id}.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, restval="")
        w.writeheader()
        for pos in range(len(playlist)):
            if pos in ratings:
                w.writerow({k: ratings[pos].get(k, "") for k in CSV_FIELDS})
    return out


# --------------------------------------------------------------------------- #
# Barre latérale
# --------------------------------------------------------------------------- #
playlist_path = PLAYLIST_PATH
playlist, playlist_error = [], None
if Path(playlist_path).exists():
    try:
        playlist = read_playlist(playlist_path)
    except ValueError as e:
        playlist_error = str(e)
playlist_ok = bool(playlist) and len(playlist) % 2 == 0

with st.sidebar:
    st.header("Session")
    observer = st.text_input("Nom / identifiant de l'observateur").strip()
    blind = st.checkbox("Masquer les noms de fichiers (évaluation en aveugle)", True)
    started = bool(observer) and st.session_state.get("started_by") == observer
    if started:  # pas de bouton de démarrage pendant le test : un clic accidentel ferait repartir de zéro
        st.caption("Test en cours : vos réponses sont enregistrées à chaque « Enregistrer ».")
    else:
        resume = resumable_run(observer, playlist) if observer and playlist_ok else None
        if resume:
            if st.button(f"▶ Reprendre le test ({resume[1]} / {len(playlist)} images notées)", type="primary",
                         use_container_width=True):
                st.session_state["started_by"], st.session_state["run_id"] = observer, resume[0]
                st.rerun()
            if st.button("Nouveau test (repartir de zéro)", use_container_width=True):
                new_run(observer)
                st.rerun()
        elif st.button("▶ Démarrer le test", type="primary", disabled=not observer, use_container_width=True):
            new_run(observer)
            st.rerun()
    _real_out = Path(os.path.realpath(OUTPUT_DIR))
    if "trash" in f"{OUTPUT_DIR} {_real_out}".lower():
        st.error("Le dossier de sortie est dans la corbeille !")
        with st.expander("Détails"):
            st.markdown(
                f"- Script : `{os.path.abspath(__file__)}`\n"
                f"- Script (chemin réel) : `{os.path.realpath(__file__)}`\n"
                f"- Dossier de sortie : `{OUTPUT_DIR}`\n"
                f"- Dossier de sortie (chemin réel) : `{_real_out}`\n"
                f"- Dossier courant : `{os.getcwd()}`\n"
                f"- BLEB_OUTPUT_DIR : `{os.environ.get('BLEB_OUTPUT_DIR', '(non défini)')}`"
            )
    try:
        import nibabel  # noqa: F401
    except ImportError:
        st.warning("nibabel n'est pas installé : lecture des NIfTI et export impossibles (`pip install nibabel`).")

if not observer:
    st.info("Saisissez votre identifiant dans la barre latérale pour commencer.")
    st.stop()
if not started:
    st.info("Cliquez sur « Démarrer le test » (ou « Reprendre le test ») dans la barre latérale.")
    st.stop()
if not Path(playlist_path).exists():
    st.error(f"Playlist introuvable : {playlist_path}")
    st.stop()
if playlist_error:
    st.error(playlist_error)
    st.stop()
if not playlist:
    st.warning("La playlist est vide.")
    st.stop()
if len(playlist) % 2 != 0:
    st.error(
        "La playlist doit contenir un nombre PAIR d'entrées (deux par cas : "
        "sans blebs puis avec blebs segmentés)."
    )
    st.stop()

if any(split_entry(p)[1].lower().endswith(".nrrd") or (split_entry(p)[0] or "").lower().endswith(".nrrd") for p in playlist):
    try:
        import nrrd  # noqa: F401
    except ImportError:
        st.sidebar.warning("pynrrd n'est pas installé : lecture des .nrrd impossible (`pip install pynrrd`).")

run_id = st.session_state["run_id"]
playlist, case_ids = ordered_cases(playlist, observer, run_id)
ratings = load_ratings(observer, run_id)

# --------------------------------------------------------------------------- #
# Navigation
# --------------------------------------------------------------------------- #
state_key = f"idx_{observer}_{run_id}_{playlist_path}"
if state_key not in st.session_state:
    todo = [i for i in range(len(playlist)) if i not in ratings]
    st.session_state[state_key] = todo[0] if todo else 0
idx = st.session_state[state_key]

n_done = sum(i in ratings for i in range(len(playlist)))

# Messages laissés par l'enregistrement précédent (la page est relancée juste après)
for kind, msg in st.session_state.pop("flash", []):
    getattr(st, kind)(msg)

# --- Fin du test : page de remerciements + sauvegarde automatique du CSV ---
if n_done == len(playlist):
    final_key = f"final_saved_{observer}_{run_id}_{playlist_path}"
    try:
        out = save_final_csv(observer, run_id, playlist, ratings)
        first_time = not st.session_state.get(final_key)
        st.session_state[final_key] = True
        saved_ok = True
    except OSError as e:
        saved_ok, first_time = False, False
        st.error(f"Impossible d'écrire le fichier de résultats : {e}")

    if first_time:
        st.balloons()
    st.title("🎉 Merci pour votre participation !")
    st.markdown(
        f"Vous avez évalué les **{len(playlist) // 2} cas** ({len(playlist)} images) de la playlist. "
        "Vos réponses ont bien été enregistrées."
    )
    if saved_ok:
        st.caption(f"Résultats sauvegardés automatiquement : `{out}`")
    st.markdown("Vous pouvez maintenant fermer cette page.")
    if st.button("↻ Recommencer un nouveau test"):
        new_run(observer)
        st.rerun()
    st.stop()

st.progress(n_done / len(playlist), text=f"{n_done} / {len(playlist)} images notées")

current = playlist[idx]
phase = phase_of(idx)
editable = phase == PHASE_SEG
phase_txt = (
    "Phase 1/2 : comptage des blebs"
    if phase == PHASE_COUNT
    else "Phase 2/2 : qualité de la segmentation des blebs (correction possible)"
)
st.subheader(
    f"Cas {idx // 2 + 1} / {len(playlist) // 2} — {phase_txt}"
    + ("" if blind else f" — {display_name(current)}")
)

# --------------------------------------------------------------------------- #
# Viewer (3 coupes + 3D)
# --------------------------------------------------------------------------- #
case = None
viewer_value = None
try:
    case = build_case(current)
except ImportError as e:
    pkg = {"nrrd": "pynrrd"}.get(e.name, e.name or "module requis")
    st.error(f"Module manquant : `pip install {pkg}`")
except Exception as e:
    st.error(f"Impossible de charger {display_name(current)} : {e}")

if case is not None:
    class_ids = set(case["present"])
    if editable:
        # au moins MIN_BLEB_CHOICES couleurs de pinceau, et toutes celles des blebs déjà présents
        n_shown = max([lab - BLEB_LABEL + 1 for lab in class_ids if lab >= BLEB_LABEL] + [MIN_BLEB_CHOICES])
        class_ids |= {PARENT_LABEL} | set(range(BLEB_LABEL, BLEB_LABEL + min(n_shown, MAX_BLEB_LABELS)))
    classes = [
        {"id": lab, "name": label_info(lab)[0], "color": label_info(lab)[1]} for lab in sorted(class_ids)
    ]
    # Les arguments restent identiques d'une relance à l'autre pour une même image : le viewer n'est pas
    # rechargé, la position, le zoom et les corrections sont conservés.
    viewer_value = _viewer(
        scene_id=f"{current}|{int(editable)}",
        dims=case["dims"],
        spacing=case["spacing"],
        center=case["center"],
        classes=classes,
        editable=editable,
        bleb_label=BLEB_LABEL,
        parent_label=PARENT_LABEL,
        bleb_palette=BLEB_COLORS,
        max_bleb_labels=MAX_BLEB_LABELS,
        viewer_version=_VIEWER_VERSION,
        height=VIEWER_HEIGHT,
        key=f"viewer_{observer}_{run_id}_{idx}",
        default=None,
        **case["payload"],
    )

# --------------------------------------------------------------------------- #
# Évaluation
# --------------------------------------------------------------------------- #
st.markdown("### Évaluation")
prev = ratings.get(idx)
if prev:
    st.caption("Déjà noté – vous pouvez modifier votre évaluation.")

n_blebs = None
if phase == PHASE_COUNT:
    prev_blebs = int(prev["nb_blebs"]) if prev and prev["nb_blebs"] != "" else None
    n_blebs = st.radio(
        "Nombre de blebs sur les anévrismes",
        options=list(BLEB_OPTIONS),
        format_func=BLEB_OPTIONS.get,
        index=list(BLEB_OPTIONS).index(prev_blebs) if prev_blebs is not None else None,
        horizontal=True,
        key=f"blebs_{observer}_{run_id}_{idx}",
    )
    if SKIP_PHASE2_IF_ZERO_BLEBS and n_blebs == 0:
        st.caption("Avec « 0 bleb », la phase 2 de ce cas sera ignorée : vous passerez directement au cas suivant.")
    ready = n_blebs is not None
else:
    st.caption(
        "Les blebs sont segmentés (chacun avec sa couleur). Corrigez la segmentation au besoin avec le "
        "pinceau / la gomme, dans n'importe laquelle des trois coupes, puis validez."
    )
    ready = case is not None

if st.button("💾 Enregistrer", type="primary", disabled=not ready):
    extra = {}
    case_no = case_ids[idx] + 1  # numéro du cas dans la playlist d'origine (non mélangée)
    if phase == PHASE_SEG and case is not None:
        init_counts = {k: v for k, v in label_counts(case["labels"]).items() if k >= BLEB_LABEL}
        extra = {
            "voxels_blebs_initial": counts_to_str(init_counts),
            "voxels_blebs_corrige": counts_to_str(init_counts),
            "fichier_correction_nifti": "",
            "export_nifti": "",
        }
        same_scene = bool(viewer_value) and viewer_value.get("scene_id") == f"{current}|1"
        if same_scene and viewer_value.get("edited"):
            res = export_edited(observer, run_id, case_no, current, viewer_value["labels_gz"], case)
            extra["export_nifti"] = res["statut"]
            extra["fichier_correction_nifti"] = res.get("fichier", "")
            if "counts" in res:
                extra["voxels_blebs_corrige"] = counts_to_str({k: v for k, v in res["counts"].items() if k >= BLEB_LABEL})
            if res["statut"].startswith("erreur"):  # un export réussi n'affiche rien
                st.session_state["flash"] = [("warning", f"Export NIfTI : {res['statut']}")]
    save_rating(observer, run_id, idx, case_no, phase, current, n_blebs, extra)
    skip_next = SKIP_PHASE2_IF_ZERO_BLEBS and phase == PHASE_COUNT and n_blebs == 0 and idx + 1 < len(playlist)
    if skip_next:  # « 0 bleb » : la phase 2 est ignorée, et le résultat du cas est un NIfTI sans aucun bleb
        skipped = bleb_free_result(observer, run_id, case_ids[idx + 1] + 1, playlist[idx + 1])
        save_rating(observer, run_id, idx + 1, case_ids[idx + 1] + 1, PHASE_SEG, playlist[idx + 1], None, skipped)
        if skipped["export_nifti"].startswith("erreur"):
            st.session_state["flash"] = [("warning", f"Export NIfTI (0 bleb) : {skipped['export_nifti']}")]
    nxt = idx + (2 if skip_next else 1)
    if nxt < len(playlist):
        st.session_state[state_key] = nxt
    st.rerun()
