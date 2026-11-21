"""Banc d'essai du viewer MPR : page « Streamlit » factice + Chrome (ou Chromium) piloté par Playwright.

Auteur : Fakhrielddine Bader (20/11/2026). Prérequis : pip install playwright ; puis un navigateur, soit
`playwright install chromium`, soit un Chrome existant indiqué par la variable CHROME (ex. /usr/bin/google-chrome).
Lancement (dossier du dépôt) : python tests/viewer/test_viewer_retouche.py ; python tests/viewer/test_viewer_affichage.py"""
import base64, functools, gzip, http.server, os, sys, threading
from pathlib import Path
import numpy as np
from playwright.sync_api import sync_playwright

ROOT = str(Path(__file__).resolve().parents[2])   # racine du dépôt (sert mpr_viewer/ et tests/viewer/)
N = 40

def pack(a):
    return base64.b64encode(gzip.compress(np.asarray(a, np.uint8).ravel(order="F").tobytes())).decode()

def volume():
    """Anévrisme (2) en boule de rayon 12 au centre, artère (1) en dessous, bleb 1 (3) et bleb 2 (4) sur les côtés."""
    i, j, k = np.indices((N, N, N))
    lab = np.zeros((N, N, N), np.uint8)
    lab[(i - 20) ** 2 + (j - 20) ** 2 < 9] = 1
    lab[(i - 20) ** 2 + (j - 20) ** 2 + (k - 20) ** 2 < 144] = 2
    lab[(i - 31) ** 2 + (j - 20) ** 2 + (k - 20) ** 2 < 9] = 3
    lab[(i - 9) ** 2 + (j - 20) ** 2 + (k - 20) ** 2 < 9] = 4
    img = (lab > 0) * 200 + 20
    return lab, img

def args_phase2(lab, img, **extra):
    a = dict(
        scene_id="cas_test|1", case_label=None, eval_title="Blebs pré-segmentés", count_options=None, zero_hint="",
        verdict_blebs=[{"id": 3, "name": "Bleb 1", "color": "#ffd700"}, {"id": 4, "name": "Bleb 2", "color": "#00e5ff"}],
        verdict_options=[{"value": "retouche", "label": "Retoucher"}, {"value": "supprime", "label": "Supprimer"}],
        expected_count=2, expected_label="2 blebs", count_open_end=4, verdict_hint="", no_bleb_hint="",
        dims=[N, N, N], spacing=[0.4, 0.4, 0.4], center=[20, 20, 20],
        classes=[{"id": 1, "name": "Artères", "color": "#d62728"}, {"id": 2, "name": "Anévrismes", "color": "#1f77b4"},
                 {"id": 3, "name": "Bleb 1", "color": "#ffd700"}, {"id": 4, "name": "Bleb 2", "color": "#00e5ff"}],
        editable=True, bleb_label=3, parent_label=2,
        bleb_palette=["#ffd700", "#00e5ff", "#ff4dd2", "#7cfc00", "#ff8c00", "#b388ff", "#ff5252", "#40e0b0"], max_bleb_labels=8, viewer_version="test", height=800,
        labels_gz=pack(lab), image_gz=pack(img))
    a.update(extra)
    return a

class Banc:
    def __enter__(self):
        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *a): pass
        h = functools.partial(Quiet, directory=ROOT)
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), h)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.pw = sync_playwright().start()
        chrome = os.environ.get("CHROME")
        self.br = self.pw.chromium.launch(**({"executable_path": chrome} if chrome else {}), args=["--no-sandbox"])
        self.page = self.br.new_page(viewport={"width": 1420, "height": 900})
        self.errors = []
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.page.goto(f"http://127.0.0.1:{self.srv.server_port}/tests/viewer/harness.html")
        self.page.wait_for_function("window.ready === true")
        self.f = self.page.frame_locator("#f")
        self.fr = self.page.frames[1]
        return self

    def charger(self, args):
        self.page.evaluate("a => window.render(a)", args)
        self.fr.wait_for_function("typeof S !== 'undefined' && S && S.sceneId === %r" % args["scene_id"])
        self.fr.wait_for_function("document.getElementById('msg').style.display === 'none'")

    def compte(self, label):
        return self.fr.evaluate(f"Array.prototype.filter.call(S.v.labels, x => x === {label}).length")

    def bouton_bleb(self, nom, libelle):
        """Bouton « libelle » sur la ligne du bleb « nom » (bloc Évaluation)."""
        self.fr.evaluate("""([nom, lib]) => {
            const names = [...document.querySelectorAll('#evalOpts .vname')];
            const n = names.find(x => x.textContent.trim().startsWith(nom));
            const row = n.nextElementSibling;
            [...row.querySelectorAll('button')].find(b => b.textContent === lib).click();
        }""", [nom, libelle])

    def peindre_axial(self, dx=0, dy=0):
        """Clic gauche au centre de la vue axiale (+ décalage en pixels)."""
        box = self.page.frame_locator("#f").locator("#pane-axial canvas").first.bounding_box()
        x, y = box["x"] + box["width"] / 2 + dx, box["y"] + box["height"] / 2 + dy
        self.page.mouse.move(x, y); self.page.mouse.down(); self.page.mouse.move(x + 3, y + 1); self.page.mouse.up()

    def message(self):
        return self.fr.evaluate("document.getElementById('evalMsg').textContent")

    def __exit__(self, *a):
        self.br.close(); self.pw.stop(); self.srv.shutdown()
