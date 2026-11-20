"""Tests : compteur dans le panneau (plein écran), Shift + souris, couleur du réticule."""
import sys; from pathlib import Path; sys.path.insert(0, str(Path(__file__).parent))
from banc import Banc, volume, args_phase2
lab, img = volume()
OK = []
def check(nom, cond, detail=""):
    OK.append(cond); print(("OK   " if cond else "ECHEC"), nom, detail)
with Banc() as b:
    b.charger(args_phase2(lab, img, progress_text="Cas 12 / 60 — phase 2/2\nReste : 49 cas, celui-ci compris"))
    txt = b.fr.evaluate("document.getElementById('progress').innerText")
    check("compteur affiché dans le panneau", "Reste : 49 cas" in txt and b.fr.evaluate("document.getElementById('progress').style.display") == "", repr(txt))
    check("compteur à l'intérieur de la zone mise en plein écran", b.fr.evaluate("document.getElementById('wrap').contains(document.getElementById('progress'))"))
    b.fr.evaluate("document.getElementById('wrap').requestFullscreen()"); b.page.wait_for_timeout(500)
    fs = b.fr.evaluate("!!document.fullscreenElement")
    vis = b.fr.evaluate("(() => { const r = document.getElementById('progress').getBoundingClientRect(); return r.width > 0 && r.height > 0; })()")
    check("compteur visible en plein écran", vis, f"plein écran actif : {fs}")
    b.fr.evaluate("document.exitFullscreen()"); b.page.wait_for_timeout(300)
    # Shift + souris sur la vue coronale : le réticule suit la souris
    cur0 = b.fr.evaluate("S.cur.slice()")
    box = b.f.locator("#c-coronal").bounding_box()
    x, y = box["x"] + box["width"] * 0.30, box["y"] + box["height"] * 0.35
    b.page.mouse.move(x - 5, y)
    b.page.mouse.move(x, y)                       # sans Shift : rien ne bouge
    check("sans Shift : le réticule ne bouge pas", b.fr.evaluate("S.cur.slice()") == cur0)
    b.page.keyboard.down("Shift"); b.page.mouse.move(x + 2, y + 2); b.page.keyboard.up("Shift")
    cur1 = b.fr.evaluate("S.cur.slice()")
    check("Shift + souris : le réticule suit la souris", cur1 != cur0 and cur1[1] == cur0[1], f"{cur0} -> {cur1} (coronale : j fixe)")
    # en mode pinceau aussi, sans peindre
    b.bouton_bleb("Bleb 1", "Retoucher"); n3 = b.compte(3)
    b.page.keyboard.down("Shift"); b.page.mouse.move(x + 30, y + 10); b.page.keyboard.up("Shift")
    check("Shift + souris en mode pinceau : réticule déplacé, rien de peint", b.fr.evaluate("S.cur.slice()") != cur1 and b.compte(3) == n3)
    # couleur du réticule : plus de jaune sur la ligne du réticule
    b.page.mouse.move(5, 5)
    # couleur du réticule : blanc (aucune composante dominante) sur la ligne du réticule, hors des blebs
    px = b.fr.evaluate("""(() => { const p = S.panes.axial, c = p.canvas, ctx = c.getContext('2d');
        const [col, row] = MPR.voxelToPixel('axial', S.v, S.cur[0], S.cur[1], S.cur[2]);
        const x = Math.round((p.ox + (col + 0.5) * p.ppx) * p.dpr), y = Math.round((p.oy + 2) * p.dpr);
        let best = null;   // pixel le plus clair sur la verticale du réticule, en haut de la vue (fond noir)
        for (let dx = -2; dx <= 2; dx++) for (let dy = 0; dy < 12 * p.dpr; dy++) {
          const d = ctx.getImageData(x + dx, y + dy, 1, 1).data; if (!best || d[0] + d[1] + d[2] > best[0] + best[1] + best[2]) best = [...d]; }
        return best; })()""")
    check("réticule blanc, plus jaune", px[0] > 120 and abs(px[0] - px[2]) < 30 and abs(px[1] - px[2]) < 30, str(px))
    check("aucune erreur JavaScript", not b.errors, str(b.errors))
print(f"\n{sum(OK)}/{len(OK)} vérifications réussies")
raise SystemExit(0 if all(OK) else 1)
