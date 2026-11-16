# /quizz

Un skill Claude Code. Quand une tâche a plusieurs décisions en suspens (cinq ou plus, ou un choix qui se regarde), ou qu'un brainstorm s'impose, Claude en fait un quiz cliquable dans un artefact claude.ai au lieu d'un pavé de questions. Pour quatre questions ou moins, il les pose directement dans le terminal. Chaque option dit ce qu'elle implique et Claude donne sa reco. Tu réponds en quelques clics : Claude relit tes réponses, applique, et écrit dans la page ce qu'il a fait.

Le quiz est solo par défaut. Dis « à plusieurs » et ça devient une sorte de « prompting multiplayer ». Les questions viennent de l'agent qui a le contexte (le code, tes outils) et qui implémentera ensuite : ce qui lui manque, ce sont les choix, et on peut être plusieurs à les lui donner. Tu partages le lien, les autres relisent tes choix et ne répondent que là où ils ne sont pas d'accord, Claude leur dit avant l'envoi ce qu'un choix coûte, et tu tranches avant de lancer l'implémentation.

Pour répondre à un quiz qu'on te partage, rien à installer : le lien suffit, connecté à claude.ai. Pour lancer tes propres quiz, il faut Claude Code : le terminal ou l'onglet Code de l'app Claude desktop, pas le chat claude.ai.

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
- « à plusieurs » (au lancement ou plus tard) : le quiz devient partageable, avec relecture et arbitrage des divergences.
- `/quizz thème <description>` : l'apparence de tes quiz (couleurs, polices, arrondis, densité, clair et sombre). Quatre thèmes livrés : ardoise, papier, cobalt, signal.

## Dans la page

- Des visuels quand la question porte sur quelque chose qui se regarde : Claude dessine les variantes (maquette, palette, mise en page, schéma), rendues pour de vrai sur chaque option, ou y met une capture. Chaque visuel garde sa forme (un écran de téléphone reste en hauteur, une carte carrée reste carrée). Avant de publier, Claude les rend dans Chrome sans écran, mesure ce qui cloche (débordement, texte coupé ou superposé, contraste, toile trop grande) et regarde les captures. Un clic agrandit, un autre referme, on compare, on choisit.
- Ta réponse en un clic, une nuance si besoin, « À toi de voir » pour laisser Claude trancher, « J'y tiens / Peu importe ».
- Un sommaire qui montre ce qui reste : un décompte des questions à trancher, les titres en entier, et un seul signal pour ce qui demande ton attention (bloquante, divergence).
- Questions qui apparaissent selon tes réponses, questions bloquantes et mode « Juste les bloquantes ».
- Creuse (touche q) : demande à Claude d'expliquer une question sans quitter la page. Sa réponse s'écrit mot par mot, mise en page (gras, listes, code), puis se signe et se copie.
- Recadrer (touche x) : si le quiz part de travers, dis ce qui cloche, Claude réécrit les questions.
- Messages à envoyer (Slack, mail...) prêts à copier, dans ton ton. Rien n'est envoyé à ta place.
- Après l'envoi : ce que Claude a appliqué, ses prédictions sur tes réponses, et « Approfondir » pour le tour suivant.
- À plusieurs (sur demande) : partage le quiz (droit Contributeur). Les autres relisent tes choix et ne répondent que là où ils ne sont pas d'accord (une question laissée vide vaut accord). Tu règles chaque divergence dans la page (garder ta réponse, retenir la leur, une synthèse de Claude, ou à discuter), puis « Appliquer » : c'est toujours toi qui lances l'implémentation.
- Ce que ça implique : quand un participant choisit une option coûteuse ou propose autre chose, la page lui dit avant l'envoi ce que ça demande (léger, moyen, lourd), sans jamais bloquer. Tu vois ce qui lui a été dit.
- Un registre des décisions commun à tous tes projets (son lien vit dans `~/.claude/quizz-registre.json`).

## Prérequis

- Claude Code récent, connecté avec un compte claude.ai (les artefacts doivent être disponibles sur ton compte).
- `python3` (bibliothèque standard uniquement).
- Chrome ou Chromium pour vérifier les visuels (facultatif ; `QUIZZ_CHROME` pour en désigner un).

Si tu avais installé une ancienne version à la main dans `~/.claude/skills/quizz`, supprime ce dossier : sinon deux `/quizz` se concurrencent.

## Licence

MIT
