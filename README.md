# ICA_blebs — validation de la segmentation des blebs

Auteurs : Fakhrielddine Bader, Florent Autrusseau.

Application Streamlit pour faire évaluer des anévrismes intracrâniens par des observateurs, dans un viewer de type
PACS : trois coupes (axiale, coronale, sagittale) sur l'image en niveaux de gris, et une vue 3D.

Chaque cas se déroule en deux phases :

1. **Comptage** : l'observateur voit l'image, les artères et l'anévrisme, et donne le nombre de blebs.
2. **Segmentation** : il voit les blebs pré-segmentés (un label et une couleur par bleb) et les corrige au pinceau
   ou à la gomme, directement sur les voxels. Il donne son avis sur chacun : « Correct », « À corriger » ou
   « Pas un bleb ».

## Installation et lancement

Avec [uv](https://docs.astral.sh/uv/getting-started/installation/) :

```bash
uv sync
uv run streamlit run app_mpr.py                      # playlist.txt du dépôt
uv run streamlit run app_mpr.py -- ma_playlist.txt   # autre playlist
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

- **Ordre aléatoire.** Les cas sont mélangés pour chaque passation ; la phase 1 d'un cas précède toujours sa phase 2.
- **Pas de retour en arrière.** Une réponse enregistrée n'est plus modifiable : on avance toujours.
- **« 0 bleb » en phase 1.** La phase 2 du cas est ignorée, et un NIfTI sans aucun bleb est enregistré comme résultat.
- **Verdict par bleb en phase 2.** L'enregistrement n'est possible qu'une fois chaque bleb pré-segmenté jugé. Un
  bleb « Pas un bleb » est rendu à l'anévrisme dans le fichier enregistré. « Correct » sur un bleb modifié, ou
  « À corriger » sur un bleb intact, est refusé avec un message.
- **Reprise.** Si la page est rechargée ou le navigateur fermé, l'observateur saisit le même identifiant et clique
  « Reprendre le test » : la passation reprend là où elle s'était arrêtée, dans le même ordre. Seules les réponses
  validées par « Enregistrer » sont conservées ; une correction en cours, non enregistrée, est perdue.

## Sorties

- `notes_observateurs.csv` : une ligne par réponse, ajoutée à chaque « Enregistrer ». La colonne `verdict_blebs`
  contient l'avis par bleb, par exemple `3:correct; 4:pas_un_bleb` (3 = Bleb 1, 4 = Bleb 2…).
- `resultats/resultats_<observateur>_<session>.csv` : récapitulatif écrit à la fin du test.
- `resultats/corrections_<observateur>_<session>/*_corrige.nii.gz` : segmentation corrigée, dans l'orientation et
  l'espace du fichier d'origine. Écrite quand l'observateur a modifié la segmentation, ou après « 0 bleb ».

## Contenu

| Fichier | Rôle |
|---|---|
| `app_mpr.py` | application Streamlit (protocole, enregistrement des réponses) |
| `mpr_utils.py` | lecture des volumes, réorientation, export NIfTI |
| `mpr_viewer/` | viewer MPR et 3D (composant Streamlit) |
| `tests/test_app_mpr.py` | tests sur volumes synthétiques : `uv run python tests/test_app_mpr.py` |
| `pyproject.toml`, `uv.lock` | environnement uv ; `requirements.txt` reste disponible pour pip |
| `Misc/` | scripts annexes |

## Déploiement sur Streamlit Community Cloud

Community Cloud n'utilise qu'un seul fichier de dépendances, et `uv.lock` passe avant `requirements.txt`. Depuis
l'ajout de `uv.lock`, c'est donc lui qui définit l'environnement de l'application déployée.

## Historique

- Version d'origine (viewer MPR, pinceau et gomme sur les voxels, export NIfTI, ordre aléatoire) : Florent Autrusseau.
- 16/11/2026, Fakhrielddine Bader : reprise d'une passation interrompue, identifiant de passation unique, bouton de
  démarrage masqué pendant le test, NIfTI sans bleb après « 0 bleb », tests, environnement uv, ce README ;
  verdict obligatoire par bleb en phase 2 et colonne `verdict_blebs`.
