# ICA_blebs — validation de la segmentation des blebs

Auteurs : Fakhrielddine Bader, Florent Autrusseau.

Application Streamlit pour faire évaluer des anévrismes intracrâniens par des observateurs, dans un viewer de type
PACS : trois coupes (axiale, coronale, sagittale) sur l'image en niveaux de gris, et une vue 3D.

Chaque cas se déroule en deux phases :

1. **Comptage** : l'observateur voit l'image, les artères et l'anévrisme, et donne le nombre de blebs. La question
   est posée dans le panneau gauche du viewer (bloc « Évaluation »), à côté des images.
2. **Segmentation** : il voit les blebs pré-segmentés (un label et une couleur par bleb) et les corrige au pinceau
   ou à la gomme, directement sur les voxels. Il donne son avis sur chacun : « Correct », « À corriger » ou
   « Pas un bleb ».

Après la phase 2 (pas après « 0 bleb »), un **aperçu final** (« phase 3 ») montre ce qui vient d'être enregistré pour le cas : le masque
relu sur le disque, le nombre de blebs qu'il contient et les deux lignes du CSV. Rien n'y est modifiable ; « Cas
suivant » passe au cas suivant. Pour le retirer : `SHOW_REVIEW = False` dans `app_mpr.py`.

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

- **Tout se fait dans le panneau gauche du viewer.** Le bloc « Évaluation » contient la question de la phase 1,
  les avis par bleb de la phase 2 et le bouton « Enregistrer ». Rien n'est affiché sous le viewer ; un message
  éventuel (avis refusé, erreur d'export) apparaît en haut de la page.
- **Nom du patient.** Il est affiché dans les deux phases, dans le titre et en haut du panneau du viewer. La case
  « Masquer le nom du patient » de la barre latérale le cache (évaluation en aveugle).
- **Ordre aléatoire.** Les cas sont mélangés pour chaque passation ; la phase 1 d'un cas précède toujours sa phase 2.
- **Pas de retour en arrière.** Une réponse enregistrée n'est plus modifiable : on avance toujours.
- **« 0 bleb » en phase 1.** La phase 2 du cas est ignorée, et un NIfTI sans aucun bleb est enregistré comme résultat.
- **Phase 2 guidée.** Seuls les blebs réellement pré-segmentés sont listés. Les outils (pinceau, gomme) restent
  cachés jusqu'à ce qu'un bleb soit jugé « À corriger » : ils s'appliquent alors à ce bleb seul. Le pinceau
  l'étend sur l'anévrisme, jamais sur un autre bleb ; la gomme rend ses voxels à l'anévrisme. « + Nouveau bleb »
  ajoute un bleb manquant. Un bleb jugé « Pas un bleb » garde sa couleur à l'écran et n'est rendu à
  l'anévrisme qu'à l'enregistrement. La partie « Affichage » (opacité, contraste, plein écran) est ouverte en
  phase 1 et repliée en phase 2 ; un clic sur son titre l'ouvre. Le plein écran est conservé d'une image à l'autre.
- **Annuler et réinitialiser.** « Annuler » (Ctrl+Z) défait le dernier coup de pinceau ou de gomme, un trait à
  la fois. « Réinitialiser ce bleb » remet le bleb en cours dans son état d'origine, sans toucher aux autres.
- **Contrôles avant l'enregistrement (phase 2)**, affichés dans le panneau au-dessus du bouton : un avis
  incohérent avec les corrections bloque l'enregistrement ; un nombre de blebs différent de celui compté en
  phase 1 demande un second clic de confirmation.
- **Verdict par bleb en phase 2.** L'enregistrement n'est possible qu'une fois chaque bleb pré-segmenté jugé. Un
  bleb « Pas un bleb » est rendu à l'anévrisme dans le fichier enregistré. « Correct » sur un bleb modifié, ou
  « À corriger » sur un bleb intact, est refusé avec un message.
- **Reprise.** Si la page est rechargée ou le navigateur fermé, l'observateur saisit le même identifiant et clique
  « Reprendre le test » : la passation reprend là où elle s'était arrêtée, dans le même ordre. Seules les réponses
  validées par « Enregistrer » sont conservées ; une correction en cours, non enregistrée, est perdue.

## Sorties

- `notes_observateurs.csv` : une ligne par réponse, ajoutée à chaque « Enregistrer ». La colonne `verdict_blebs`
  contient l'avis par bleb, par exemple `3:correct; 4:pas_un_bleb` (3 = Bleb 1, 4 = Bleb 2…). La colonne
  `nb_blebs_final` donne le nombre de blebs de la segmentation enregistrée en phase 2 ; elle se compare au
  `nb_blebs` de la phase 1 du même cas.
- `resultats/resultats_<observateur>_<session>.csv` : récapitulatif écrit à la fin du test.
- `resultats/corrections_<observateur>_<session>/*_corrige.nii.gz` : segmentation corrigée, dans l'orientation et
  l'espace du fichier d'origine. Écrite pour chaque cas : après la phase 2 (la pré-segmentation elle-même si
  rien n'a été modifié), ou après « 0 bleb » (segmentation sans bleb).

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
