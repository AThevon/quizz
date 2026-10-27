# /quizz

Un skill Claude Code. Quand Claude a plusieurs questions à te poser (choix de design, arbitrages, priorités, réponses à envoyer), au lieu d'un pavé il publie un quiz cliquable dans un artefact claude.ai. Chaque option dit sa conséquence et Claude donne sa reco. Tu envoies : Claude relit tes réponses, applique, et écrit dans la page ce qu'il a fait.

Marche dans Claude Code : le terminal ou l'onglet Code de l'app Claude desktop. Pas dans le chat claude.ai.

## Installer

Dans Claude Code :

```
/plugin marketplace add AThevon/quizz
/plugin install quizz@quizz
```

Puis relance Claude Code (ou `/reload-plugins`). La première fois qu'un quiz s'ouvre, claude.ai demande l'accord pour que la page puisse poser des questions à Claude (Creuse) : accepte.

Pour recevoir les nouvelles versions : `/plugin`, onglet Marketplaces, `quizz`, Enable auto-update.

## S'en servir

- `/quizz` : un quiz sur les questions ouvertes de la session. Claude te le propose aussi tout seul quand il a plusieurs questions.
- `/quizz <sujet>` : un quiz sur un sujet précis.
- `/quizz thème <description>` : l'apparence de tes quiz (couleurs, polices, arrondis, densité, clair et sombre). Quatre thèmes livrés : ardoise, papier, cobalt, signal.

## Dans la page

- Ta réponse en un clic, une nuance si besoin, « À toi de voir » pour laisser Claude trancher, « J'y tiens / Peu importe ».
- Un sommaire qui montre ce qui reste : un décompte des questions à trancher, les titres en entier, et un seul signal pour ce qui demande ton attention (bloquante, divergence).
- Questions qui apparaissent selon tes réponses, questions bloquantes et mode « Juste les bloquantes ».
- Creuse (touche q) : demande à Claude d'expliquer une question sans quitter la page. Sa réponse s'écrit mot par mot, mise en page (gras, listes, code), puis se signe et se copie.
- Recadrer (touche x) : si le quiz part de travers, dis ce qui cloche, Claude réécrit les questions.
- Messages à envoyer (Slack, mail...) prêts à copier, dans ton ton. Rien n'est envoyé à ta place.
- Après l'envoi : ce que Claude a appliqué, ses prédictions sur tes réponses, et « Approfondir » pour le tour suivant.
- À plusieurs : partage le quiz (droit Contributeur). Les autres relisent tes choix et ne répondent que là où ils ne sont pas d'accord (une question laissée vide vaut accord). Tu règles chaque divergence dans la page (garder ta réponse, retenir la leur, une synthèse de Claude, ou à discuter), puis « Appliquer » : c'est toujours toi qui lances l'implémentation.
- Ce que ça implique : quand un participant choisit une option coûteuse ou propose autre chose, la page lui dit avant l'envoi ce que ça demande (léger, moyen, lourd), sans jamais bloquer. Tu vois ce qui lui a été dit.
- Un registre des décisions commun à tous tes projets.

## Prérequis

- Claude Code récent, connecté avec un compte claude.ai (les artefacts doivent être disponibles sur ton compte).
- `python3` (bibliothèque standard uniquement).

Si tu avais installé une ancienne version à la main dans `~/.claude/skills/quizz`, supprime ce dossier : sinon deux `/quizz` se concurrencent.

## Licence

MIT
