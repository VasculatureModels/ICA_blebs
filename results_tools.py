"""
Récupérer les résultats quand l'application tourne sur Streamlit Community Cloud.

Sur Streamlit Cloud, le disque du serveur est ÉPHÉMÈRE et inaccessible : les fichiers écrits dans
`resultats/` disparaissent au redémarrage, à la mise en veille ou au redéploiement. Ce module propose :

1. un espace « Administrateur » (barre latérale, protégé par mot de passe) pour télécharger les résultats ;
2. une sauvegarde automatique, à chaque enregistrement, vers un stockage distant (facultative) :
   - un dépôt GitHub PRIVÉ, et/ou
   - un dossier Nextcloud (par exemple l'UNCloud de Nantes Université), par WebDAV.

Configuration : dans Streamlit Cloud, « Settings » > « Secrets » (format TOML) :

    ADMIN_PASSWORD = "un-mot-de-passe-solide"

    [nextcloud]                       # facultatif : sauvegarde vers Nextcloud (WebDAV)
    url      = "https://VOTRE-NEXTCLOUD"    # adresse de votre Nextcloud, sans « /remote.php/... »
    user     = "votre.identifiant"
    password = "xxxxx-xxxxx-xxxxx-xxxxx-xxxxx"   # MOT DE PASSE D'APPLICATION (pas votre mot de passe habituel)
    folder   = "Resultats/ica_blebs"        # dossier de destination (créé s'il n'existe pas)

    # variante sans identifiants personnels : lien de partage « peut modifier » d'un dossier
    # [nextcloud]
    # url = "https://VOTRE-NEXTCLOUD"
    # share_token = "jeton-du-lien"          # la fin de l'adresse du lien : .../s/<jeton>
    # share_password = "mot-de-passe-du-lien"  # si le lien en a un
    # folder = ""

    [backup]                          # facultatif : sauvegarde vers un dépôt GitHub PRIVÉ
    token  = "github_pat_xxx"         # jeton avec le droit « Contents : lecture et écriture » sur ce dépôt
    repo   = "mon-compte/ica_blebs_resultats"   # dépôt DISTINCT de celui de l'application
    branch = "main"
    folder = "resultats"

Sans secrets, rien de tout cela n'apparaît et l'application se comporte comme avant.
"""

import base64
import hmac
import io
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import quote


# --------------------------------------------------------------------------- #
# Secrets
# --------------------------------------------------------------------------- #
def get_secret(st, key, default=None):
    """Lit un secret Streamlit ; renvoie `default` s'il n'existe pas (ou s'il n'y a aucun fichier de secrets)."""
    try:
        return st.secrets[key]
    except Exception:
        return default


def _section(st, name) -> dict | None:
    cfg = get_secret(st, name)
    if not cfg:
        return None
    try:
        return {k: cfg[k] for k in cfg}
    except Exception:
        return None


def backup_config(st) -> list[dict] | None:
    """Destinations de sauvegarde configurées (liste de dictionnaires avec une clé « provider »), ou None."""
    targets = []
    gh = _section(st, "backup")
    if gh and gh.get("token") and gh.get("repo"):
        targets.append(dict(gh, provider="github"))
    nc = _section(st, "nextcloud")
    if nc and nc.get("url") and (nc.get("share_token") or (nc.get("user") and nc.get("password"))):
        targets.append(dict(nc, provider="nextcloud"))
    return targets or None


# --------------------------------------------------------------------------- #
# Fichiers de résultats / téléchargement
# --------------------------------------------------------------------------- #
def list_result_files(results_dir, ratings_file) -> list[Path]:
    """Tous les fichiers produits : dossier de résultats (récursif) + journal commun."""
    files = []
    rd = Path(results_dir)
    if rd.exists():
        files += sorted(p for p in rd.rglob("*") if p.is_file())
    rf = Path(ratings_file)
    if rf.is_file():
        files.append(rf)
    return files


def zip_bytes(paths, base) -> bytes:
    """Archive ZIP en mémoire ; les noms dans l'archive sont relatifs à `base`."""
    base = Path(base).resolve()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in paths:
            p = Path(p)
            try:
                name = p.resolve().relative_to(base).as_posix()
            except ValueError:
                name = p.name
            z.write(p, arcname=name)
    return buf.getvalue()


def human_size(n: int) -> str:
    for unit in ("o", "Ko", "Mo", "Go"):
        if n < 1024 or unit == "Go":
            return f"{n:.0f} {unit}" if unit == "o" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} o"


def admin_panel(st, output_dir, results_dir, ratings_file):
    """Espace administrateur (à appeler dans `with st.sidebar:`). N'existe que si ADMIN_PASSWORD est défini."""
    pwd = get_secret(st, "ADMIN_PASSWORD")
    if not pwd:
        return
    with st.expander("🔒 Administrateur"):
        entered = st.text_input("Mot de passe", type="password", key="admin_pwd")
        if not entered:
            return
        if not hmac.compare_digest(str(entered).encode(), str(pwd).encode()):
            st.error("Mot de passe incorrect.")
            return
        files = list_result_files(results_dir, ratings_file)
        if not files:
            st.info("Aucun résultat pour le moment.")
            return
        total = sum(p.stat().st_size for p in files)
        st.caption(f"{len(files)} fichiers, {human_size(total)}. Attention : le disque du serveur est éphémère.")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        st.download_button(
            "⬇ Tout télécharger (zip)", zip_bytes(files, output_dir), file_name=f"resultats_{stamp}.zip",
            mime="application/zip", use_container_width=True,
        )
        rf = Path(ratings_file)
        if rf.is_file():
            st.download_button(
                "⬇ Journal des notes (CSV)", rf.read_bytes(), file_name=rf.name, mime="text/csv", use_container_width=True
            )
        for p in files:
            if p.suffix == ".csv" and p != rf:
                st.download_button(
                    f"⬇ {p.name}", p.read_bytes(), file_name=p.name, mime="text/csv", key=f"dl_{p.name}", use_container_width=True
                )


# --------------------------------------------------------------------------- #
# Sauvegarde distante (GitHub, dépôt privé)
# --------------------------------------------------------------------------- #
def _put_file(sess, cfg, remote_path, content: bytes, message):
    """Crée ou met à jour un fichier du dépôt (API « contents » de GitHub)."""
    url = f"https://api.github.com/repos/{cfg['repo']}/contents/{quote(remote_path)}"
    headers = {"Authorization": f"Bearer {cfg['token']}", "Accept": "application/vnd.github+json"}
    branch = cfg.get("branch", "main")
    last = None
    for _ in range(2):  # une seconde tentative si le fichier a changé entre-temps (conflit de version)
        r = sess.get(url, headers=headers, params={"ref": branch}, timeout=20)
        sha = r.json().get("sha") if r.status_code == 200 else None
        payload = {"message": message, "content": base64.b64encode(content).decode("ascii"), "branch": branch}
        if sha:
            payload["sha"] = sha
        last = sess.put(url, headers=headers, json=payload, timeout=60)
        if last.status_code in (200, 201):
            return
        if last.status_code not in (409, 422):
            break
    detail = ""
    try:
        detail = last.json().get("message", "")
    except Exception:
        pass
    raise RuntimeError(f"HTTP {last.status_code} {detail}".strip())


# --- Nextcloud (WebDAV) -------------------------------------------------------------------------------------
def _nc_endpoint(cfg):
    """(adresse WebDAV de la racine, identifiants) : compte personnel, ou lien de partage."""
    url = str(cfg["url"]).rstrip("/")
    if cfg.get("share_token"):
        return f"{url}/public.php/webdav", (str(cfg["share_token"]), str(cfg.get("share_password", "")))
    user = str(cfg["user"])
    return f"{url}/remote.php/dav/files/{quote(user, safe='')}", (user, str(cfg["password"]))


def _nc_error(code: int) -> str:
    hints = {
        401: "identifiants refusés (utilisez un mot de passe d'application)",
        403: "accès refusé (droits du dossier ou du lien de partage)",
        404: "adresse ou identifiant introuvable",
        423: "fichier verrouillé",
        507: "espace de stockage insuffisant",
    }
    return f"HTTP {code}" + (f" : {hints[code]}" if code in hints else "")


def _nc_put(sess, cfg, remote_path, content: bytes):
    """Dépose un fichier dans Nextcloud ; crée les dossiers manquants au besoin."""
    base, auth = _nc_endpoint(cfg)
    parts = [p for p in remote_path.split("/") if p]
    target = base + "/" + "/".join(quote(p, safe="") for p in parts)

    r = sess.put(target, data=content, auth=auth, timeout=60)
    if r.status_code == 409:  # dossier parent absent : on crée chaque niveau (MKCOL), puis on réessaie
        cur = base
        for p in parts[:-1]:
            cur += "/" + quote(p, safe="")
            m = sess.request("MKCOL", cur, auth=auth, timeout=20)
            if m.status_code not in (201, 405):  # 201 : créé ; 405 : existe déjà
                raise RuntimeError(f"création du dossier « {p} » impossible : {_nc_error(m.status_code)}")
        r = sess.put(target, data=content, auth=auth, timeout=60)
    if r.status_code not in (200, 201, 204):
        raise RuntimeError(_nc_error(r.status_code))


# --- répartition ----------------------------------------------------------------------------------------------------------
def _upload_one(provider, sess, cfg, folder, rel, content, message):
    remote = f"{folder}/{rel}" if folder else rel
    if provider == "nextcloud":
        _nc_put(sess, cfg, remote, content)
    else:
        _put_file(sess, cfg, remote, content, message)


def backup_files(paths, base, cfg, session=None, message="Sauvegarde automatique des résultats"):
    """Envoie les fichiers vers la ou les destinations configurées.

    `cfg` : un dictionnaire (une destination ; GitHub par défaut) ou la liste renvoyée par `backup_config`.
    Ne lève jamais d'exception : renvoie [(nom, ok, message_d_erreur)]. Avec plusieurs destinations,
    les messages d'erreur sont préfixés par « [github] » ou « [nextcloud] »."""
    if session is None:
        import requests

        session = requests.Session()
    targets = [cfg] if isinstance(cfg, dict) else list(cfg)
    prefix = not isinstance(cfg, dict)
    base = Path(base).resolve()
    out = []
    for p in paths:
        p = Path(p)
        if not p.is_file():
            continue
        try:
            rel = p.resolve().relative_to(base).as_posix()
        except ValueError:
            rel = p.name
        content = p.read_bytes()
        for t in targets:
            provider = t.get("provider", "github")
            folder = str(t.get("folder", "resultats" if provider == "github" else "")).strip("/")
            try:
                _upload_one(provider, session, t, folder, rel, content, message)
                out.append((rel, True, ""))
            except Exception as e:
                out.append((rel, False, f"[{provider}] {e}" if prefix else str(e)))
    return out
