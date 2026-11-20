"""Tests du bug de retouche (Louise, 20/11/2026), dans Chrome."""
import sys; from pathlib import Path; sys.path.insert(0, str(Path(__file__).parent))
from banc import Banc, volume, args_phase2
lab, img = volume()
OK = []
def check(nom, cond, detail=""):
    OK.append(cond); print(("OK   " if cond else "ECHEC"), nom, detail)

with Banc() as b:
    def neuf():
        b.charger(args_phase2(lab, img, scene_id=f"cas_{len(OK)}|1"))
    titre = lambda: b.fr.evaluate("document.getElementById('toolTitle').textContent")
    actifs = lambda: b.fr.evaluate("[...document.querySelectorAll('#evalOpts .row button.on')].map(x => x.closest('.row').previousElementSibling.textContent.trim() + ':' + x.textContent)")

    # 1. scénario de Louise : A retouché, passage à B, retour à A
    neuf(); i0 = b.compte(3)
    b.bouton_bleb("Bleb 1", "Retoucher"); b.peindre_axial(); a = b.compte(3)
    b.bouton_bleb("Bleb 2", "Retoucher"); b.bouton_bleb("Bleb 1", "Retoucher")
    check("1. retour sur Bleb 1 : retouche conservée", b.compte(3) == a > i0, f"{i0} -> {a} -> {b.compte(3)}")
    check("1. outils de Bleb 1 réaffichés", titre() == "Retouche : Bleb 1", titre())
    check("1. les deux choix « Retoucher » restent actifs", sorted(actifs()) == ["Bleb 1:Retoucher", "Bleb 2:Retoucher"], actifs())
    # 2. on continue à retoucher A : les retouches s'ajoutent
    b.peindre_axial(dx=-25); c = b.compte(3)
    check("2. nouvelle retouche ajoutée à l'ancienne", c > a, f"{a} -> {c}")
    # 3. annuler « Retoucher » sur le bleb actif : confirmation demandée
    b.bouton_bleb("Bleb 1", "Retoucher")
    check("3. 1er clic d'annulation : rien n'est effacé", b.compte(3) == c and "Cliquez de nouveau" in b.message(), b.message().splitlines()[0])
    b.bouton_bleb("Bleb 1", "Retoucher")
    check("3. 2e clic : bleb remis à l'origine, choix annulé", b.compte(3) == i0 and "Bleb 1:Retoucher" not in actifs(), str(b.compte(3)))
    # 4. « Supprimer » sur un bleb retouché : confirmation demandée
    neuf(); b.bouton_bleb("Bleb 1", "Retoucher"); b.peindre_axial(); a = b.compte(3)
    b.bouton_bleb("Bleb 1", "Supprimer")
    check("4. 1er clic sur Supprimer : rien n'est effacé", b.compte(3) == a and "Supprimer" in b.message(), str(b.compte(3)))
    b.bouton_bleb("Bleb 1", "Supprimer")
    check("4. 2e clic : bleb supprimé", b.compte(3) == 0 and "Bleb 1:Supprimer" in actifs(), str(actifs()))
    # 5. « Retoucher » sans aucune retouche : un second clic l'annule directement (comportement inchangé)
    neuf(); b.bouton_bleb("Bleb 1", "Retoucher"); b.bouton_bleb("Bleb 2", "Retoucher"); b.bouton_bleb("Bleb 1", "Retoucher")
    check("5. sans retouche, le second clic annule le choix", actifs() == ["Bleb 2:Retoucher"], str(actifs()))
    # 6. enregistrement après le scénario de Louise : le masque envoyé contient la retouche
    neuf(); b.bouton_bleb("Bleb 1", "Retoucher"); b.peindre_axial(); a = b.compte(3)
    b.bouton_bleb("Bleb 2", "Retoucher"); b.bouton_bleb("Bleb 1", "Retoucher"); b.bouton_bleb("Bleb 2", "Retoucher")  # B sans retouche : annulé
    n0 = b.page.evaluate("window.values.length")
    b.fr.evaluate("document.getElementById('evalSave').click()")
    b.page.wait_for_function(f"window.values.length > {n0} && window.values[window.values.length-1].save")
    val = b.page.evaluate("window.values[window.values.length-1]")
    check("6. valeur enregistrée : Bleb 1 retouché avec ses voxels", val["verdicts"] == {"3": "retouche"} and val["counts"]["3"] == a,
          f"{val['verdicts']} {val['counts']}")
    check("aucune erreur JavaScript", not b.errors, str(b.errors))
print(f"\n{sum(OK)}/{len(OK)} vérifications réussies")
raise SystemExit(0 if all(OK) else 1)
