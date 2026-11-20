# ICA_blebs — validation de la segmentation des blebs

Auteurs : Fakhrielddine Bader, Florent Autrusseau.

Application Streamlit pour faire évaluer des anévrismes intracrâniens par des observateurs, dans un viewer de type
PACS : trois coupes (axiale, coronale, sagittale) sur l'image en niveaux de gris, et une vue 3D.

Chaque cas se déroule en deux phases :

1. **Comptage** : l'observateur voit l'image, les artères et l'anévrisme, et donne le nombre de blebs. La question
   est posée dans le panneau gauche du viewer (bloc « Évaluation »), à côté des images.
2. **Segmentation** : il voit les blebs pré-segmentés (un label et une couleur par bleb) et les corrige au pinceau
   ou à la gomme, directement sur les voxels. Sans choix, un bleb est gardé tel quel ; il peut être retouché
   (« Retoucher ») ou supprimé (« Supprimer »), et un bleb manquant peut être ajouté (« + Nouveau bleb »).

Après la phase 2, on passe directement au cas suivant (l'aperçu final, « phase 3 », a été retiré le 19/11/2026).

## Étude des observateurs : un jeu par identifiant

Chaque observateur a son identifiant et sa playlist (jeu de 50 cas : 20 cas communs aux trois observateurs, pour
mesurer leur accord, et 30 cas propres ; décision du 20/11/2026, tirage `tirer_jeux` v1.1.0) :

| Identifiant | Observateur | Playlist |
|---|---|---|
| `JB` | Julien Boucherit | `playlist_JB.txt` |
| `GG` | Guillaume Geffroy | `playlist_GG.txt` |
| `VL` | Vincent L'Allinec | `playlist_VL.txt` |

Les découpes (images et segmentations) sont dans `images/`, à côté de `app_mpr.py`.
L'observateur lance l'application **sans argument**, saisit son identifiant (majuscules ou minuscules) et clique
« Démarrer le test » : sa playlist s'ouvre.

**Identifiant libre** (tout autre identifiant, par exemple `TEST` ou `LOUISE`) : 50 cas tirés au hasard parmi ceux des
trois playlists de l'étude. Le tirage dépend de l'identifiant : le même identifiant retrouve toujours les mêmes cas
(la reprise fonctionne), et l'ordre est mélangé à chaque passation. Un bandeau « Identifiant hors étude » le
signale. Les réponses sont enregistrées **à part** : `notes_libres.csv` et `resultats/libres/` (aussi dans la
sauvegarde distante, sous `libres/`). Elles ne se mélangent jamais aux passations de l'étude. Nombre de cas :
variable `BLEB_FREE_N_CASES` (50 par défaut).

```bash
uv run streamlit run app_mpr.py
```

Les playlists sont lues dans le dossier de `app_mpr.py`, ou dans `BLEB_PLAYLIST_DIR`. Elles sont produites par
`outils/tirer_jeux.py` (tirage au hasard, graine fixe ; voir l'en-tête du script), qui écrit aussi le groupe de
chaque cas (`tirage_jeux.csv`). Le manifeste des découpes (`crops_manifest.csv`) ne doit jamais être donné aux
observateurs.

## Installation et lancement

Avec [uv](https://docs.astral.sh/uv/getting-started/installation/) :

```bash
uv sync
uv run streamlit run app_mpr.py                      # étude : identifiant JB, GG ou VL -> sa playlist
uv run streamlit run app_mpr.py -- ma_playlist.txt   # mode libre : tout identifiant, playlist donnée
```

Pour une annotation de calibration où chaque bleb pré-segmenté doit être vu, `BLEB_SKIP_PHASE2=0` garde la
phase 2 même après « 0 bleb » en phase 1 (par défaut, la phase 2 est sautée, comme dans l'étude) :

```bash
BLEB_SKIP_PHASE2=0 uv run streamlit run app_mpr.py -- ma_playlist.txt
```

Pour écrire les réponses ailleurs que dans le dossier du dépôt :

```bash
BLEB_OUTPUT_DIR=~/mes_sorties uv run streamlit run app_mpr.py -- ma_playlist.txt
```

Sans uv : `pip install -r requirements.txt`, puis `streamlit run app_mpr.py`.

## Playlist

Une entrée par ligne, au format `image ; segmentation`, et **deux lignes consécutives par cas** :

```
images/RCAN_01_167_S_0.4__ICA_1.nrrd ; images/RCAN_01_167_S_0.4__ICA_1.seg.nrrd
images/RCAN_01_167_S_0.4__ICA_1.nrrd ; images/RCAN_01_167_S_0.4__ICA_1_blebs.seg.nrrd
```

- 1re ligne (phase 1) : artères = 1, anévrisme = 2 ;
- 2e ligne (phase 2) : les mêmes, plus un label par bleb (3, 4, 5…).

Les fichiers peuvent être en NRRD ou en NIfTI. L'image et la segmentation doivent avoir la même grille.

## Déroulement d'une passation

- **Tout se fait dans le panneau gauche du viewer.** Le bloc « Évaluation » contient la question de la phase 1,
  les choix par bleb de la phase 2 et le bouton « Enregistrer ». Rien n'est affiché sous le viewer ; un message
  éventuel (choix refusé, erreur d'export) apparaît en haut de la page.
- **Plein écran.** Bouton « Plein écran », ou double-clic sur le panneau gauche (hors boutons et réglages) ; un
  nouveau double-clic en sort. Il est conservé d'une image à l'autre, dans les deux phases.
- **Nom du patient.** Il n'est jamais affiché (évaluation en aveugle), ni en phase 1 ni en phase 2.
- **Phase 1.** Pas de rangée d'outils dans le panneau (seule la navigation est possible : réticule, défilement,
  zoom, fenêtrage, rotation 3D).
- **Ordre aléatoire.** Les cas sont mélangés pour chaque passation ; la phase 1 d'un cas précède toujours sa phase 2.
- **Pas de retour en arrière.** Une réponse enregistrée n'est plus modifiable : on avance toujours.
- **« 0 bleb » en phase 1.** La phase 2 du cas est ignorée, et un NIfTI sans aucun bleb est enregistré comme résultat.
- **Phase 2 guidée.** Seuls les blebs réellement pré-segmentés sont listés, chacun avec deux boutons :
  - sans choix, le bleb est **gardé** tel quel ;
  - « **Retoucher** » affiche le pinceau et la gomme pour ce bleb seul (taille 1 mm par défaut, réglable). Le
    pinceau l'étend sur l'anévrisme, jamais sur un autre bleb ; la gomme rend ses voxels à l'anévrisme ;
  - « **Supprimer** » : le bleb est rendu tout de suite à l'anévrisme, on le voit disparaître et son nom est
    barré ; un second clic sur « Supprimer » le rétablit ;
  - un second clic sur un choix l'annule ; quitter « Retoucher » annule les retouches de ce bleb.

  « + Nouveau bleb » ajoute un bleb manquant, avec « Dessiner » et « Supprimer ». « Supprimer » retire tout de
  suite ce bleb en entier ; pour en faire un autre, on reclique sur « + Nouveau bleb ». Un bleb ajouté laissé
  vide (jamais dessiné, ou trait hors de l'anévrisme) bloque l'enregistrement, avec un message. La partie « Affichage »
  (opacité, contraste, plein écran) est ouverte en phase 1 et repliée en phase 2 ; un clic sur son titre l'ouvre.
- **Annuler et réinitialiser.** « Annuler » (Ctrl+Z) défait le dernier coup de pinceau ou de gomme, un trait à
  la fois. « Réinitialiser ce bleb » remet le bleb en cours dans son état d'origine, sans toucher aux autres.
- **Contrôles avant l'enregistrement (phase 2)**, affichés dans le panneau au-dessus du bouton : « Retoucher »
  sans aucune retouche bloque l'enregistrement ; un nombre de blebs différent de celui compté en phase 1 demande
  un second clic de confirmation.
- **Reprise.** Si la page est rechargée ou le navigateur fermé, l'observateur saisit le même identifiant et clique
  « Reprendre le test » : la passation reprend là où elle s'était arrêtée, dans le même ordre. Seules les réponses
  validées par « Enregistrer » sont conservées ; une correction en cours, non enregistrée, est perdue.

## Sorties

- `notes_observateurs.csv` : une ligne par réponse, ajoutée à chaque « Enregistrer ». La colonne `verdict_blebs`
  contient la décision par bleb : `garde`, `retouche`, `supprime` pour un bleb pré-segmenté, `ajoute` pour un
  bleb ajouté, par exemple `3:garde; 4:supprime; 5:ajoute` (3 = Bleb 1, 4 = Bleb 2…). La colonne
  `nb_blebs_final` donne le nombre de blebs de la segmentation enregistrée en phase 2 ; elle se compare au
  `nb_blebs` de la phase 1 du même cas.
- `resultats/resultats_<observateur>_<session>.csv` : récapitulatif écrit à la fin du test.
- Identifiants libres : mêmes fichiers, dans `notes_libres.csv` et `resultats/libres/`.
- `resultats/corrections_<observateur>_<session>/*_corrige.nii.gz` : segmentation corrigée, dans l'orientation et
  l'espace du fichier d'origine. Écrite pour chaque cas : après la phase 2 (la pré-segmentation elle-même si
  rien n'a été modifié), ou après « 0 bleb » (segmentation sans bleb).

## Contenu

| Fichier | Rôle |
|---|---|
| `app_mpr.py` | application Streamlit (protocole, enregistrement des réponses) |
| `mpr_utils.py` | lecture des volumes, réorientation, export NIfTI |
| `mpr_viewer/` | viewer MPR et 3D (composant Streamlit) |
| `tests/test_app_mpr.py` | tests sur volumes synthétiques : `python tests/test_app_mpr.py` |
| `tests/viewer/` | tests du viewer dans un vrai navigateur (Playwright) : `python tests/viewer/test_viewer_retouche.py`, `python tests/viewer/test_viewer_affichage.py` ; prérequis dans `tests/viewer/banc.py` |
| `playlist_JB.txt`, `playlist_GG.txt`, `playlist_VL.txt` | jeux de l'étude (un par observateur) |
| `outils/tirer_jeux.py` | tirage des jeux ; tests : `python tests/test_tirer_jeux.py` |
| `outils/verifier_sorties.py` | vérification des sorties d'une passation |
| `pyproject.toml`, `requirements.txt` | environnement (uv ou pip) ; Streamlit Cloud utilise `requirements.txt` |

## Vérifier ce qu'une passation a enregistré

`outils/verifier_sorties.py` relit, sans rien modifier, le CSV, chaque NIfTI résultat et la pré-segmentation
d'origine, puis contrôle cas par cas : fichier présent, grille identique, rien de modifié hors de l'anévrisme,
« 0 bleb » sans bleb, décisions cohérentes avec le fichier (`garde` identique, `retouche` modifié, `supprime`
rendu à l'anévrisme, `ajoute` pour tout bleb nouveau), et nombres du CSV identiques à ceux des fichiers.

```bash
uv run python outils/verifier_sorties.py --sorties ~/mes_sorties --observateur mon_identifiant
```

Test de bout en bout (passation complète simulée, puis fichiers altérés exprès) :
`uv run python tests/test_verifier_sorties.py`.

## Déploiement sur Streamlit Community Cloud

Community Cloud n'utilise qu'un seul fichier de dépendances. Le dépôt n'a pas de `uv.lock` : c'est donc
`requirements.txt` qui définit l'environnement de l'application déployée. Le disque de Community Cloud est
éphémère : les résultats sont envoyés à chaque « Enregistrer » vers la sauvegarde distante (UNCloud), configurée dans
les secrets de l'application (`.streamlit/secrets.toml` en local, jamais dans le dépôt).

## Historique

- Version d'origine (viewer MPR, pinceau et gomme sur les voxels, export NIfTI, ordre aléatoire) : Florent Autrusseau.
- 16/11/2026, Fakhrielddine Bader : reprise d'une passation interrompue, identifiant de passation unique, bouton de
  démarrage masqué pendant le test, NIfTI sans bleb après « 0 bleb », tests, environnement uv, ce README ;
  verdict obligatoire par bleb en phase 2 et colonne `verdict_blebs`.
- 17/11/2026, Fakhrielddine Bader : évaluation dans le panneau du viewer, phase 2 guidée, aperçu final (phase 3),
  vérificateur des sorties ; demandes de Florent Autrusseau : plus de bouton « Correct », « Retoucher » et
  « Supprimer », pinceau à 1 mm, suppression d'un bleb ajouté, double-clic pour le plein écran.
- 19/11/2026, Fakhrielddine Bader : étude des observateurs — un jeu par identifiant (`JB`, `GG`, `VL` ; 60 cas dont
  20 communs), outil de tirage `outils/tirer_jeux.py` ; nom du patient jamais affiché ; plus de rangée d'outils en
  phase 1 ; aperçu final (phase 3) retiré ; données, réponses de test et scripts annexes retirés du dépôt.
- 20/11/2026, Fakhrielddine Bader, retours des tests (Louise, Laurence, Adrien, Florent Autrusseau) :
  - bug corrigé : revenir sur un bleb déjà retouché (« Retoucher » après être passé à un autre bleb) effaçait ses
    retouches ; elles sont maintenant conservées, et un choix qui efface des retouches (annuler « Retoucher »,
    « Supprimer ») demande un second clic ;
  - réticule de navigation blanc en tirets (il se confondait avec un bleb jaune) ;
  - progression (« Cas 12 / 50 — phase 2/2 ») dans le panneau du viewer : visible aussi en plein écran ;
  - Shift + déplacement de la souris : le réticule suit la souris et les trois vues se synchronisent (comme dans Slicer) ;
  - identifiants libres : 50 cas tirés au hasard, résultats à part ;
  - jeux de 50 cas (20 communs + 30 propres), `tirer_jeux` v1.1.0 ; tests du viewer dans un navigateur.
