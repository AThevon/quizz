# Thèmes

Chaque personne a un thème, valable pour tous ses quiz, rangé dans `~/.claude/quizz-theme.json` (hors du dossier du skill, pour survivre aux mises à jour). Il change les couleurs, les polices (Google Fonts), l'arrondi et la densité ; la mise en page ne bouge jamais. Sans fichier, c'est `ardoise`.

**Choix du thème au build** : `--theme <nom|chemin>`, sinon le champ `"theme"` du JSON du quiz (nom ou chemin relatif au JSON), sinon le thème perso, sinon `ardoise`. Un fichier perso cassé est signalé et le build prend `ardoise`. La première ligne de `build.py` dit le thème utilisé et ses modes, puis chaque correction de lisibilité : reporte-les en une ligne.

**Thèmes livrés** (`themes/`) :
- `ardoise` : ardoise foncée, un seul accent vert, tampons en Anton. Sombre seulement.
- `papier` : gris papier et encre bleu-vert, angles discrets, aéré, fait pour lire longtemps. Clair d'abord, avec un sombre.
- `cobalt` : bleu cobalt profond, accent chartreuse, angles doux. Sombre d'abord, avec un clair bleu pâle.
- `signal` : blanc, noir et orange de balisage, angles vifs, compact, pour les quiz courts. Clair d'abord, avec un sombre.

**Format** (JSON, tout est facultatif, ne donne que ce qui change) :
`{"nom", "description", "base", "prefere": "sombre"|"clair", "sombre": {...}, "clair": {...}, "polices": {...}, "arrondi": 0-24, "densite": "aere"|"normal"|"compact"}`
- `base` : un thème livré ou un chemin (`ardoise` par défaut) ; tout champ absent vient de la base. Avec une `base` explicite, les modes qu'on ne mentionne pas sont repris de la base ; `"clair": null` ou `"sombre": null` retire un mode. Avec deux modes, la page suit le réglage de l'appareil (et le clair/sombre du viewer claude.ai l'emporte).
- Rôles de couleur (#rgb ou #rrggbb) : fond, surface, surface-2, champ, ligne, controle, texte, texte-2, discret, accent, accent-hi, sur-accent (texte des boutons), focus, voile, reco, ecart, toi, fait (encres d'état), sur-encre (lettres posées sur les encres). Un rôle absent est dérivé de fond, texte et accent : un clair qui ne donne que ces trois-là reste cohérent.
- `polices` : `{"tampons", "titres", "texte", "mono"}`, chacune une famille Google Fonts (mots séparés d'un seul espace) ou `{"famille": "...", "graisses": [600]}`. Tampons : une police condensée et lourde (Anton, Bebas Neue, Oswald).
- `arrondi` : rayon des options en px, les autres en dérivent ; les ronds restent ronds, les cases restent carrées. `densite` : facteur sur les espacements ; les cibles restent à 44 px au doigt.
- Lisibilité : `build.py` corrige tout seul, juste assez et en gardant la teinte (au moins 4,5 pour les textes, l'accent et les encres sur fond et surfaces ; 3 pour contrôles et focus). Il ne refuse jamais.

**Aperçu** : `python3 "${CLAUDE_SKILL_DIR}/build.py" --apercu <scratchpad>/apercu.html [thème|chemin ...]` montre la même question et un bouton dans chaque thème, en clair et en sombre, avec le vrai CSS du gabarit (sans argument : les quatre livrés). Publie-le en artefact (sans capacités, `icon: "palette"`) pour faire choisir.

**`/quizz thème [description]`** (l'argument commence par « thème » ou « theme ») : on règle le thème, on ne fait pas de quiz.
1. Lis le thème perso actuel s'il existe, et dis-le en une ligne.
2. Sans description : publie l'aperçu des thèmes livrés et demande lequel, ou « décris-moi ce que tu veux ».
3. Avec une description : propose 3 thèses de style distinctes (palette, polices, arrondi, densité, et une phrase d'intention chacune), tirées de la description et, si on est dans un projet, de son identité visuelle (config Tailwind, tokens, logo). Si le plugin genjutsu est installé (skill `genjutsu:paint` listé), appuie-toi sur sa démarche de direction artistique et ses règles anti-cliché pour formuler les thèses, mais en version courte : ni MASTER.md, ni implémentation, ni audit, seulement les thèses. Sinon, la description suffit.
4. Écris chaque thèse en fichier de thème dans le scratchpad, construis l'aperçu avec elles (plus le thème actuel pour comparer), publie-le, et demande laquelle garder (ou ce qu'il faut ajuster).
5. Écris le thème retenu dans `~/.claude/quizz-theme.json`. S'il en existait un, montre ce qui change et demande avant d'écraser. Rapporte les corrections de lisibilité. Les prochains quiz le prennent tout seuls.
