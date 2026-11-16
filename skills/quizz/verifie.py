#!/usr/bin/env python3
"""Vérifie les visuels d'un quiz construit, avant publication : rendus pour de vrai dans Chrome sans écran.

Usage : python3 verifie.py sortie/index.html [--mobile]

Pour chaque visuel : des contrôles mesurés dans la page (débordement de la toile, texte coupé ou tronqué, textes qui se
chevauchent, contraste trop faible, texte minuscule, toile trop grande pour son contenu, image cassée ou de mauvaise
forme), et une capture à taille réelle. Pour chaque question à visuels : une capture de la question telle qu'elle
s'affiche dans la page (bureau, et téléphone avec --mobile). Les captures se regardent ensuite : les contrôles ne voient
pas tout (un alignement raté, une maquette peu crédible).

Rien n'est publié ni modifié : une copie de la page (verif.html) et les captures vont dans verif/ à côté d'elle.
Code de sortie : 0 sans problème relevé, 1 avec, 2 sans navigateur ou sans page.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BUREAU = (1440, 900)
TELEPHONE = (390, 844)
ATTENTE_MS = 4000  # temps virtuel laissé à la page (polices, animations) avant de mesurer ou de capturer

# Injecté à la fin de la copie : mesure (#verif), isole un visuel à taille réelle (#vis=N) ou montre une question (#q=ID).
SCRIPT = r"""
<script>
(function () {
  var P = new URLSearchParams(location.hash.slice(1));
  if (P.get("mode")) document.documentElement.setAttribute("data-theme", P.get("mode"));
  function boites() { return Array.prototype.slice.call(document.querySelectorAll("article.q .vis-btn")); }
  function desc(el) {
    var t = (el.textContent || "").replace(/\s+/g, " ").trim().slice(0, 40);
    return el.localName + (el.classList && el.classList.length ? "." + Array.prototype.slice.call(el.classList).join(".") : "") + (t ? " « " + t + " »" : "");
  }
  function rgba(c) {
    var m = /rgba?\(([^)]+)\)/.exec(c || "");
    if (!m) return null;
    var p = m[1].split(/[\s,\/]+/).filter(Boolean).map(parseFloat);
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  }
  function lum(c) {
    function f(v) { v /= 255; return v <= .03928 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4); }
    return .2126 * f(c.r) + .7152 * f(c.g) + .0722 * f(c.b);
  }
  function mele(a, b) { return { r: a.r * a.a + b.r * (1 - a.a), g: a.g * a.a + b.g * (1 - a.a), b: a.b * a.a + b.b * (1 - a.a), a: 1 }; }
  function fondDe(el, hote, defaut) {
    var pile = [];
    for (var e = el; e; e = e.parentElement || (e.getRootNode && e.getRootNode().host) || null) {
      var cs = getComputedStyle(e);
      if (cs.backgroundImage && cs.backgroundImage !== "none") return null;  // dégradé ou image : pas de mesure fiable
      var c = rgba(cs.backgroundColor);
      if (c && c.a > 0) { pile.push(c); if (c.a >= 1) break; }
      if (e === hote) break;
    }
    var fond = defaut;
    for (var i = pile.length - 1; i >= 0; i--) fond = mele(pile[i], fond);
    return fond;
  }
  function visible(el) {
    var cs = getComputedStyle(el);
    return cs.display !== "none" && cs.visibility !== "hidden" && parseFloat(cs.opacity) > 0.05;
  }
  function textes(racine) {
    var out = [], w = document.createTreeWalker(racine, NodeFilter.SHOW_TEXT), n;
    while ((n = w.nextNode())) {
      if (!n.nodeValue.trim() || !n.parentElement || !visible(n.parentElement)) continue;
      if (/^(?:style|script|title)$/i.test(n.parentElement.localName)) continue;
      var r = document.createRange(); r.selectNodeContents(n);
      Array.prototype.slice.call(r.getClientRects()).forEach(function (x) { if (x.width > 1 && x.height > 1) out.push({ n: n, el: n.parentElement, r: x }); });
    }
    return out;
  }
  function scene(hote, w, h, defaut) {
    var R = hote.getBoundingClientRect(), sr = hote.shadowRoot, pb = [], tous = Array.prototype.slice.call(sr.querySelectorAll("*"));
    var deborde = [];
    tous.forEach(function (el) {
      if (/^(?:style|defs|title)$/i.test(el.localName) || !visible(el)) return;
      var r = el.getBoundingClientRect();
      if (r.width < 1 || r.height < 1) return;
      var d = Math.max(R.left - r.left, r.right - R.right, R.top - r.top, r.bottom - R.bottom);
      if (d > 2 && !deborde.some(function (x) { return x.el.contains(el); })) deborde.push({ el: el, d: d });
      var cs = getComputedStyle(el);
      var coupeX = cs.overflowX !== "visible" && el.scrollWidth > el.clientWidth + 1, coupeY = cs.overflowY !== "visible" && el.scrollHeight > el.clientHeight + 1;
      if ((coupeX || coupeY) && el.textContent.trim())
        pb.push({ type: cs.textOverflow === "ellipsis" ? "tronque" : "coupe", ou: desc(el), detail: (coupeX ? "largeur " + el.scrollWidth + " pour " + el.clientWidth : "") + (coupeX && coupeY ? ", " : "") + (coupeY ? "hauteur " + el.scrollHeight + " pour " + el.clientHeight : "") + " px" });
    });
    deborde.slice(0, 6).forEach(function (x) { pb.push({ type: "deborde", ou: desc(x.el), detail: "sort de la toile de " + Math.round(x.d) + " px" }); });
    var tx = textes(sr), vus = {}, petits = null;
    for (var i = 0; i < tx.length; i++) {
      var a = tx[i];
      var cs = getComputedStyle(a.el), fs = parseFloat(cs.fontSize);
      if (fs < 11 && (!petits || fs < petits.fs)) petits = { fs: fs, ou: desc(a.el) };
      if (!vus[i + "c"]) {
        var c = rgba(cs.color), f = fondDe(a.el, hote, defaut);
        if (c && f) {
          var t = mele(c, f), l1 = lum(t), l2 = lum(f), k = (Math.max(l1, l2) + .05) / (Math.min(l1, l2) + .05);
          var grand = fs >= 24 || fs >= 18.5 && parseInt(cs.fontWeight, 10) >= 700;
          if (k < (grand ? 3 : 4.5) && !pb.some(function (p) { return p.type === "contraste" && p.ou === desc(a.el); }))
            pb.push({ type: "contraste", ou: desc(a.el), detail: "contraste " + k.toFixed(1) + " (" + (grand ? 3 : 4.5) + " au moins)" });
        }
      }
      for (var j = i + 1; j < tx.length; j++) {
        var b = tx[j];
        if (a.el === b.el || a.el.contains(b.el) || b.el.contains(a.el)) continue;
        var ix = Math.min(a.r.right, b.r.right) - Math.max(a.r.left, b.r.left), iy = Math.min(a.r.bottom, b.r.bottom) - Math.max(a.r.top, b.r.top);
        if (ix <= 0 || iy <= 0) continue;
        var part = ix * iy / Math.min(a.r.width * a.r.height, b.r.width * b.r.height);
        if (part > .25 && pb.filter(function (p) { return p.type === "chevauche"; }).length < 4)
          pb.push({ type: "chevauche", ou: desc(a.el), detail: "sur " + desc(b.el) });
      }
    }
    if (petits) pb.push({ type: "petit", ou: petits.ou, detail: "texte de " + petits.fs + " px à taille réelle, illisible une fois réduit" });
    // Ce qui porte le contenu : les textes, les images et dessins, les blocs marqués qui ne sont pas un fond de toile.
    var bb = null, surface = false;
    function ajoute(r) {
      var l = Math.max(r.left, R.left), t = Math.max(r.top, R.top), rr = Math.min(r.right, R.right), bo = Math.min(r.bottom, R.bottom);
      if (rr <= l || bo <= t) return;
      bb = bb ? { l: Math.min(bb.l, l), t: Math.min(bb.t, t), r: Math.max(bb.r, rr), b: Math.max(bb.b, bo) } : { l: l, t: t, r: rr, b: bo };
    }
    tx.forEach(function (x) { ajoute(x.r); });
    tous.forEach(function (el) {
      if (!visible(el) || /^(?:style|defs|title)$/i.test(el.localName)) return;
      var r = el.getBoundingClientRect(), cs = getComputedStyle(el);
      if (r.width < 1 || r.height < 1) return;
      if (r.width * r.height > .85 * w * h) {
        // Un fond peint sur toute la toile : c'est la maquette elle-même (un écran, une carte), son vide est voulu.
        if ((rgba(cs.backgroundColor) || { a: 0 }).a > 0 || cs.backgroundImage !== "none") surface = true;
        return;
      }
      var marque = /^(?:img|svg|canvas|video|path|rect|circle|ellipse|line|polyline|polygon)$/i.test(el.localName) ||
        (rgba(cs.backgroundColor) || { a: 0 }).a > 0 || cs.backgroundImage !== "none" || parseFloat(cs.borderTopWidth) > 0 || parseFloat(cs.borderLeftWidth) > 0 || cs.boxShadow !== "none";
      if (marque) ajoute(r);
    });
    var hcs = getComputedStyle(hote);
    if ((rgba(hcs.backgroundColor) || { a: 0 }).a > 0 || hcs.backgroundImage !== "none") surface = true;
    if (!bb) pb.push({ type: "vide", ou: "toile", detail: "rien de visible sur la toile" });
    else {
      var cw = bb.r - bb.l, ch = bb.b - bb.t, part = cw * ch / (w * h);
      var vers = Math.round(cw + 48) + " x " + Math.round(ch + 48);
      if (surface ? part < .15 : cw < .55 * w || ch < .55 * h)
        pb.push({ type: "toile", ou: "toile " + w + " x " + h, detail: "le contenu n'en occupe que " + Math.round(cw) + " x " + Math.round(ch) +
          (surface ? " sur un fond plein : il sera minuscule en vignette, resserre la toile (vers " + vers + ") ou grossis le contenu"
                   : " : toile à la forme du contenu, vers " + vers) });
    }
    return pb;
  }
  function fichier(img, v) {
    var pb = [];
    if (!img.complete || !img.naturalWidth) pb.push({ type: "casse", ou: v.src, detail: "l'image ne se charge pas" });
    else if (!/\.svg$/i.test(v.src)) {
      var r1 = img.naturalWidth / img.naturalHeight, r2 = v.w / v.h;
      if (Math.abs(r1 - r2) / r2 > .02) pb.push({ type: "forme", ou: v.src, detail: "affichée " + img.naturalWidth + " x " + img.naturalHeight + ", place prévue " + v.w + " x " + v.h });
    }
    return pb;
  }
  function vis(b) { return b.vis || {}; }
  // Une copie à taille réelle, hors de la page : la scène dessinée (son arbre isolé recopié) ou l'image.
  function copie(b) {
    var v = vis(b), sc = b.querySelector(".vis-scene"), d = document.createElement("div");
    d.style.cssText = "position:relative;overflow:hidden;width:" + v.w + "px;height:" + v.h + "px;background:var(--field)";
    if (sc && sc.shadowRoot) {
      var hote = document.createElement("div");
      hote.style.cssText = "width:" + v.w + "px;height:" + v.h + "px";
      hote.attachShadow({ mode: "open" }).innerHTML = sc.shadowRoot.innerHTML;
      d.appendChild(hote);
    } else if (b.querySelector("img")) {
      var im = b.querySelector("img").cloneNode(true);
      im.removeAttribute("loading");
      im.style.cssText = "display:block;width:100%;height:100%;object-fit:contain" + (/\.svg$/i.test(v.src || "") ? ";background:#fff" : "");
      d.appendChild(im);
    }
    return d;
  }
  function seul(el) {
    Array.prototype.slice.call(document.body.children).forEach(function (c) { if (c.localName !== "script") c.style.display = "none"; });
    document.body.style.cssText = "margin:0;padding:0;background:var(--field)";
    document.body.appendChild(el);
  }
  function quand(f) {
    var fini = false;
    function go() { if (!fini) { fini = true; f(); } }
    (document.fonts && document.fonts.ready ? document.fonts.ready : Promise.resolve()).then(function () { setTimeout(go, 400); });
    setTimeout(go, 2500);
  }
  // Sans défilement (Chrome sans écran capture mal une page défilée) : la question seule en haut de la colonne, dans la
  // vraie mise en page (rail, largeurs, vignettes). Dès maintenant, pour que les images aient le temps d'arriver.
  function isoler() {
    var art = document.getElementById("q-" + P.get("q"));
    if (!art) return;
    Array.prototype.slice.call(document.querySelectorAll("article.q")).forEach(function (x) { if (x !== art) x.style.display = "none"; });
    Array.prototype.slice.call(document.querySelectorAll(".top, .group-h, .fin, .keys-hint, .precedent")).forEach(function (x) { if (!x.contains(art)) x.style.display = "none"; });
    Array.prototype.slice.call(document.querySelectorAll(".group")).forEach(function (g) { if (!g.contains(art)) g.style.display = "none"; else g.style.marginTop = "0"; });
    art.style.marginTop = "0";
    Array.prototype.slice.call(art.querySelectorAll("img")).forEach(function (im) { im.loading = "eager"; im.decoding = "sync"; });
    window.scrollTo(0, 0);
  }
  if (P.has("q")) isoler();
  quand(function () {
    var bs = boites();
    if (P.has("vis")) {
      var b = bs[+P.get("vis")];
      if (b) seul(copie(b));
      return;
    }
    if (P.has("q")) { isoler(); return; }
    if (!P.has("verif")) return;
    var defaut = rgba(getComputedStyle(document.body).backgroundColor) || { r: 255, g: 255, b: 255, a: 1 };
    var zone = document.createElement("div");
    zone.style.cssText = "position:absolute;left:0;top:0;z-index:99";
    document.body.appendChild(zone);
    var out = bs.map(function (b) {
      var v = vis(b), d = copie(b);
      zone.appendChild(d);
      var hote = d.firstChild;
      var f = rgba(getComputedStyle(d).backgroundColor) || defaut;
      try {
        if (b.querySelector(".vis-ko")) return { pb: [{ type: "casse", ou: v.src || "visuel", detail: "la page affiche « Visuel introuvable »" }] };
        if (hote && hote.shadowRoot) return { pb: scene(hote, v.w, v.h, f), theme: /var\(--/.test(hote.shadowRoot.innerHTML) };
        if (hote && hote.localName === "img") return { pb: fichier(b.querySelector("img"), v) };
        return { pb: [{ type: "vide", ou: "visuel", detail: "ni scène ni image dans la boîte" }] };
      } catch (e) { return { pb: [{ type: "erreur", ou: "mesure", detail: String(e) }] }; }
    });
    var pre = document.createElement("pre");
    pre.id = "verif-out";
    pre.textContent = JSON.stringify(out);
    document.body.appendChild(pre);
  });
})();
</script>
"""


# Chrome sans écran ne fait pas de fenêtre plus étroite qu'environ 500 px : la page en mode téléphone vit dans un cadre.
CADRE = """<!doctype html><meta charset="utf-8"><style>html,body{margin:0;background:#777}iframe{display:block;border:0}</style>
<iframe width="__L__" height="__H__"></iframe>
<script>document.querySelector("iframe").src = location.hash.slice(1);</script>"""


def navigateur():
    if os.environ.get("QUIZZ_CHROME"):
        return os.environ["QUIZZ_CHROME"]
    candidats = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ]
    for nom in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "brave-browser", "chrome"):
        if shutil.which(nom):
            candidats.append(shutil.which(nom))
    for base in ("~/Library/Caches/ms-playwright", "~/.cache/ms-playwright"):
        candidats += sorted(glob.glob(os.path.expanduser(base + "/chromium-*/chrome-*/Chromium.app/Contents/MacOS/Chromium")), reverse=True)
        candidats += sorted(glob.glob(os.path.expanduser(base + "/chromium-*/chrome-*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing")), reverse=True)
        candidats += sorted(glob.glob(os.path.expanduser(base + "/chromium-*/chrome-linux*/chrome")), reverse=True)
    return next((c for c in candidats if c and os.path.isfile(c) and os.access(c, os.X_OK)), None)


def chrome(exe, args, url):
    with tempfile.TemporaryDirectory(prefix="quizz-verif-") as profil:
        cmd = [exe, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run", "--no-default-browser-check",
               "--mute-audio", "--force-device-scale-factor=1", f"--user-data-dir={profil}",
               f"--virtual-time-budget={ATTENTE_MS}"] + args + [url]
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            return None


def visuels(data):
    """Dans l'ordre de la page : pour chaque question, ses visuels puis ceux de ses options."""
    out = []
    for q in data.get("questions") or []:
        v = q.get("visuel")
        liste = v if isinstance(v, list) else [v] if v else []
        for j, x in enumerate(liste, 1):
            out.append((q["id"], f"{q['id']}" + (f"-{j}" if len(liste) > 1 else ""), x))
        for o in q.get("options") or []:
            if o.get("visuel"):
                out.append((q["id"], f"{q['id']}-{o['k']}", o["visuel"]))
    return out


def main():
    args = sys.argv[1:]
    mobile = "--mobile" in args
    args = [a for a in args if a != "--mobile"]
    if len(args) != 1:
        print("usage : python3 verifie.py sortie/index.html [--mobile]", file=sys.stderr)
        sys.exit(2)
    page = Path(args[0]).resolve()
    if not page.is_file():
        print(f"verifie : {page} introuvable", file=sys.stderr)
        sys.exit(2)
    html_ = page.read_text(encoding="utf-8")
    m = re.search(r'<script id="quiz-data" type="application/json">(.*?)</script>', html_, re.DOTALL)
    if not m:
        print("verifie : pas de données de quiz dans la page (construis-la d'abord avec build.py)", file=sys.stderr)
        sys.exit(2)
    data = json.loads(m.group(1))
    vs = visuels(data)
    if not vs:
        print("aucun visuel dans ce quiz : rien à vérifier")
        return
    exe = navigateur()
    if not exe:
        print("verifie : aucun Chrome ou Chromium trouvé (QUIZZ_CHROME=chemin pour en donner un). Sans navigateur, "
              "rends les visuels autrement (Playwright si tu l'as) ou relis leur code avec soin.", file=sys.stderr)
        sys.exit(2)

    copie = page.with_name("verif.html")
    copie.write_text(html_ + SCRIPT, encoding="utf-8")
    cadre = page.with_name("verif-telephone.html")
    cadre.write_text(CADRE.replace("__L__", str(TELEPHONE[0])).replace("__H__", str(TELEPHONE[1])), encoding="utf-8")
    dossier = page.parent / "verif"
    if dossier.is_dir():
        for f in dossier.glob("*.png"):
            f.unlink()
    dossier.mkdir(exist_ok=True)
    url = copie.as_uri()
    # Deux modes quand le thème en a deux : un visuel qui suit le thème se regarde dans chacun.
    modes = ["dark", "light"] if "@media (prefers-color-scheme" in html_ else [None]

    r = chrome(exe, ["--dump-dom", f"--window-size={BUREAU[0]},{BUREAU[1]}"], url + "#verif")
    mesure = re.search(r'<pre id="verif-out">(.*?)</pre>', r.stdout if r else "", re.DOTALL)
    if not mesure:
        print("verifie : la mesure n'a rien rendu (page cassée ?)" + (f"\n{r.stderr[-800:]}" if r and r.stderr else ""), file=sys.stderr)
        sys.exit(2)
    resultats = json.loads(mesure.group(1).replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&amp;", "&"))
    if len(resultats) != len(vs):
        print(f"verifie : {len(resultats)} visuels dans la page pour {len(vs)} dans les données", file=sys.stderr)

    travaux = []
    for i, (qid, nom, v) in enumerate(vs):
        w, h = v.get("w", 640), v.get("h", 400)
        res = resultats[i] if i < len(resultats) else {}
        for mode in (modes if res.get("theme") else modes[:1]):
            suffixe = f"-{'sombre' if mode == 'dark' else 'clair'}" if mode and len(modes) > 1 and res.get("theme") else ""
            frag = f"#vis={i}" + (f"&mode={mode}" if mode else "")
            travaux.append((dossier / f"visuel-{nom}{suffixe}.png", (w, h), frag))
    for qid in dict.fromkeys(q for q, _, _ in vs):
        travaux.append((dossier / f"question-{qid}-bureau.png", BUREAU, f"#q={qid}"))
        if mobile:
            travaux.append((dossier / f"question-{qid}-telephone.png", (max(TELEPHONE[0], 520), TELEPHONE[1]), f"#q={qid}", cadre))

    def capture(t):
        chemin, (w, h), frag = t[:3]
        cible = (t[3].as_uri() + "#" + copie.name + frag) if len(t) > 3 else url + frag
        chrome(exe, [f"--screenshot={chemin}", f"--window-size={w},{h}"], cible)
        return chemin if chemin.is_file() else None

    with ThreadPoolExecutor(max_workers=4) as pool:
        faites = list(pool.map(capture, travaux))

    n = 0
    for i, (qid, nom, v) in enumerate(vs):
        pb = (resultats[i] if i < len(resultats) else {}).get("pb", [])
        n += len(pb)
        print(f"{nom} ({v.get('w')} x {v.get('h')}) : " + ("rien relevé" if not pb else f"{len(pb)} problème(s)"))
        for p in pb:
            print(f"  {p['type']} : {p['ou']} : {p['detail']}")
    ok = [str(c) for c in faites if c]
    print(f"\ncaptures à regarder ({len(ok)}) :")
    for c in ok:
        print(f"  {c}")
    if len(ok) < len(travaux):
        print(f"  {len(travaux) - len(ok)} capture(s) ratée(s)")
    print("\nLes contrôles ne voient pas tout : regarde chaque capture (alignements, crédibilité, rien de bizarre), "
          "corrige le JSON, reconstruis, revérifie.")
    sys.exit(1 if n else 0)


if __name__ == "__main__":
    main()
