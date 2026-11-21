#!/usr/bin/env python3
"""Remplit template.html avec un fichier de questions et vérifie les données avant.

Usage : python3 build.py questions.json sortie/index.html [--theme <nom|chemin>]
        python3 build.py --apercu sortie/apercu.html [thème ...]

Thème : --theme, sinon le champ "theme" du quiz, sinon ~/.claude/quizz-theme.json, sinon ardoise. Les thèmes
livrés sont dans themes/ ; un thème perso part d'une base et ne donne que ce qui change. Les couleurs trop peu
contrastées sont corrigées ici (juste assez, teinte gardée) et chaque correction est affichée.

Le remplacement se fait ici plutôt qu'avec sed : un « & » ou un « / » dans le texte ne casse
rien, le nom est échappé pour <title>, et chaque « < » du JSON devient \\u003c pour ne jamais
fermer la balise <script> qui le contient.
"""
import colorsys
import hashlib
import html
import json
import math
import re
import struct
import sys
from html.parser import HTMLParser
from pathlib import Path

SEGMENT = re.compile(r"^[A-Za-z0-9_.~:@+-]{1,60}$")
TYPES = ("choix", "multi", "texte")
FORMATS = ("slack", "markdown", "texte")
CONTEXTE_MAX = 12000  # contexte global de Creuse, en caractères
FOND_MAX = 8000  # fond d'une question
POIDS = ("leger", "moyen", "lourd")  # poids d'un « implique » d'option
IMPLIQUE_MAX = 400
# Une durée chiffrée (« 2 jours », « 30 min ») : jamais dans un « implique », qui ne dit que ce que le code montre.
# Une estimation d'effort (jours, semaines, sprints...), pas une valeur factuelle comme « un délai de 12 s ».
DUREE = re.compile(r"\d+(?:[.,]\d+)?\s*(?:j|jours?|sem|semaines?|sprints?|days?|weeks?|jours?-homme|heures? de (?:travail|dev))\b",
                   re.IGNORECASE)
VISUELS_PAR_QUESTION = 4
VISUEL_ALT_MAX = 600
VISUEL_LEGENDE_MAX = 240
VISUEL_CODE_MAX = 20000  # html + css d'un visuel dessiné, en caractères : ça part dans la page et dans Creuse
VISUEL_COTE_MAX = 100000  # côté lu dans un fichier : au-delà, le fichier est hostile ou abîmé
VISUEL_TOILE_BORNES = (80, 2400)
# Limites de publication d'un artefact : 15 Mo par fichier, 64 Mo et 255 fichiers par publication (la page en est un).
IMAGE_OCTETS_MAX = 15 * 1024 * 1024
IMAGES_OCTETS_MAX = 64 * 1024 * 1024
IMAGES_NOMBRE_MAX = 254
IMAGE_LOURDE = 3 * 1024 * 1024  # au-delà, le build le signale : la page charge lentement

# Un visuel dessiné est une image vivante : ni script, ni élément qui charge ou embarque autre chose, et rien
# d'extérieur (une page publiée n'a pas de réseau). Refusé ici pour donner une erreur claire plutôt qu'un rendu cassé.
# Ce n'est pas la barrière de sécurité : html.parser ne découpe pas le HTML comme un navigateur. La barrière est
# visuelPropre dans le gabarit, qui filtre l'arbre réellement analysé.
BALISES_INTERDITES = {"script", "iframe", "frame", "frameset", "object", "embed", "applet", "link", "meta", "base",
                      "html", "head", "body", "title", "noscript", "template", "slot"}
ATTRS_URL = {"src", "href", "xlink:href", "poster", "action", "formaction", "data", "background", "ping"}
URL_PERMISE = re.compile(r"^\s*(?:#|data:image/|$)", re.IGNORECASE)
CSS_URL = re.compile(r"""url\(\s*(?:"([^"]*)"|'([^']*)'|([^)\s]*))""", re.IGNORECASE)
CSS_INTERDIT = re.compile(r"@import|image-set\(|(?<![\w-])src\(", re.IGNORECASE)
CSS_ECHAPPE = re.compile(r"\\([0-9a-fA-F]{1,6})\s?|\\(.)")
CSS_RACINE = re.compile(r"(?<![\w.#-])(?:html|body)\b(?=[^{}]*\{)|:root\b", re.IGNORECASE)


def css_lisible(css):
    """Le CSS tel que le navigateur le lit : u\\72l( vaut url(, et les commentaires ne comptent pas."""
    def un(m):
        if m.group(2):
            return m.group(2)
        n = int(m.group(1), 16)
        return chr(n) if 0 < n <= 0x10FFFF else ""
    return CSS_ECHAPPE.sub(un, re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL))


def erreurs_css(css):
    err = []
    css = css_lisible(css)
    if CSS_INTERDIT.search(css):
        err.append("@import, image-set() et src() sont refusés : une page publiée ne charge rien d'ailleurs")
    for m in CSS_URL.finditer(css):
        cible = next((g for g in m.groups() if g is not None), "")
        if not URL_PERMISE.match(cible):
            err.append(f"url({cible[:60]}) : seules les data:image et les ancres # passent, une page publiée ne charge rien d'ailleurs")
            break
    if CSS_RACINE.search(css):
        err.append("sélecteur html, body ou :root : le visuel a son propre arbre, ils n'y atteignent rien ; utilise :host ou une classe")
    return err


class LectureVisuel(HTMLParser):
    """Relève ce qu'un visuel dessiné n'a pas le droit de contenir."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.erreurs, self.pile = [], []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in BALISES_INTERDITES:
            self.erreurs.append(f"balise <{tag}> interdite : un visuel est une image vivante, sans script ni contenu extérieur")
        for nom, val in attrs:
            nom = nom.lower()
            if nom.startswith("on"):
                self.erreurs.append(f"attribut {nom} interdit : pas de script dans un visuel")
            elif nom == "srcset":
                self.erreurs.append("srcset refusé : un seul src suffit à un visuel")
            elif nom in ATTRS_URL and not URL_PERMISE.match(val or ""):
                self.erreurs.append(f"{nom}={(val or '')[:60]!r} : seules les data:image et les ancres # passent")
            elif "url(" in (val or "").lower() or nom == "style":
                self.erreurs += [e for e in erreurs_css(val or "") if not e.startswith("sélecteur")]
        self.pile.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.pile.pop()

    def handle_endtag(self, tag):
        if tag.lower() in self.pile:
            while self.pile.pop() != tag.lower():
                pass

    def handle_data(self, data):
        if self.pile and self.pile[-1] == "style":
            self.erreurs += erreurs_css(data)


def check_visuel(v, where, errors):
    """Un visuel : dessiné {"html", "css"?, "largeur"?, "hauteur"?} ou fichier {"src"}, avec "alt" et "legende"?.
    alt est obligatoire : c'est le texte de secours, et Claude n'a rien d'autre quand il ne peut pas regarder."""
    if not isinstance(v, dict) or set(v) - {"html", "css", "largeur", "hauteur", "src", "alt", "legende"}:
        errors.append(f"{where} : visuel attendu sous la forme {{\"html\": \"<div>...</div>\", \"css\": \"...\", \"alt\": \"ce qu'on y voit\"}} "
                      "ou {\"src\": \"capture.png\", \"alt\": \"ce qu'on y voit\"}")
        return
    alt = v.get("alt")
    if not isinstance(alt, str) or not alt.strip():
        errors.append(f"{where} : visuel sans alt (ce qu'on y voit, concrètement : texte de secours et description pour Claude)")
    elif len(alt) > VISUEL_ALT_MAX:
        errors.append(f"{where} : alt trop long ({len(alt)} caractères, {VISUEL_ALT_MAX} au plus)")
    leg = v.get("legende")
    if leg is not None and (not isinstance(leg, str) or not leg.strip()):
        errors.append(f"{where} : legende : texte non vide attendu (ou retire le champ)")
    elif leg is not None and len(leg) > VISUEL_LEGENDE_MAX:
        errors.append(f"{where} : legende trop longue ({len(leg)} caractères, {VISUEL_LEGENDE_MAX} au plus)")
    if ("html" in v) == ("src" in v):
        errors.append(f"{where} : un visuel a soit html (dessiné), soit src (fichier), pas les deux")
        return
    if "src" in v:
        if set(v) & {"css", "largeur", "hauteur"}:
            errors.append(f"{where} : css, largeur et hauteur ne valent que pour un visuel dessiné (html)")
        src = v["src"]
        if not isinstance(src, str) or not src.strip():
            errors.append(f"{where} : src : chemin du fichier attendu, absolu ou relatif au JSON")
        elif re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", src) or src.startswith("//"):
            errors.append(f"{where} : src {src[:60]!r} : un fichier local est attendu, pas une URL (une page publiée ne charge "
                          "rien d'ailleurs) ; télécharge-le d'abord, ou dessine le visuel en html")
        return
    code, css = v["html"], v.get("css", "")
    if not isinstance(code, str) or not code.strip():
        errors.append(f"{where} : html : code du visuel attendu, non vide")
        return
    if not isinstance(css, str):
        errors.append(f"{where} : css : texte attendu")
        return
    if len(code) + len(css) > VISUEL_CODE_MAX:
        errors.append(f"{where} : visuel trop long ({len(code) + len(css)} caractères de html et css, {VISUEL_CODE_MAX} au plus)")
    # Pas de toile par défaut : une valeur imposée faisait tout dessiner en paysage. La forme suit ce qu'on montre.
    for k in ("largeur", "hauteur"):
        if k not in v:
            errors.append(f"{where} : {k} manquante : choisis la toile selon ce que tu montres (écran de téléphone 390 x 844, "
                          "carte carrée 480 x 480, page de bureau 1280 x 800, bouton seul 360 x 160...), pas une taille par habitude")
        elif (isinstance(v[k], bool) or not isinstance(v[k], int)
              or not VISUEL_TOILE_BORNES[0] <= v[k] <= VISUEL_TOILE_BORNES[1]):
            errors.append(f"{where} : {k} : nombre entier de {VISUEL_TOILE_BORNES[0]} à {VISUEL_TOILE_BORNES[1]} (px de la toile)")
    if "<![" in code or "<?" in code:
        errors.append(f"{where} : visuel : <![ et <? sont refusés (CDATA, instructions) : écris du HTML simple")
        return
    if re.search(r"&(?:mdash|#0*8212|#x0*2014);?", code, re.IGNORECASE) or re.search(r"\\0*2014", code + css):
        errors.append(f"{where} : visuel : tiret cadratin encodé (entité ou \\2014), le remplacer par un tiret simple ou reformuler")
    lecture = LectureVisuel()
    try:
        lecture.feed(code)
        lecture.close()
    except (AssertionError, NotImplementedError, ValueError):
        errors.append(f"{where} : visuel : html illisible, écris du HTML simple")
        return
    for e in dict.fromkeys(lecture.erreurs + erreurs_css(css)):
        errors.append(f"{where} : visuel : {e}")


def visuels_du_quiz(data):
    """Chaque visuel du quiz, avec où il est : [(où, visuel)]. Seulement les objets, la forme a été vérifiée avant."""
    out = []
    for q in data.get("questions") or []:
        if not isinstance(q, dict):
            continue
        v = q.get("visuel")
        for x in v if isinstance(v, list) else [v] if v is not None else []:
            if isinstance(x, dict):
                out.append((f"question {q.get('id', '?')}", x))
        for o in q.get("options") or [] if isinstance(q.get("options"), list) else []:
            if isinstance(o, dict) and isinstance(o.get("visuel"), dict):
                out.append((f"question {q.get('id', '?')}, option {o.get('k', '?')}", o["visuel"]))
    return out


def dimensions_svg(octets):
    texte = octets.decode("utf-8", "replace")
    racine = re.search(r"<svg\b[^>]*>", texte, re.IGNORECASE)
    if not racine:
        return None
    vb = re.search(r"""(?<![\w:-])viewBox\s*=\s*["']\s*[-\d.]+[\s,]+[-\d.]+[\s,]+([\d.]+)[\s,]+([\d.]+)""", racine.group(0), re.IGNORECASE)
    if vb:
        return float(vb.group(1)), float(vb.group(2))
    w = re.search(r"""(?<![\w:-])width\s*=\s*["']\s*([\d.]+)(?:px)?\s*["']""", racine.group(0), re.IGNORECASE)
    h = re.search(r"""(?<![\w:-])height\s*=\s*["']\s*([\d.]+)(?:px)?\s*["']""", racine.group(0), re.IGNORECASE)
    return (float(w.group(1)), float(h.group(1))) if w and h else None


def orientation_jpeg(octets):
    """Orientation EXIF d'un JPEG (1 à 8), 1 sans EXIF lisible."""
    i = 2
    while i + 4 < len(octets) and octets[i] == 0xFF:
        m = octets[i + 1]
        n = struct.unpack(">H", octets[i + 2:i + 4])[0]
        if m == 0xDA:
            break
        if m == 0xE1 and octets[i + 4:i + 10] == b"Exif\x00\x00":
            t = octets[i + 10:i + 2 + n]
            if t[:2] not in (b"II", b"MM"):
                return 1
            e = "<" if t[:2] == b"II" else ">"
            ifd = struct.unpack(e + "I", t[4:8])[0]
            for j in range(struct.unpack(e + "H", t[ifd:ifd + 2])[0]):
                a = ifd + 2 + 12 * j
                if struct.unpack(e + "H", t[a:a + 2])[0] == 0x0112:
                    return struct.unpack(e + "H", t[a + 8:a + 10])[0]
            return 1
        i += 2 + n
    return 1


def format_image(octets, nom):
    """(extension, largeur, hauteur) lus dans le fichier lui-même, pas dans son nom : une capture mal nommée passe,
    un autre format ou un en-tête illisible ne passe pas. None sinon. Seul l'en-tête est lu : un fichier coupé plus loin
    passe ici, et la page dit alors « Visuel introuvable »."""
    try:
        if octets[:8] == b"\x89PNG\r\n\x1a\n":
            w, h = struct.unpack(">II", octets[16:24])
            return "png", w, h
        if octets[:6] in (b"GIF87a", b"GIF89a"):
            w, h = struct.unpack("<HH", octets[6:10])
            return "gif", w, h
        if octets[:2] == b"\xff\xd8":
            # Une photo de téléphone est souvent stockée couchée, avec une orientation EXIF que le navigateur applique :
            # sans l'échange, la place réservée aurait la forme inverse de l'image affichée.
            tourne = orientation_jpeg(octets) in (5, 6, 7, 8)
            i = 2
            while i + 9 < len(octets):
                if octets[i] != 0xFF:
                    i += 1
                    continue
                m = octets[i + 1]
                if m == 0xFF:
                    i += 1
                elif m == 0xD8 or m == 0x01 or 0xD0 <= m <= 0xD7:
                    i += 2
                elif 0xC0 <= m <= 0xCF and m not in (0xC4, 0xC8, 0xCC):
                    h, w = struct.unpack(">HH", octets[i + 5:i + 9])
                    return ("jpg", h, w) if tourne else ("jpg", w, h)
                else:
                    i += 2 + struct.unpack(">H", octets[i + 2:i + 4])[0]
            return None
        if octets[:4] == b"RIFF" and octets[8:12] == b"WEBP":
            bloc = octets[12:16]
            if bloc == b"VP8 ":
                w, h = struct.unpack("<HH", octets[26:30])
                return "webp", w & 0x3FFF, h & 0x3FFF
            if bloc == b"VP8L" and len(octets) >= 25:
                b = int.from_bytes(octets[21:25], "little")
                return "webp", (b & 0x3FFF) + 1, ((b >> 14) & 0x3FFF) + 1
            if bloc == b"VP8X" and len(octets) >= 30:
                return "webp", int.from_bytes(octets[24:27], "little") + 1, int.from_bytes(octets[27:30], "little") + 1
            return None
        if nom.lower().endswith(".svg"):
            d = dimensions_svg(octets)
            return ("svg", d[0], d[1]) if d else None
    except (struct.error, ValueError, IndexError):
        return None
    return None


def preparer_images(data, racine, erreurs):
    """Complète chaque visuel : w et h (toile d'un dessiné, taille lue dans le fichier sinon) réservent sa place avant
    chargement. Un fichier est vérifié et src devient images/<empreinte>.<ext> : le nom neutre ne dit rien du contenu
    (comparaison à l'aveugle), une image répétée n'est publiée qu'une fois et une nouvelle version change d'URL.
    Rend {chemin publié: octets}."""
    fichiers, reperes = {}, []
    for ou, im in visuels_du_quiz(data):
        if isinstance(im.get("html"), str):
            im["w"], im["h"] = im.pop("largeur"), im.pop("hauteur")
            continue
        src = im.get("src")
        if not isinstance(src, str) or not src.strip() or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", src) or src.startswith("//"):
            continue  # déjà signalé par check_visuel
        try:
            chemin = Path(src).expanduser()
            if not chemin.is_absolute():
                chemin = racine / chemin
            octets = chemin.read_bytes()
        except (OSError, RuntimeError, ValueError) as e:
            erreurs.append(f"{ou} : image {src!r} illisible ({getattr(e, 'strerror', None) or e})")
            continue
        fmt = format_image(octets, chemin.name)
        if not fmt or not all(math.isfinite(c) and 0 < c <= VISUEL_COTE_MAX for c in fmt[1:]):
            erreurs.append(f"{ou} : image {src!r} : format non reconnu ou fichier abîmé (PNG, JPEG, GIF, WebP, ou SVG avec "
                           "viewBox ; un HEIC se convertit d'abord, par exemple avec sips -s format jpeg)")
            continue
        if len(octets) > IMAGE_OCTETS_MAX:
            erreurs.append(f"{ou} : image {src!r} trop lourde ({len(octets) / 1048576:.1f} Mo, "
                           f"{IMAGE_OCTETS_MAX // 1048576} Mo au plus) : réduis-la d'abord")
            continue
        publie = f"images/{hashlib.sha256(octets).hexdigest()[:16]}.{fmt[0]}"
        fichiers[publie] = octets
        reperes.append((im, publie, fmt[1], fmt[2]))
    total = sum(len(o) for o in fichiers.values())
    if total > IMAGES_OCTETS_MAX:
        erreurs.append(f"images : {total / 1048576:.1f} Mo au total, {IMAGES_OCTETS_MAX // 1048576} Mo au plus par publication")
    if len(fichiers) > IMAGES_NOMBRE_MAX:
        erreurs.append(f"images : {len(fichiers)} fichiers, {IMAGES_NOMBRE_MAX} au plus par publication")
    for im, publie, w, h in reperes:
        im["src"], im["w"], im["h"] = publie, w, h
    return fichiers


def check_implique(o, where, errors):
    """« implique » d'une option : {"poids": "leger" | "moyen" | "lourd", "texte": une phrase concrète}. Écrit depuis le
    code, seulement quand il y a quelque chose à dire ; jamais de durée ni de chiffre inventé."""
    if "implique" not in o:
        return
    imp = o["implique"]
    w = f"{where}, option {o.get('k', '?')} : implique"
    if not isinstance(imp, dict) or set(imp) - {"poids", "texte"}:
        errors.append(f"{w} attendu sous la forme {{\"poids\": \"leger|moyen|lourd\", \"texte\": \"...\"}}")
        return
    if imp.get("poids") not in POIDS:
        errors.append(f"{w} : poids {imp.get('poids')!r}, attendu {', '.join(POIDS)}")
    t = imp.get("texte")
    if not isinstance(t, str) or not t.strip():
        errors.append(f"{w} : texte non vide attendu (ou retire le champ quand il n'y a rien à dire)")
    elif len(t) > IMPLIQUE_MAX:
        errors.append(f"{w} : texte trop long ({len(t)} caractères, {IMPLIQUE_MAX} au plus)")
    elif "\u2014" in t:
        errors.append(f"{w} : tiret cadratin (U+2014), le remplacer par un tiret simple ou reformuler")
    elif DUREE.search(t):
        errors.append(f"{w} : durée chiffrée ({DUREE.search(t).group(0)!r}) : dis ce que le code demande, sans estimer de durée")


def check_si(q, where, avant, bloquantes, errors):
    """« si » : {id: clé | [clés]}, chaque id une question précédente de type choix ou multi.

    Une bloquante conditionnelle exige des parents bloquants : en mode « Juste les bloquantes », un parent
    non bloquant est caché, donc jamais répondu, et la bloquante disparaîtrait avec lui comme « sans objet ».
    """
    if "si" not in q:
        return
    si = q["si"]
    if not isinstance(si, dict) or not si:
        errors.append(f"{where} : si attendu sous la forme {{\"Q2\": \"b\"}} ou {{\"Q2\": [\"b\", \"c\"]}}")
        return
    if q.get("cadrage"):
        errors.append(f"{where} : la question de cadrage ne peut pas être conditionnelle")
    for ref, want in si.items():
        if ref not in avant:
            errors.append(f"{where} : si vise {ref!r}, qui n'est pas une question choix ou multi précédente")
            continue
        ks = want if isinstance(want, list) else [want]
        if not ks or any(not isinstance(k, str) for k in ks):
            errors.append(f"{where} : si[{ref!r}] attend une clé ou une liste de clés")
            continue
        inconnues = [k for k in ks if k not in avant[ref][1]]
        if inconnues:
            errors.append(f"{where} : si[{ref!r}] : clé(s) inconnue(s) {', '.join(inconnues)}")
        if q.get("bloquant") is True and ref not in bloquantes:
            errors.append(f"{where} : bloquante, mais dépend de {ref}, qui ne l'est pas ; marque {ref} \"bloquant\": true "
                          "(sinon le mode « Juste les bloquantes » la cache avec son parent) ou retire bloquant ici")


def check_prediction(q, where, kind, keys, errors):
    """« prediction » : une clé (choix) ou une liste de clés distinctes (multi), jamais toi."""
    if "prediction" not in q:
        return
    p = q["prediction"]
    if kind == "choix":
        if not isinstance(p, str) or p not in keys:
            errors.append(f"{where} : prediction doit être une clé d'option existante (pas toi)")
    elif (not isinstance(p, list) or not p or any(not isinstance(k, str) or k not in keys for k in p)
          or len(set(p)) != len(p)):
        errors.append(f"{where} : prediction d'un multi : liste de clés existantes, sans doublon")


def check(data):
    errors = []
    for key in ("nom", "titre", "questions"):
        if not data.get(key):
            errors.append(f"champ manquant : {key}")
    for key in ("nom", "titre", "eyebrow", "intro"):
        if key in data and not isinstance(data[key], str):
            errors.append(f"{key} : texte attendu")
    if "equipe" in data and not isinstance(data["equipe"], bool):
        errors.append("equipe : true (quiz à plusieurs) ou false ; sans le champ, le quiz est solo")
    if "theme" in data and not (isinstance(data["theme"], str) and data["theme"].strip()):
        errors.append("theme : nom d'un thème livré ou chemin vers un fichier de thème attendu")
    seul = data.get("seul")
    if seul is not None and not (isinstance(seul, list) and all(isinstance(t, str) and t for t in seul)):
        errors.append("seul : liste de phrases attendue")
    if "questions" in data and not isinstance(data["questions"], list):
        errors.append("questions : liste attendue")
        data["questions"] = []
    tour = data.setdefault("tour", "t1")
    if not isinstance(tour, str) or not SEGMENT.match(tour) or tour in (".", ".."):
        errors.append(f"tour invalide : {tour!r} (lettres, chiffres, _ - . ~ : @ +)")

    ctx = data.get("contexte")
    if ctx is not None:
        if not isinstance(ctx, str) or not ctx.strip():
            errors.append("contexte : texte non vide attendu (le contexte de fond que Creuse transmet à Claude), ou retire le champ")
        elif len(ctx) > CONTEXTE_MAX:
            errors.append(f"contexte trop long ({len(ctx)} caractères, {CONTEXTE_MAX} au plus) : garde l'essentiel")

    seen = set()
    avant = {}  # id -> (type, clés possibles) des questions déjà vues, pour « si »
    bloquantes = set()  # ids des questions bloquantes déjà vues
    for i, q in enumerate(data.get("questions") or [], 1):
        if not isinstance(q, dict):
            errors.append(f"question {i} : objet attendu")
            continue
        where = f"question {i} ({q.get('id', 'sans id')})"
        qid = q.get("id")
        if not isinstance(qid, str) or not SEGMENT.match(qid):
            errors.append(f"{where} : id manquant ou invalide")
        elif qid in seen:
            errors.append(f"{where} : id en double")
        seen.add(qid)
        kind = q.setdefault("type", "choix")
        if kind not in TYPES:
            errors.append(f"{where} : type {kind!r}, attendu {', '.join(TYPES)}")
        if not q.get("titre"):
            errors.append(f"{where} : titre manquant")
        if "bloquant" in q and not isinstance(q["bloquant"], bool):
            errors.append(f"{where} : bloquant vaut true ou false")
        if "fond" in q:
            # Contexte détaillé pour Creuse : seul Claude (côté page) le lit, la question ne l'affiche pas.
            fond = q["fond"]
            if not isinstance(fond, str) or not fond.strip():
                errors.append(f"{where} : fond attendu sous forme de texte non vide (ou retire le champ)")
            elif len(fond) > FOND_MAX:
                errors.append(f"{where} : fond trop long ({len(fond)} caractères, {FOND_MAX} au plus)")
            elif q.get("cadrage"):
                errors.append(f"{where} : pas de fond sur le cadrage (Creuse n'y est pas proposé)")
        if "image" in q:
            errors.append(f"{where} : image s'appelle maintenant visuel : {{\"src\": \"capture.png\", \"alt\": \"ce qu'on y voit\"}}")
        if "visuel" in q:
            vs = q["visuel"] if isinstance(q["visuel"], list) else [q["visuel"]]
            if not vs or len(vs) > VISUELS_PAR_QUESTION:
                errors.append(f"{where} : visuel : un seul, ou une liste de 1 à {VISUELS_PAR_QUESTION}")
            for v in vs:
                check_visuel(v, where, errors)
        check_si(q, where, avant, bloquantes, errors)
        # « implique » vit sur une option de choix ou de multi : ni sur la question, ni sur une question texte ou de cadrage.
        if "implique" in q:
            errors.append(f"{where} : implique se met sur une option (choix ou multi), pas sur la question")
        if (q.get("cadrage") or kind == "texte") and isinstance(q.get("options"), list) and any(
                isinstance(o, dict) and "implique" in o for o in q["options"]):
            errors.append(f"{where} : pas d'implique sur une question {'de cadrage' if q.get('cadrage') else 'texte'}")
        if (q.get("cadrage") or kind == "texte") and isinstance(q.get("options"), list) and any(
                isinstance(o, dict) and "visuel" in o for o in q["options"]):
            errors.append(f"{where} : pas de visuel d'option sur une question {'de cadrage' if q.get('cadrage') else 'texte'} "
                          "(mets-le sur la question)")
        if q.get("bloquant") is True and isinstance(qid, str):
            bloquantes.add(qid)
        if q.get("cadrage"):
            # Les trois options du cadrage sont fixes, ajoutées par la page.
            if i != 1:
                errors.append(f"{where} : la question de cadrage doit être la première")
            if kind != "choix" or q.get("options"):
                errors.append(f"{where} : une question de cadrage n'a ni type ni options (la page les ajoute)")
            if not q.get("contexte"):
                errors.append(f"{where} : cadrage sans contexte (ce que tu as compris, en deux ou trois phrases)")
            if "prediction" in q:
                errors.append(f"{where} : pas de prédiction sur la question de cadrage")
            if isinstance(qid, str):
                avant[qid] = ("choix", {"a", "b"})
                bloquantes.add(qid)  # toujours visible, même en mode « Juste les bloquantes »
            continue
        if kind in ("choix", "multi"):
            opts = q.get("options") or []
            if not isinstance(opts, list):
                errors.append(f"{where} : options attendues sous forme de liste [{{\"k\": \"a\", \"texte\": ...}}]")
                opts = []
            elif not 2 <= len(opts) <= 8:
                errors.append(f"{where} : 2 à 8 options (« À toi de voir » est ajouté tout seul)")
            for j, o in enumerate(opts, 1):
                if not isinstance(o, dict):
                    errors.append(f"{where} : option {j} : objet {{\"k\": \"a\", \"texte\": ...}} attendu")
                else:
                    check_implique(o, where, errors)
                    if "visuel" in o:
                        if isinstance(o["visuel"], list):
                            errors.append(f"{where}, option {o.get('k', '?')} : un seul visuel par option")
                        else:
                            check_visuel(o["visuel"], f"{where}, option {o.get('k', '?')}", errors)
            opts = [o for o in opts if isinstance(o, dict)]
            keys = [o.get("k") for o in opts]
            if len(set(keys)) != len(keys) or any(not isinstance(k, str) or not k or k == "toi" for k in keys):
                errors.append(f"{where} : clés d'option manquantes, en double ou réservées (toi)")
            elif keys != list("abcdefgh"[:len(keys)]):
                errors.append(f"{where} : clés d'option a, b, c... dans l'ordre (la page affiche et lit ces lettres)")
            if any(not o.get("texte") for o in opts):
                errors.append(f"{where} : une option n'a pas de texte")
            if kind == "choix" and sum(bool(o.get("reco")) for o in opts) > 1:
                errors.append(f"{where} : une seule reco pour un choix simple")
            valides = {k for k in keys if isinstance(k, str)}
            check_prediction(q, where, kind, valides, errors)
            if kind == "choix" and q.get("delegable") is not False:
                valides = valides | {"toi"}
            if isinstance(qid, str):
                avant[qid] = (kind, valides)
        elif "prediction" in q:
            errors.append(f"{where} : pas de prédiction sur une question texte")

    msgs = data.get("messages") or []
    if not isinstance(msgs, list):
        errors.append("messages : une liste attendue")
        msgs = []
    seen_m = set()
    for i, m in enumerate(msgs, 1):
        if not isinstance(m, dict):
            errors.append(f"message {i} : objet {{\"id\", \"pour\", \"texte\", \"format\"}} attendu")
            continue
        where = f"message {i} ({m.get('id', 'sans id')})"
        mid = m.get("id")
        if not isinstance(mid, str) or not SEGMENT.match(mid):
            errors.append(f"{where} : id manquant ou invalide")
        elif mid in seen_m:
            errors.append(f"{where} : id en double")
        seen_m.add(mid)
        if not m.get("pour"):
            errors.append(f"{where} : destinataire (pour) manquant")
        if not m.get("texte"):
            errors.append(f"{where} : texte manquant")
        fmt = m.setdefault("format", "texte")
        if fmt not in FORMATS:
            errors.append(f"{where} : format {fmt!r}, attendu {', '.join(FORMATS)}")
        lien = m.get("lien")
        if lien is not None and not (isinstance(lien, str) and re.match(r"^https?://", lien)):
            errors.append(f"{where} : lien http(s) attendu")

    rec = data.get("recadre")
    if rec is not None and not (isinstance(rec, dict) and isinstance(rec.get("le"), str) and rec["le"]
                                and isinstance(rec.get("resume"), str) and rec["resume"]):
        errors.append("recadre : {\"le\": <le de la demande, recopié tel quel>, \"resume\": <une ou deux phrases>} attendu")

    # Tour suivant après « Approfondir » : d'où l'on vient, en une ligne.
    prec = data.get("precedent")
    if prec is not None:
        if not (isinstance(prec, dict) and isinstance(prec.get("tour"), str) and SEGMENT.match(prec["tour"])
                and isinstance(prec.get("resume"), str) and prec["resume"].strip()):
            errors.append("precedent : {\"tour\": \"t1\", \"resume\": <ce que le tour précédent a réglé, une phrase>} attendu")
        elif prec["tour"] == tour:
            errors.append(f"precedent : le tour précédent ({prec['tour']}) doit différer du tour publié ; change \"tour\" (t2, t3...)")
    return errors


# ---------- Thèmes ----------

ICI = Path(__file__).resolve().parent
THEMES = ICI / "themes"
THEME_PERSO = Path("~/.claude/quizz-theme.json").expanduser()
# Posé après la première astuce sur les thèmes : elle ne revient plus.
ASTUCE_THEME = Path("~/.claude/.quizz-astuce-theme").expanduser()
MODES = ("sombre", "clair")

# Rôle du thème -> variable CSS du gabarit, dans l'ordre où le gabarit les déclarait.
ROLES = {
    "fond": "--bg", "surface": "--surface", "surface-2": "--surface-2", "champ": "--field", "ligne": "--line",
    "controle": "--control", "texte": "--text", "texte-2": "--text-2", "discret": "--muted",
    "accent": "--accent", "accent-hi": "--accent-hi",
    "reco": "--sun", "ecart": "--rasp", "toi": "--lilac", "fait": "--sky",
    "sur-accent": "--on-ink", "focus": "--focus", "voile": "--voile", "sur-encre": "--on-state",
}
ENCRES = ("reco", "ecart", "toi", "fait")
# Encres d'état par défaut, selon que le fond est sombre ou clair.
ENCRES_DEF = {
    "sombre": {"reco": "#FFC940", "ecart": "#FF5A88", "toi": "#C9B8F6", "fait": "#8EC7FF"},
    "clair": {"reco": "#946200", "ecart": "#c42a5c", "toi": "#6a4cc4", "fait": "#1f68b8"},
}
VOILE_ALPHA = {"sombre": ".8", "clair": ".45"}

POLICES = {  # rôle -> (variable CSS, graisses chargées par défaut, pile de secours)
    "tampons": ("--display", [400], ["Anton", "Bebas Neue", "Oswald", "Impact", "Arial Narrow", "sans-serif"]),
    "titres": ("--title", [400, 500, 600, 700], ["Helvetica Neue", "Arial", "system-ui", "sans-serif"]),
    "texte": ("--sans", [400, 500, 600, 700],
              ["ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"]),
    "mono": ("--mono", [500, 700], ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"]),
}
GENERIQUES = {"sans-serif", "serif", "monospace", "system-ui", "ui-sans-serif", "ui-monospace", "ui-serif",
              "-apple-system", "Impact", "Arial", "Menlo", "Consolas", "Roboto"}
FAMILLE = re.compile(r"^(?=.{1,60}$)[A-Za-z0-9]+(?: [A-Za-z0-9]+)*$")  # mots séparés d'un seul espace
DENSITES = {"aere": "1.2", "aéré": "1.2", "normal": "1", "compact": ".85"}
CHAMPS = {"nom", "description", "base", "prefere", "sombre", "clair", "polices", "arrondi", "densite", "matiere"}
HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
HEXA = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")

# Matière (facultative) : ciel, verre, bord, ombres, formes et orbe, posés par le gabarit derrière data-matiere. Sans
# champ « matiere », rien de tout ça n'est écrit dans la page : les thèmes qui n'en ont pas rendent comme avant.
# Rôles de couleur propres à la matière, dans les modes : variable CSS, et si la valeur peut être translucide (#rrggbbaa).
ROLES_MATIERE = {
    "teinte": ("--teinte", False), "sur-teinte": ("--sur-teinte", False),
    "verre": ("--verre", True), "verre-fort": ("--verre-fort", True),
    "remplissage": ("--remplissage", True), "remplissage-survol": ("--remplissage-survol", True),
    "bord": ("--bord", True), "ombre": ("--ombre", False),
}
CHAMPS_MATIERE = {"ciel", "flou", "saturation", "bord", "formes", "orbe", "arrondis"}
ARRONDIS = {"panneau": 30, "carte": 22, "champ": 16, "bouton": 999}
MATIERE_DEF = {"ciel": {"clair": 55, "sombre": 34}, "flou": 16, "saturation": 140, "bord": 2, "formes": False,
               "orbe": False, "arrondis": dict(ARRONDIS)}
OMBRES = {"clair": (.07, .10, .16), "sombre": (.22, .30, .42)}  # repos, verre, surimpression


def rgb(c):
    c = c.lstrip("#")
    if len(c) == 3:
        c = "".join(x * 2 for x in c)
    return tuple(int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))


def alpha(c):
    """Opacité d'une couleur #rrggbbaa (1 pour #rgb et #rrggbb)."""
    c = c.lstrip("#")
    return int(c[6:8], 16) / 255 if len(c) == 8 else 1.0


def avec_alpha(c, a):
    return hexa(rgb(c)) + f"{round(max(0, min(1, a)) * 255):02x}"


def sur(dessus, dessous):
    """Couleur vue d'un calque translucide (#rrggbbaa) posé sur un fond opaque."""
    return mix(dessous, hexa(rgb(dessus)), alpha(dessus))


def hexa(t):
    return "#" + "".join(f"{round(max(0, min(1, x)) * 255):02x}" for x in t)


def lum(c):
    def lin(x):
        return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(x) for x in rgb(c))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def mix(a, b, t):
    """a vers b, de t (0 : a, 1 : b), en sRGB."""
    return hexa(tuple(x + (y - x) * t for x, y in zip(rgb(a), rgb(b))))


def classe(fond):
    return "clair" if lum(fond) > 0.18 else "sombre"


def tenue(c, contraintes):
    """Pire rapport contraste / minimum de c sur ses contraintes [(couleur, mini)] : 1 ou plus, tout est tenu."""
    return min(contraste(c, f) / m for f, m in contraintes)


def corriger(c, contraintes):
    """Déplace la luminosité de c (teinte et saturation gardées) juste assez pour tenir chaque contrainte
    [(couleur, mini)]. Si aucun sens n'y arrive (couleurs claires et sombres mêlées), garde le meilleur compromis."""
    if tenue(c, contraintes) >= 1:
        return c
    h, l, s = colorsys.rgb_to_hls(*rgb(c))
    meilleur, score, ecart_l = c, tenue(c, contraintes), 1
    for sens in (1, -1):
        for i in range(1, 501):
            nl = min(1, max(0, l + sens * i * 0.002))
            x = hexa(colorsys.hls_to_rgb(h, nl, s))
            p = tenue(x, contraintes)
            if p >= 1:
                if score < 1 or abs(nl - l) < ecart_l:
                    meilleur, score, ecart_l = x, p, abs(nl - l)
                break
            if score < 1 and p > score:
                meilleur, score, ecart_l = x, p, abs(nl - l)
            if nl in (0, 1):
                break
    return meilleur


def derive(role, p, cl):
    """Valeur d'un rôle absent, tirée des rôles déjà connus du mode (cl : classe du fond)."""
    f, t, a = p["fond"], p.get("texte"), p.get("accent")
    sombre = cl == "sombre"
    if role == "texte":
        return mix(f, "#ffffff", .9) if sombre else mix(f, "#000000", .88)
    if role == "surface":
        return mix(f, t, .035) if sombre else mix(f, "#ffffff", .65)
    if role == "surface-2":
        return mix(f, t, .07) if sombre else mix(f, t, .05)
    if role == "champ":
        return mix(f, "#000000", .25) if sombre else mix(f, "#ffffff", .8)
    if role == "ligne":
        return corriger(mix(f, t, .12) if sombre else mix(f, t, .14), [(f, 1.25)])  # un filet qui se voit
    if role == "controle":
        return mix(f, t, .42) if sombre else mix(f, t, .48)
    # Texte secondaire et discret : un mélange, puis assez de contraste pour du petit texte, sous celui du texte
    # pour garder la hiérarchie (texte-2 vers 80 % du contraste du texte, discret au plancher de 4.5).
    fonds = [f, p["surface"], p["surface-2"]]
    if role == "texte-2":
        cible = max(4.5, min(6, .8 * min(contraste(t, x) for x in fonds)))
        return corriger(mix(f, t, .75) if sombre else mix(f, t, .8), [(x, cible) for x in fonds])
    if role == "discret":
        return corriger(mix(f, t, .58) if sombre else mix(f, t, .64), [(x, 4.5) for x in fonds])
    if role == "accent":
        return "#6fcf7c" if sombre else "#1f7a35"
    if role == "accent-hi":
        return mix(a, "#ffffff", .22) if sombre else mix(a, "#000000", .16)
    if role == "focus":
        return a
    if role == "sur-accent":
        fonce = min((f, t, p["surface"]), key=lum)
        pale = max((f, t, p["surface"]), key=lum)
        return max((fonce, pale), key=lambda x: contraste(x, a))
    if role == "sur-encre":
        encres = [p[e] for e in ENCRES] + [p["texte-2"]]
        return max((f, t), key=lambda x: min(contraste(x, e) for e in encres))
    if role in ENCRES:
        return ENCRES_DEF[cl][role]
    if role == "voile":
        return mix(f, "#000000", .5) if sombre else t
    raise KeyError(role)


# D'où vient chaque rôle dérivé : si l'une de ses sources a changé par rapport à la base, il est recalculé.
SOURCES = {
    "fond": (), "texte": (), "accent": (), "surface": ("fond", "texte"), "surface-2": ("fond", "texte"),
    "champ": ("fond",), "ligne": ("fond", "texte"), "controle": ("fond", "texte"), "texte-2": ("fond", "texte"),
    "discret": ("fond", "texte"), "accent-hi": ("accent",), "focus": ("accent",),
    "sur-accent": ("accent", "fond", "texte", "surface"), "reco": (), "ecart": (), "toi": (), "fait": (),
    "voile": ("fond", "texte"), "sur-encre": ("fond", "texte", "texte-2") + ENCRES,
}


def resoudre_mode(donne, base, defaut_fond, nom, mode, notes):
    """Palette complète d'un mode : ce que le thème donne, le reste de la base (même mode, même luminosité de fond)
    sauf ce qui dépend d'un rôle changé, recalculé alors par mélange. Le texte et l'accent, d'où presque tout se
    dérive, sont rendus lisibles sur le fond avant la dérivation : les rôles tirés d'eux partent des valeurs corrigées."""
    p = {"fond": donne.get("fond") or (base or {}).get("fond") or defaut_fond}
    cl = classe(p["fond"])
    if base and classe(base["fond"]) != cl:
        base = None  # le fond change de luminosité : rien de la base ne tient, tout se dérive
    change = {r for r in donne if not base or donne[r].lower() != base[r].lower()}
    # Un texte corrigé tout juste à 4.5 ne laisserait aucune place au texte secondaire dérivé de lui : 7 dans ce cas.
    sources = {"texte": 4.5 if "texte-2" in donne else 7, "accent": 4.5}
    for role in SOURCES:
        if role in donne:
            p[role] = donne[role]
        elif base and not any(s in change for s in SOURCES[role]):
            p[role] = base[role]
        else:
            if role != "fond":
                p[role] = derive(role, p, cl)
            change.add(role)
        if role in sources:
            avant = p[role]
            p[role] = corriger(avant, [(p["fond"], sources[role])])
            if p[role] != avant:
                noter(notes, nom, mode, p, role, avant, p[role], [("fond", sources[role])])
                change.add(role)
    return p


# Exigences de lisibilité, appliquées dans l'ordre (une couleur corrigée sert aux suivantes). Ce qui sert à du petit
# texte (texte, texte-2, discret, accent du surtitre et des liens) tient 4.5 ; bordures et commandes, 3.
EXIGENCES = [
    ("texte", ("fond", "surface", "surface-2"), 4.5),
    ("texte-2", ("fond", "surface", "surface-2"), 4.5),
    ("discret", ("fond", "surface", "surface-2"), 4.5),
    ("controle", ("surface",), 3),
    ("accent", ("fond", "surface", "surface-2"), 4.5),
    ("focus", ("fond", "surface"), 3),
    ("sur-accent", ("accent",), 4.5),
    ("accent-hi", ("sur-accent",), 4.5),
]
NOMS_FOND = {"fond": "le fond", "surface": "la surface", "surface-2": "la surface 2"}
PROCHES = {"accent": "de l'accent", "sur-accent": "du texte des boutons (sur-accent)",
           "sur-encre": "des lettres posées sur les encres (sur-encre)", "texte-2": "du texte secondaire",
           "reco": "de l'encre reco", "ecart": "de l'encre écart", "toi": "de l'encre toi", "fait": "de l'encre fait"}


def noter(notes, nom, mode, p, role, avant, apres, contraintes, verbe="corrigé en", apres_p=None):
    """Une ligne par correction ; contraintes : [(rôle de p, mini)], la pire d'avant donne la raison. apres_p : la
    palette où juger la nouvelle valeur, quand ses voisines ont bougé avec elle."""
    def rapport(c, x, q=p):
        return contraste(x, q[c[0]]) / c[1]
    pire = min(contraintes, key=lambda c: rapport(c, avant))[0]
    if pire in PROCHES:
        quoi = f"trop proche {PROCHES[pire]}"
    else:
        quoi = ("trop pâle sur " if classe(p[pire]) == "clair" else "trop sombre sur ") + NOMS_FOND.get(pire, pire)
    note = f"thème {nom}, mode {mode} : {role} {avant} {quoi}, {verbe} {apres}"
    q = apres_p or p
    f, m = min(contraintes, key=lambda c: rapport(c, apres, q))
    if contraste(apres, q[f]) < m:
        note += f" (meilleur possible, contraste {contraste(apres, q[f]):.1f} sur {m})"
    notes.append(note)


def encres_lisibles(p, nom, mode, notes, q=None, extra=()):
    """Encres d'état et sur-encre, les lettres posées sur elles (touches cochées, pastilles, compteurs du bilan).
    Chaque encre tient 4.5 sur le fond et les surfaces (tampons, tags en petit texte, rail) et 4.5 face à sur-encre ;
    sur-encre tient aussi 4.5 face à texte-2 (le compteur « Vide » du bilan). La sur-encre du thème est gardée si
    les encres peuvent s'écarter d'elle ; sinon le bord (fond, texte, noir, blanc) qui tient en touchant le moins
    d'encres ; sinon le meilleur compromis. q, extra : avec une matière, les fonds nommés (verre, remplissage) en plus."""
    q = q or p

    def contraintes(s):
        return [(p["fond"], 4.5), (p["surface"], 4.5), (p["surface-2"], 4.5), (s, 4.5)] + [(q[f], 4.5) for f in extra]

    def essai(s):
        enc = {e: corriger(p[e], contraintes(s)) for e in ENCRES}
        score = min([tenue(s, [(p["texte-2"], 4.5)])] + [tenue(enc[e], contraintes(s)) for e in ENCRES])
        return score, sum(enc[e] != p[e] for e in ENCRES), enc

    orig = p["sur-encre"]
    essais = [(orig,) + essai(orig)]
    autres = [x for x in dict.fromkeys((p["fond"], p["texte"], "#000000", "#ffffff")) if x.lower() != orig.lower()]
    tiennent = [(s,) + essai(s) for s in autres]
    essais += sorted((e for e in tiennent if e[1] >= 1), key=lambda e: e[2]) + [e for e in tiennent if e[1] < 1]
    s, _, _, enc = next((e for e in essais if e[1] >= 1), max(essais, key=lambda e: e[1]))
    if s != orig:
        noter(notes, nom, mode, p, "sur-encre", orig, s, [("texte-2", 4.5)] + [(e, 4.5) for e in ENCRES],
              verbe="remplacé par", apres_p=dict(p, **enc))
    p["sur-encre"] = q["sur-encre"] = s
    for e in ENCRES:
        if enc[e] != p[e]:
            noter(notes, nom, mode, q, e, p[e], enc[e], [("fond", 4.5), ("surface", 4.5), ("surface-2", 4.5),
                                                          ("sur-encre", 4.5)] + [(f, 4.5) for f in extra])
            p[e] = q[e] = enc[e]


def lisible(p, nom, mode, notes, mat=None):
    """Avec une matière, le texte se lit aussi sur ce qui est derrière lui. Le gabarit pose tout sur du verre (rail,
    en-tête, questions, bilan) sauf les titres de groupe, en texte : lui seul se juge aussi sur le ciel et les formes
    nus ; tous se jugent sur le verre et le remplissage posés sur eux, et le texte sur les teintes douces (puces)."""
    q, ex, panneaux = p, {}, []
    if mat:
        d = derives_matiere(p, mat)
        dessous, pan = fonds_matiere(p, mat, d)
        douces = {"la teinte douce": d["teinte-douce"], "la teinte moyenne": d["teinte-moyenne"]}
        douces.update({f"l'encre {e} douce": d[f"{e}-doux"] for e in ENCRES})
        q = dict(p, **dessous, **pan, **douces)
        panneaux = list(pan)
        ex = {"texte": list(dessous) + panneaux + list(douces), "texte-2": panneaux, "discret": panneaux,
              "accent": panneaux, "controle": panneaux, "focus": panneaux}
    for role, fonds, mini in EXIGENCES:
        fonds = tuple(fonds) + tuple(ex.get(role, ()))
        avant = q[role]
        apres = corriger(avant, [(q[f], mini) for f in fonds])
        if apres != avant:
            noter(notes, nom, mode, q, role, avant, apres, [(f, mini) for f in fonds])
            p[role] = q[role] = apres
    if mat:
        avant = p["sur-teinte"]
        apres = corriger(avant, [(p["teinte"], 4.5)])
        if apres != avant:
            noter(notes, nom, mode, p, "sur-teinte", avant, apres, [("teinte", 4.5)])
            p["sur-teinte"] = apres
    encres_lisibles(p, nom, mode, notes, q, panneaux)
    return p


# ---------- Matière ----------

def lire_matiere(t, b):
    """Matière du thème : celle de la base, retouchée champ par champ ; "matiere": null la retire."""
    if "matiere" in t and t["matiere"] is None:
        return None
    m = t.get("matiere")
    if m is None:
        return b.get("matiere")
    out = json.loads(json.dumps(b.get("matiere") or MATIERE_DEF))
    for k, v in m.items():
        if k == "ciel":
            out["ciel"] = dict(out["ciel"], **v) if isinstance(v, dict) else {"clair": v, "sombre": v}
        elif k == "arrondis":
            out["arrondis"] = dict(out["arrondis"], **v)
        elif k == "formes":
            out["formes"] = ({"seconde": None} if v is True else dict(v) if isinstance(v, dict) else False)
        else:
            out[k] = v
    return out


def verifier_matiere(m):
    if m is None:
        return []
    if not isinstance(m, dict):
        return ["matiere : objet {\"ciel\": 55, \"flou\": 16, ...} attendu, ou null pour retirer celle de la base"]
    err = []

    def nombre(v, lo, hi):
        return not isinstance(v, bool) and isinstance(v, (int, float)) and lo <= v <= hi
    inconnus = set(m) - CHAMPS_MATIERE
    if inconnus:
        err.append(f"matiere : champ(s) inconnu(s) : {', '.join(sorted(inconnus))} "
                   f"(attendus : {', '.join(sorted(CHAMPS_MATIERE))})")
    c = m.get("ciel")
    if c is not None and not (nombre(c, 0, 100) or (isinstance(c, dict) and c and set(c) <= set(MODES)
                                                    and all(nombre(x, 0, 100) for x in c.values()))):
        err.append("matiere.ciel : part de la teinte en haut de page, de 0 à 100 (%), ou {\"clair\": 55, \"sombre\": 34}")
    for k, lo, hi, quoi in (("flou", 0, 40, "px"), ("saturation", 100, 200, "%"), ("bord", 0, 4, "px")):
        if k in m and not nombre(m[k], lo, hi):
            err.append(f"matiere.{k} : nombre de {lo} à {hi} ({quoi})")
    f = m.get("formes")
    if f is not None and not isinstance(f, bool):
        if not (isinstance(f, dict) and set(f) <= {"seconde"} and (f.get("seconde") is None or (
                isinstance(f["seconde"], str) and HEX.match(f["seconde"])))):
            err.append("matiere.formes : true, false, ou {\"seconde\": \"#rrggbb\"} (couleur de la deuxième forme)")
    if "orbe" in m and not isinstance(m["orbe"], bool):
        err.append("matiere.orbe : true ou false")
    a = m.get("arrondis")
    if a is not None:
        if not isinstance(a, dict):
            err.append("matiere.arrondis : objet {\"panneau\": 30, \"carte\": 22, \"champ\": 16, \"bouton\": 999} attendu")
        else:
            for k, v in a.items():
                if k not in ARRONDIS:
                    err.append(f"matiere.arrondis.{k} : niveau inconnu ({', '.join(ARRONDIS)})")
                elif not nombre(v, 0, 999 if k == "bouton" else 40):
                    err.append(f"matiere.arrondis.{k} : nombre de 0 à {999 if k == 'bouton' else 40} (px)")
    return err


# D'où vient chaque rôle de matière dérivé : recalculé si l'une de ses sources change par rapport à la base.
SOURCES_MATIERE = {"teinte": ("accent",), "sur-teinte": ("teinte", "fond", "texte"), "verre": ("fond", "texte"),
                   "verre-fort": ("verre",), "remplissage": ("fond", "texte"), "remplissage-survol": ("remplissage",),
                   "bord": ("fond",), "ombre": ("fond", "texte")}


def derive_matiere(role, p, cl):
    sombre = cl == "sombre"
    f, t = p["fond"], p["texte"]
    if role == "teinte":
        return p["accent"]
    if role == "sur-teinte":
        fonce, pale = min((f, t), key=lum), max((f, t), key=lum)
        return max((fonce, pale), key=lambda x: contraste(x, p["teinte"]))
    if role == "verre":
        return avec_alpha(mix(f, t, .12), .62) if sombre else "#ffffffa8"
    if role == "verre-fort":
        return avec_alpha(p["verre"], alpha(p["verre"]) + (.28 if sombre else .2))
    if role == "remplissage":
        return avec_alpha(mix(f, t, .17), .62) if sombre else "#ffffffb8"
    if role == "remplissage-survol":
        return avec_alpha(p["remplissage"], alpha(p["remplissage"]) + .18)
    if role == "bord":
        return "#ffffff29" if sombre else "#ffffff"
    if role == "ombre":
        return "#000000" if sombre else t
    raise KeyError(role)


def resoudre_matiere(donne, base, p, avant):
    """Rôles de matière d'un mode : donnés, sinon repris de la base (même luminosité de fond, sources inchangées),
    sinon dérivés. avant : la palette de base du mode, pour savoir quels rôles ordinaires ont changé."""
    cl = classe(p["fond"])
    if base and classe(base["fond"]) != cl:
        base = None
    change = {r for r in p if not avant or r not in avant or p[r].lower() != avant[r].lower()}
    for role in ROLES_MATIERE:
        if role in donne:
            p[role] = donne[role]
            change.add(role)
        elif base and role in base and not any(s in change for s in SOURCES_MATIERE[role]):
            p[role] = base[role]
        else:
            p[role] = derive_matiere(role, p, cl)
            change.add(role)
    return p


def derives_matiere(p, mat):
    """Valeurs calculées d'un mode : teintes mêlées (de blanc en clair, de surface-2 en sombre, comme la suite
    Homie), couleur du ciel en haut de page, formes du fond."""
    sombre = classe(p["fond"]) == "sombre"
    t = p["teinte"]
    melange = p["surface-2"] if sombre else "#ffffff"
    douce, moyenne = (.30, .40) if sombre else (.26, .55)
    part = mat["ciel"]["sombre" if sombre else "clair"] / 100
    d = {"teinte-douce": mix(melange, t, douce), "teinte-moyenne": mix(melange, t, moyenne),
         "teinte-bord": mix("#ffffff", t, .7), "teinte-survol": mix("#ffffff", t, .88),
         "ciel": mix(p["fond"] if sombre else "#ffffff", t, part), "melange": melange}
    # Encres d'état en version douce (fond des puces et des options choisies) : en clair, la même teinte très claire
    # (un mélange avec du blanc ternirait une encre foncée pour la lecture) ; en sombre, mêlée au fond comme la suite.
    for e in ENCRES:
        if sombre:
            d[f"{e}-doux"] = mix(melange, p[e], .28)
        else:
            h, _, sat = colorsys.rgb_to_hls(*rgb(p[e]))
            d[f"{e}-doux"] = hexa(colorsys.hls_to_rgb(h, .9, sat))
    if mat["formes"]:
        d["forme-1"] = mix("#ffffff", t, .48)
        d["forme-2"] = mix("#ffffff", mat["formes"].get("seconde") or t, .38)
        d["formes-op"] = .32 if sombre else 1
    return d


def fonds_matiere(p, mat, d):
    """Ce sur quoi le texte peut se poser, en couleurs opaques : (dessous, panneaux), chacun {nom: couleur}."""
    dessous = {"le fond": p["fond"], "le ciel": d["ciel"]}
    if mat["formes"]:
        for i in (1, 2):
            for k in ("le fond", "le ciel"):
                dessous[f"la forme {i} sur {k}"] = mix(dessous[k], d[f"forme-{i}"], d["formes-op"])
    panneaux = {}
    for k, u in dessous.items():
        v = sur(p["verre"], u)
        panneaux[f"le verre sur {k}"] = v
        panneaux[f"le remplissage sur le verre sur {k}"] = sur(p["remplissage"], v)
    return dessous, panneaux


def lire_theme(ref, depuis, notes, chaine=()):
    """Charge un thème (nom livré ou chemin) et sa chaîne de bases. Rend (nom, données brutes fusionnées, palettes).

    Modes : ceux que le thème donne ; s'il n'en donne aucun, ceux de sa base. Avec une base explicite (« base »), les
    modes de la base qu'il ne mentionne pas sont repris aussi (une retouche du sombre de papier garde son clair) ;
    "clair": null ou "sombre": null en retire un."""
    if not isinstance(ref, str) or not ref.strip():
        sys.exit("quizz : thème vide")
    livre = THEMES / f"{ref}.json"
    if "/" not in ref and not ref.endswith(".json") and livre.is_file():
        chemin = livre
    else:
        chemin = Path(ref).expanduser()
        if not chemin.is_absolute() and depuis is not None and (depuis / chemin).is_file():
            chemin = depuis / chemin
        if not chemin.is_file():
            noms = ", ".join(sorted(x.stem for x in THEMES.glob("*.json")))
            sys.exit(f"quizz : thème introuvable : {ref} (thèmes livrés : {noms})")
    chemin = chemin.resolve()
    if chemin in chaine:
        sys.exit(f"quizz : thème {ref} : les bases tournent en rond")
    try:
        t = json.loads(chemin.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        sys.exit(f"quizz : thème {chemin} : JSON UTF-8 invalide ({e})")
    except OSError as e:
        sys.exit(f"quizz : thème {chemin} illisible ({e})")
    nom = t.get("nom") if isinstance(t, dict) and isinstance(t.get("nom"), str) else chemin.stem
    err = verifier_theme(t, nom)
    if err:
        sys.exit(f"quizz : thème {nom} invalide\n  " + "\n  ".join(err))

    base_ref = t.get("base", "ardoise" if chemin != (THEMES / "ardoise.json").resolve() else None)
    if base_ref:
        _, b, bpal = lire_theme(base_ref, chemin.parent, notes, chaine + (chemin,))
    else:
        b, bpal = {"nom": "", "polices": {}, "arrondi": 12, "densite": "normal", "prefere": "sombre", "matiere": None}, {}

    polices = dict(b["polices"])
    for role, v in (t.get("polices") or {}).items():
        polices[role] = v
    fus = {"nom": nom, "description": t.get("description", ""), "polices": polices,
           "arrondi": t.get("arrondi", b["arrondi"]), "densite": t.get("densite", b["densite"]),
           "matiere": lire_matiere(t, b)}
    donnes = [m for m in MODES if t.get(m) is not None]
    herite = "base" in t or not donnes
    repris = [m for m in MODES if m not in t and m in bpal and herite]
    modes = [m for m in MODES if m in donnes or m in repris]
    if not modes:
        sys.exit(f"quizz : thème {nom} : aucun mode, ni sombre ni clair (ni donné, ni repris de sa base)")
    fus["repris"] = [m for m in repris if donnes]  # modes tirés tels quels de la base à côté de ceux du thème
    fus["base"] = b["nom"]
    pal = {}
    for m in modes:
        defaut_fond = "#131518" if m == "sombre" else "#f4f5f6"
        donne = t.get(m) or {}
        pal[m] = resoudre_mode({r: v for r, v in donne.items() if r in ROLES}, bpal.get(m), defaut_fond, nom, m, notes)
        if fus["matiere"]:
            avant = {r: v for r, v in (bpal.get(m) or {}).items() if r in ROLES} or None
            resoudre_matiere({r: v for r, v in donne.items() if r in ROLES_MATIERE}, bpal.get(m), pal[m], avant)
    pref = t.get("prefere", b.get("prefere"))
    fus["prefere"] = pref if pref in modes else modes[0]
    return nom, fus, pal


def verifier_theme(t, nom):
    if not isinstance(t, dict):
        return ["objet JSON attendu"]
    err = []
    inconnus = set(t) - CHAMPS
    if inconnus:
        err.append(f"champ(s) inconnu(s) : {', '.join(sorted(inconnus))} (attendus : {', '.join(sorted(CHAMPS))})")
    for k in ("nom", "description", "base"):
        if k in t and not isinstance(t[k], str):
            err.append(f"{k} : texte attendu")
    if "prefere" in t and t["prefere"] not in MODES:
        err.append("prefere : sombre ou clair")
    if isinstance(t.get("base"), str) and not t["base"].strip():
        err.append("base : nom d'un thème livré ou chemin vers un fichier de thème attendu")
    for m in MODES:
        if m not in t or t[m] is None:
            continue
        if not isinstance(t[m], dict):
            err.append(f"{m} : objet {{\"fond\": \"#...\", ...}} attendu, ou null pour retirer ce mode de la base")
            continue
        for r, v in t[m].items():
            if r not in ROLES and r not in ROLES_MATIERE:
                err.append(f"{m}.{r} : rôle inconnu (rôles : {', '.join(ROLES)} ; avec une matière : "
                           f"{', '.join(ROLES_MATIERE)})")
            elif r in ROLES_MATIERE and ROLES_MATIERE[r][1]:
                if not isinstance(v, str) or not HEXA.match(v):
                    err.append(f"{m}.{r} : couleur #rgb, #rrggbb ou #rrggbbaa (translucide) attendue")
            elif not isinstance(v, str) or not HEX.match(v):
                err.append(f"{m}.{r} : couleur #rgb ou #rrggbb attendue")
    pol = t.get("polices")
    if pol is not None:
        if not isinstance(pol, dict):
            err.append("polices : objet {\"titres\": \"Famille\", ...} attendu")
        else:
            for r, v in pol.items():
                fam = v.get("famille") if isinstance(v, dict) else v
                gr = v.get("graisses") if isinstance(v, dict) else None
                if r not in POLICES:
                    err.append(f"polices.{r} : rôle inconnu ({', '.join(POLICES)})")
                elif not isinstance(fam, str) or not FAMILLE.match(fam):
                    err.append(f"polices.{r} : nom de famille Google Fonts attendu (mots de lettres et chiffres, "
                               "séparés d'un seul espace)")
                elif gr is not None and not (isinstance(gr, list) and gr and all(
                        isinstance(g, int) and not isinstance(g, bool) and 100 <= g <= 900 and g % 100 == 0 for g in gr)):
                    err.append(f"polices.{r}.graisses : liste de graisses (100 à 900) attendue")
    a = t.get("arrondi")
    if a is not None and (isinstance(a, bool) or not isinstance(a, (int, float)) or not 0 <= a <= 24):
        err.append("arrondi : nombre de 0 à 24 (px)")
    if "densite" in t and not (isinstance(t["densite"], str) and t["densite"] in DENSITES):
        err.append(f"densite : {', '.join(DENSITES)}")
    err += verifier_matiere(t.get("matiere"))
    return err


def famille(v):
    return v["famille"] if isinstance(v, dict) else v


def variables_polices(th):
    lignes = []
    for role, (var, _, secours) in POLICES.items():
        fam = famille(th["polices"][role]) if role in th["polices"] else None
        pile = ([fam] if fam else []) + [x for x in secours if x != fam]
        lignes.append(f"  {var}: " + ", ".join(x if x in GENERIQUES else f'"{x}"' for x in pile) + ";")
    a = th["arrondi"]
    lignes.append(f"  --r: {int(a) if a == int(a) else a}px;")
    lignes.append(f"  --d: {DENSITES[th['densite']]};")
    return lignes


def liens_polices(themes):
    """Une feuille Google Fonts par famille (graisses réunies) : une graisse absente ne fait tomber qu'elle ;
    si Google refuse les graisses, le lien se rabat sur la graisse normale."""
    fams = {}
    for th in themes:
        for role, v in th["polices"].items():
            g = (v.get("graisses") if isinstance(v, dict) else None) or POLICES[role][1]
            fams.setdefault(famille(v), set()).update(g)
    liens = []
    for fam, gr in fams.items():
        q = fam.replace(" ", "+") + ("" if gr == {400} else ":wght@" + ";".join(str(g) for g in sorted(gr)))
        liens.append(f'<link href="https://fonts.googleapis.com/css2?family={q}&amp;display=swap" rel="stylesheet" '
                     "onerror=\"this.onerror=null;this.href=this.href.replace(/:wght@[^&amp;]*/,'')\">")
    return "\n".join(liens)


def variables_couleurs(p, mode, indent):
    out = [f"{indent}color-scheme: {'dark' if mode == 'sombre' else 'light'};"]
    for role, var in ROLES.items():
        v = p[role]
        if role == "voile":
            r, g, b = (round(x * 255) for x in rgb(v))
            v = f"rgba({r}, {g}, {b}, {VOILE_ALPHA[classe(p['fond'])]})"
        out.append(f"{indent}{var}: {v};")
    return out


def css_rgba(c):
    if alpha(c) >= 1:
        return hexa(rgb(c))
    r, g, b = (round(x * 255) for x in rgb(c))
    return f"rgba({r}, {g}, {b}, {round(alpha(c), 2):g})"


def variables_matiere_theme(th):
    """Ce qui ne change pas d'un mode à l'autre : flou, saturation, épaisseur du bord, arrondis par niveau."""
    m = th.get("matiere")
    if not m:
        return []
    def px(v):
        return f"{int(v) if v == int(v) else v}px"
    lignes = [f"  --flou: {px(m['flou'])};", f"  --sat: {m['saturation']:g}%;", f"  --bord-l: {px(m['bord'])};"]
    lignes += [f"  --r-{k}: {px(v)};" for k, v in m["arrondis"].items()]
    return lignes


def variables_matiere(p, mat, indent):
    if not mat:
        return []
    d = derives_matiere(p, mat)
    out = [f"{indent}{var}: {css_rgba(p[r])};" for r, (var, _) in ROLES_MATIERE.items() if r != "ombre"]
    out += [f"{indent}--{k}: {d[k]};" for k in ("teinte-douce", "teinte-moyenne", "teinte-bord", "teinte-survol",
                                                "ciel", "melange")]
    out += [f"{indent}--{ROLES[e][2:]}-doux: {d[e + '-doux']};" for e in ENCRES]
    r, g, b = (round(x * 255) for x in rgb(p["ombre"]))
    for i, (geo, a) in enumerate(zip(("0 6px 16px", "0 12px 28px", "0 22px 50px"),
                                     OMBRES[classe(p["fond"])]), 1):
        out.append(f"{indent}--ombre-{i}: {geo} rgba({r}, {g}, {b}, {a:g});")
    if mat["formes"]:
        out += [f"{indent}--forme-1: {d['forme-1']};", f"{indent}--forme-2: {d['forme-2']};",
                f"{indent}--formes-op: {d['formes-op']:g};"]
    return out


def attribut_matiere(th):
    """L'attribut que build.py pose sur la page (__MATIERE__) : vide sans matière, la page reste celle d'avant."""
    m = th.get("matiere")
    if not m:
        return ""
    jetons = ["verre"] + (["formes"] if m["formes"] else []) + (["orbe"] if m["orbe"] else [])
    return f' data-matiere="{" ".join(jetons)}"'


def css_theme(th, pal):
    """Variables du thème sur :root. Avec deux modes, le patron à trois états : le mode préféré en base, l'autre
    selon prefers-color-scheme sauf si le viewer impose data-theme, et data-theme l'emporte dans les deux sens."""
    pref = th["prefere"]
    mat = th.get("matiere")

    def couleurs(m, indent):
        return variables_couleurs(pal[m], m, indent) + variables_matiere(pal[m], mat, indent)
    lignes = [":root {"] + variables_polices(th) + variables_matiere_theme(th) + couleurs(pref, "  ") + ["}"]
    autres = [m for m in pal if m != pref]
    if autres:
        m = autres[0]
        cs, pref_cs = ("dark", "light") if m == "sombre" else ("light", "dark")
        lignes += [f"@media (prefers-color-scheme: {cs}) {{", f'  :root:not([data-theme="{pref_cs}"]) {{']
        lignes += couleurs(m, "    ") + ["  }", "}", f':root[data-theme="{cs}"] {{']
        lignes += couleurs(m, "  ") + ["}"]
    return "\n".join(lignes)


def charger(ref, depuis):
    notes = []
    nom, th, pal = lire_theme(ref, depuis, notes)
    for m in pal:
        lisible(pal[m], nom, m, notes, th.get("matiere"))
    return th, pal, notes


def choisir_theme(cli, data, src):
    """--theme > champ "theme" du quiz > ~/.claude/quizz-theme.json > ardoise."""
    if cli:
        return cli, Path.cwd(), "option --theme"
    if data.get("theme"):
        return data["theme"], src.parent, "champ theme du quiz"
    if THEME_PERSO.is_file():
        return str(THEME_PERSO), None, "thème perso"
    return "ardoise", None, "par défaut"


# ---------- Aperçu ----------

APERCU_CSS = """
/* Page d'aperçu : sa propre enveloppe, neutre ; chaque panneau porte les variables d'un thème et d'un mode. */
:root { color-scheme: light; --a-bg: #ebebea; --a-text: #1c1d1f; --a-muted: #5d6066; --a-line: #d2d2cf; }
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) { color-scheme: dark; --a-bg: #0d0d0e; --a-text: #e7e7e5; --a-muted: #9a9ca1; --a-line: #2a2b2e; }
}
:root[data-theme="dark"] { color-scheme: dark; --a-bg: #0d0d0e; --a-text: #e7e7e5; --a-muted: #9a9ca1; --a-line: #2a2b2e; }
body { background: var(--a-bg); color: var(--a-text); font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }
.ap { max-width: 1240px; margin: 0 auto; padding: 40px 0 72px; }
.ap > header h1 { font-family: "Familjen Grotesk", system-ui, sans-serif; font-size: clamp(28px, 3vw, 38px); }
.ap > header p { margin: 10px 0 0; max-width: 40em; color: var(--a-muted); font-size: 16px; }
.ap-th { margin-top: 48px; padding-top: 20px; border-top: 1px solid var(--a-line); }
.ap-th > h2 { margin: 0; font-family: "Familjen Grotesk", system-ui, sans-serif; font-weight: 500; font-size: 26px; line-height: 1.1; }
.ap-th > h2 code { margin-left: 10px; font-family: ui-monospace, Menlo, monospace; font-size: 14px; font-weight: 500; color: var(--a-muted); }
.ap-th > p { margin: 6px 0 16px; max-width: 46em; color: var(--a-muted); font-size: 15px; }
.ap-modes { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 440px), 1fr)); gap: 16px; }
.ap-p {
  background: var(--bg); color: var(--text); font-family: var(--sans); font-size: 16px; line-height: 1.55;
  border: 1px solid var(--line); border-radius: calc(var(--r) * 16 / 12); padding: 18px 22px 22px; min-width: 0;
}
.ap-mode { margin: 0 0 6px; font-family: var(--mono); font-size: 12px; font-weight: 500; color: var(--muted); }
.ap-p .q { scroll-margin: 0; }
.ap-p .q-ctx { font-size: 15px; }
.ap-tags { display: flex; flex-wrap: wrap; gap: 8px 16px; margin-top: 16px; }
.ap-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 14px; margin-top: 18px; }
.ap-actions .btn-fin { width: auto; padding: 11px 22px; }
.ap-actions .tenir { margin-top: 0; }
@media (max-width: 899px) { .ap { padding-top: 28px; } .ap-p { padding: 14px 14px 18px; } }
/* Thème à matière : le panneau porte son ciel et ses formes, la question y devient un panneau de verre. */
.ap-p[data-matiere~="verre"] {
  position: relative; isolation: isolate; overflow: hidden; border: var(--bord-l) solid var(--bord); border-radius: var(--r-panneau);
  background: linear-gradient(180deg, var(--ciel) 0, var(--bg) 320px);
}
.ap-p[data-matiere~="verre"] .ap-mode { color: var(--text); }
.ap-p[data-matiere~="formes"]::before, .ap-p[data-matiere~="formes"]::after {
  content: ""; position: absolute; z-index: -1; aspect-ratio: 1; border-radius: 50%; filter: blur(2px); opacity: var(--formes-op); pointer-events: none;
}
.ap-p[data-matiere~="formes"]::before { width: 46%; right: -14%; top: 40px; background: var(--forme-1); }
.ap-p[data-matiere~="formes"]::after { width: 34%; left: -12%; top: 58%; background: var(--forme-2); }
"""

APERCU_Q = """<article class="q is-cur" data-type="choix" data-state="reco">
  <div class="q-head">
    <p style="margin:0"><span class="q-num">Q2</span><span class="q-type">Une réponse</span></p>
    <div class="slot"><span class="stamp" style="--ink: var(--sun); --doux: var(--sun-doux)">Reco</span></div>
  </div>
  <h2 class="q-title">Où ranger le thème de chacun ?</h2>
  <p class="q-ctx">Un seul réglage par personne, valable pour tous ses quiz.</p>
  <div class="opts has-choice" role="radiogroup">
    <button type="button" class="opt has-reco" role="radio" aria-checked="true" data-state="reco"><span class="key">a</span><span class="otext">Dans un fichier perso, à côté du skill</span><span class="reco-tag">Ma reco</span></button>
    <button type="button" class="opt" role="radio" aria-checked="false"><span class="key">b</span><span class="otext">Dans chaque quiz</span></button>
    <button type="button" class="opt toi" role="radio" aria-checked="false"><span class="key">c</span><span class="otext">À toi de voir</span></button>
  </div>
  <div class="field"><span class="field-l">Une nuance ? <small>facultatif</small></span><textarea rows="1" placeholder="Une condition, une précision, ou rien."></textarea></div>
  <div class="ap-tags"><span class="tag" data-state="reco">Reco</span><span class="tag" data-state="ecart">Écart</span><span class="tag" data-state="toi">À toi</span><span class="tag" data-state="fait">Répondu</span></div>
  <div class="ap-actions"><button class="btn-fin" type="button">Voir le bilan</button><div class="tenir"><button type="button" class="tn" aria-pressed="true">J'y tiens</button><button type="button" class="tn" aria-pressed="false">Peu importe</button></div></div>
</article>"""


def apercu(out, refs):
    if not refs:
        ordre = ["ardoise", "papier", "cobalt", "signal", "homie"]
        refs = sorted((x.stem for x in THEMES.glob("*.json")), key=lambda r: (r not in ordre, ordre.index(r) if r in ordre else 0, r))
    template = (ICI / "template.html").read_text(encoding="utf-8")
    style = template[template.index("<style>") + len("<style>"):template.index("</style>")]
    style = style.replace("__THEME__", "")
    charges, css, corps, toutes = [], [], [], []
    for i, ref in enumerate(refs):
        th, pal, notes = charger(ref, Path.cwd())
        toutes += notes
        charges.append(th)
        modes = [th["prefere"]] + [m for m in pal if m != th["prefere"]]
        panneaux = []
        for m in modes:
            cls = f"th{i}-{m}"
            css.append(f".{cls} {{\n" + "\n".join(variables_polices(th) + variables_matiere_theme(th)
                                                    + variables_couleurs(pal[m], m, "  ")
                                                    + variables_matiere(pal[m], th.get("matiere"), "  ")) + "\n}")
            panneaux.append(f'<div class="ap-p {cls}"{attribut_matiere(th)}><p class="ap-mode">{m}</p>\n{APERCU_Q}\n</div>')
        desc = f"<p>{html.escape(th['description'])}</p>" if th["description"] else "<p></p>"
        cle = ref if "/" not in ref and not ref.endswith(".json") else Path(ref).name
        corps.append(f'<section class="ap-th"><h2>{html.escape(th["nom"])}<code>{html.escape(cle)}</code></h2>{desc}\n'
                     f'<div class="ap-modes">\n' + "\n".join(panneaux) + "\n</div></section>")
    page = "\n".join([
        "<!doctype html>", '<html lang="fr">', "<head>", '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">', "<title>Thèmes de quiz</title>",
        '<link rel="preconnect" href="https://fonts.googleapis.com">',
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>',
        liens_polices(charges + [{"polices": {"titres": "Familjen Grotesk"}}]),
        "<style>" + style + "\n" + "\n".join(css) + "\n" + APERCU_CSS + "</style>", "</head>", "<body>",
        '<main class="ap">', "<header><h1>Thèmes de quiz</h1>",
        "<p>La même question dans chaque thème, en clair et en sombre quand il a les deux. "
        "Pour en choisir un, donne son nom à Claude.</p></header>",
        "\n".join(corps), "</main>", "</body>", "</html>", ""])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    for n in toutes:
        print(n)
    print(f"{out} : aperçu de {len(refs)} thème(s) ({', '.join(t['nom'] for t in charges)})")


def capacites(equipe, images):
    """Ce que la page déclare à la publication. Solo : seul l'auteur écrit, rien sur qui regarde. À plusieurs : chaque
    participant écrit son avis (avis/{self}) et la page lit les profils pour nommer les avis."""
    regles = [{"path": c, "read": "view", "write": "owner"} for c in ("reponses", "messages", "recadrage", "bilan")]
    if equipe:
        regles += [{"path": "avis", "read": "view", "write": "owner"}, {"path": "avis/{self}", "write": "interact"}]
    cap = {"db": {"rules": regles}, "comments": {}, "sample": {"images": True} if images else {}}
    if equipe:
        cap["user"] = {"scopes": ["profile"]}
    return cap


def main():
    args = sys.argv[1:]
    usage = ("usage : python3 build.py questions.json sortie/index.html [--theme <nom|chemin>]\n"
             "        python3 build.py --apercu sortie/apercu.html [thème ...]")
    if args[:1] == ["--apercu"]:
        if len(args) < 2:
            sys.exit(usage)
        return apercu(Path(args[1]), args[2:])
    cli = None
    if "--theme" in args:
        i = args.index("--theme")
        if i + 1 >= len(args):
            sys.exit(usage)
        cli = args[i + 1]
        del args[i:i + 2]
    if len(args) != 2:
        sys.exit(usage)
    src, out = Path(args[0]), Path(args[1])
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"quizz : {src} n'est pas du JSON valide ({e})")

    errors = check(data)
    fichiers = preparer_images(data, src.resolve().parent, errors)
    raw = json.dumps(data, ensure_ascii=False, allow_nan=False)
    if "\u2014" in raw:
        errors.append("tiret cadratin (U+2014) dans le texte : le remplacer par un tiret simple ou reformuler")
    if errors:
        sys.exit("quizz : données invalides\n  " + "\n  ".join(errors))

    ref, depuis, pourquoi = choisir_theme(cli, data, src)
    try:
        th, pal, notes = charger(ref, depuis)
    except SystemExit as e:
        if pourquoi != "thème perso":
            raise
        # Le fichier perso vaut pour tous les quiz : cassé, il ne doit pas bloquer chaque build.
        print(f"{e.code}\n  {THEME_PERSO} ignoré, thème ardoise à la place", file=sys.stderr)
        pourquoi = "thème perso illisible, par défaut"
        th, pal, notes = charger("ardoise", None)
    template = (ICI / "template.html").read_text(encoding="utf-8")
    # Thème d'abord : les données du quiz, posées ensuite, ne peuvent pas contenir un marqueur à remplacer.
    page = template.replace("__POLICES__", liens_polices([th]), 1)
    page = page.replace("__THEME__", css_theme(th, pal), 1)
    page = page.replace("__MATIERE__", attribut_matiere(th))
    page = page.replace("__NOM__", html.escape(data["nom"]), 1)
    page = page.replace("__DATA__", raw.replace("<", "\\u003c"), 1)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    # À côté de la page : une source de publication doit être dans le scratchpad ou le dossier de travail.
    dest = {}
    for publie, octets in fichiers.items():
        cible = out.resolve().parent / publie
        cible.parent.mkdir(parents=True, exist_ok=True)
        if not cible.is_file() or cible.read_bytes() != octets:
            cible.write_bytes(octets)
        dest[publie] = str(cible)
    modes = " + ".join(m for m in [th["prefere"]] + [m for m in pal if m != th["prefere"]])
    suit = ", suit l'appareil" if len(pal) > 1 else ""
    repris = f" ; {' et '.join(th['repris'])} repris de la base {th['base']}" if th["repris"] else ""
    print(f"thème {th['nom']} ({pourquoi}) : {modes}{suit}{repris}")
    for n in notes:
        print(n)
    nm = len(data.get("messages") or [])
    nv = len(visuels_du_quiz(data))
    print(f"{out} : {len(data['questions'])} questions, {nm} messages, {nv} visuels, tour {data['tour']}")
    if pourquoi == "par défaut" and not ASTUCE_THEME.exists():
        print("astuce : tu peux changer l'apparence de tes quiz avec /quizz thème")
        try:
            ASTUCE_THEME.parent.mkdir(parents=True, exist_ok=True)
            ASTUCE_THEME.touch()
        except OSError:
            pass
    equipe = data.get("equipe") is True
    if not equipe and any(isinstance(o, dict) and "implique" in o
                          for q in data["questions"] for o in (q.get("options") or [])):
        print("note : « implique » ne s'affiche qu'à plusieurs (equipe), il ne sert à rien dans ce quiz solo")
    if dest:
        total = sum(len(o) for o in fichiers.values())
        print(f"images : {len(dest)} fichier(s), {total / 1048576:.1f} Mo")
        for ou, im in visuels_du_quiz(data):
            if "src" in im and len(fichiers[im["src"]]) > IMAGE_LOURDE:
                print(f"  {ou} : image lourde ({len(fichiers[im['src']]) / 1048576:.1f} Mo), la page chargera lentement : réduis-la si tu peux")
        print("à publier dans files : " + json.dumps(dest, ensure_ascii=False))
    print(f"{'à plusieurs' if equipe else 'solo'}, capabilities à passer telles quelles : "
          + json.dumps(capacites(equipe, bool(dest)), ensure_ascii=False))
    if nv:
        print(f"visuels à vérifier : python3 {ICI / 'verifie.py'} {out}")


if __name__ == "__main__":
    main()
