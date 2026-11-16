# Messages à envoyer

- Quand une décision appelle un message (répondre à quelqu'un, poser une question, annoncer un choix), propose-le en bas du quiz, prêt à copier. Projet perso ou travail : Slack, GitHub, Discord, mail, peu importe le canal.
- Deux moments. Un message qui ne dépend d'aucune réponse va dans `messages` du JSON, prêt dès l'ouverture. Un message qui dépend des réponses s'écrit après relecture (section 4 de SKILL.md) ; mets alors `"messages_apres": true` dans le JSON pour que la page annonce l'emplacement.
- Champs : `id` (ex. `M1`), `pour` (personne ou groupe), `ou` (#canal, DM, PR #12, mail), `pourquoi` (une ligne), `format`, `texte`, `lien` facultatif (le fil, la PR).
- `format` selon la destination : `slack` et `markdown` s'écrivent tous deux en Markdown courant (`**gras**`, `_italique_`, `~~barré~~`, `` `code` ``, listes `- `, liens `[texte](url)`) ; pour `slack`, la page copie aussi la mise en forme que Slack colle telle quelle. `texte` : mail, SMS, aucune mise en forme.
- Ids de message uniques sur tout le tour, jamais réutilisés pour un autre message (après `M3`, le suivant est `M4`, même dans un tour republié).
- Sur chaque carte, l'utilisateur peut retoucher, copier, cocher « Envoyé », ou écarter le message avec une raison facultative.
- Le ton est celui de l'utilisateur, pas le tien : appuie-toi sur ses mémoires sur le ton, ses propres messages dans la conversation et ses retouches passées. Court, direct, sans formule creuse, dans la langue du destinataire.
- Tu n'envoies jamais rien toi-même. Les messages Slack, mails et DM restent toujours dans le quiz. Seul un message que ses instructions envoient explicitement dans un autre outil (par exemple les réponses aux issues et PR d'un repo suivi dans un outil de brouillons) n'y va pas.

## Après relecture

- Écris les messages qui découlent de ses réponses : `ArtifactData` `set`, collection `messages`, doc `<tour>`, données `{"liste": [message, ...]}` (mêmes champs et règles que dans le JSON). Le document est remplacé en entier : remets-y ceux que tu avais déjà écrits et que tu gardes. Un message avec le même `id` qu'un message du JSON le remplace. Pas de tiret cadratin. Si `messages_apres` était vrai et qu'aucun message n'est finalement utile, écris `{"liste": [], "aucun": "Pas de message à envoyer : <raison en une ligne>."}`.
- Ses retouches et ses écarts t'apprennent son ton : compare chaque `texte` à sa `base`, lis les `raison`. Si un écart revient (longueur, tutoiement, formules supprimées, emojis, ponctuation, type de message écarté), garde-le dans une mémoire de feedback sur ses messages (mets à jour celle qui existe). Il retouche souvent après coup : relis `reponses/<tour>.messages` quand il revient vers toi sur ce quiz.
