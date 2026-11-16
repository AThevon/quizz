# Registre des décisions

Un seul artefact, commun à tous les projets, qui garde ce qui a été tranché. Son lien est dans `~/.claude/quizz-registre.json` (`{"url": "https://claude.ai/..."}`), hors du skill et hors des projets : c'est la seule source, ne le range pas dans la mémoire d'un projet (chaque projet en recréait un).

- Fichier absent : cherche « Registre des décisions » avec `Artifact` `list`. Un seul trouvé : écris son lien dans le fichier. Plusieurs : garde celui qui a le plus de décisions, recopie les autres dedans (un `batch` de `set`, mêmes ids), écris le fichier, et dis à l'utilisateur lesquels il peut supprimer. Aucun : publie `${CLAUDE_SKILL_DIR}/registre.html` tel quel (pas de build), avec `capabilities: {"db": {}}` et `icon: "list"`, au premier quiz appliqué, écris le fichier et donne le lien.
- Lien du fichier mort (artefact supprimé) : même recherche, puis réécris le fichier.

- **Avant un quiz** : `ArtifactData` `query` (ou `list`) sur la collection `decisions` du registre, filtrée sur le projet, pour ne pas reposer ce qui est tranché (section 1 de SKILL.md).
- **Après application** : un seul `ArtifactData` `batch` sur l'URL du registre, collection `decisions`, un `set` par question tranchée (choix ou multi répondu, `toi` que tu as tranché ; ni le cadrage, ni les vides, ni les masquées). Id du document : `<projet>~<tour>~<qid>` en minuscules (lettres, chiffres, `_ - . ~ : @ +`), ex. `picta-web~t2~q3`. Contenu :
  ```json
  {"projet": "picta-web", "sujet": "Design", "question": "Couleur du bouton principal",
   "decision": "Bleu ciel pour les CTA, vert réservé aux promos",
   "le": "2026-10-20T14:50:00+02:00", "quiz": "https://claude.ai/code/artifact/...",
   "tour": "t2", "qid": "Q3", "statut": "active", "note": "facultatif : nuance ou condition"}
  ```
  `projet` : nom court et stable (repo ou dossier), toujours écrit pareil, c'est la clé du filtre. `decision` : ce qui a été appliqué, en une phrase concrète, jamais la lettre de l'option.
- **Remplacer** : quand une décision en remplace une ancienne, passe l'ancienne en `update` `{"statut": "remplacee", "remplacee_par": "<id de la nouvelle>"}` dans le même batch. Ne supprime jamais une décision.
- Jamais de nom de personne, jamais de tiret cadratin. Termine par une ligne à l'utilisateur avec le nombre de décisions ajoutées.
