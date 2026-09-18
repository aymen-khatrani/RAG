# Vérifications réalisées

Version 1.0.0 — 17 septembre 2026.

## Moteur Python

Sept tests automatisés passent avec pdfplumber 0.11.8 :

1. Extraction sur PDF fictif de quatre pages, provenance, négations, tableau, recherche et repérage de page image.
2. Reprise intégrale depuis le cache puis réparation d’une entrée de cache corrompue.
3. Limite globale de pages, doublon exact, PDF cassé et reconstruction de l’index du lot courant.
4. Interruption après une page puis reprise, sans perdre les pages terminées.
5. Invalidation du cache après changement de paramètres d’extraction.
6. Dossier vide et prévention des exécutions concurrentes.
7. Découpage sans perte sur le texte de test, offsets exacts, nettoyage conservateur et protection CSV contre les formules.

Les tests remplacent les fonctions réseau `socket.connect` et `socket.getaddrinfo` par des erreurs : le traitement réussit sans les utiliser. Cela vérifie le moteur et ses chemins exécutés ; ce n’est pas une certification de tous les composants du poste, du navigateur ou des extensions Jupyter installées.

## Notebook et prévisualisation

Le notebook contient 28 cellules, dont 13 cellules Python. Ces cellules ont été compilées et exécutées dans l’ordre avec la démonstration. Seul l’adaptateur d’affichage IPython a été simulé : le traitement documentaire, les exports et les recherches ont été réellement exécutés.

Le rendu local d’une page via `render_page` a été exécuté. Les quatre pages du PDF fourni ont été rendues et inspectées visuellement. Le notebook livré a ses sorties effacées et aucun chemin de l’environnement de test n’est stocké dans ses cellules de sortie.

L’environnement de validation est Linux. Le lanceur `.cmd`, le serveur et l’interface Jupyter sous Windows n’ont pas été exécutés ici. Les chemins utilisent `pathlib` et les fichiers texte emploient un encodage explicite. Le premier essai sur Windows reste nécessaire.

## Test de charge sur 5 000 pages synthétiques

| Mesure | Résultat observé |
|---|---:|
| PDF | 1 |
| Pages exportées | 5 000 |
| Erreurs de pages ou de fichiers | 0 |
| Tableaux détectés | 50 |
| Fragments indexés | 10 000 |
| Blocs d’obligation candidats | 5 000 |
| Moteur de recherche | SQLite FTS5 |
| Durée de l’exécution de traitement | 34,74 secondes |
| Pic mémoire du processus Linux | environ 69 Mio |

Le PDF de charge contient un texte bref répété et un tableau simple toutes les 100 pages. La génération du PDF est exclue de la durée ; le pic mémoire inclut le processus de génération et de traitement. Ce résultat vérifie le fonctionnement à ce nombre de pages et ne prédit ni la durée, ni la mémoire, ni la qualité sur 5 000 pages de réglementation réelle. Les formules, scans, colonnes et tableaux complexes peuvent demander beaucoup plus de temps et produire des erreurs d’extraction.

Le test est reproductible avec `python tests/benchmark_5000.py`, après installation de `requirements-tests.txt`. Le gros PDF synthétique et les données de benchmark ne sont pas inclus dans le ZIP pour garder le dossier léger.

## Points à vérifier sur le corpus réel

- Lecture des colonnes et ordre des phrases.
- Cellules fusionnées, tableaux sans bordures et suites de tableaux sur plusieurs pages.
- Présence des notes, conditions, exceptions, négations, symboles et unités.
- Titres de clauses réellement reconnus et contexte conservé après changements de section.
- Renvois vers documents absents et versions à renseigner manuellement.
- Obligations exprimées sans les marqueurs lexicaux retenus.
- Pages scannées et schémas qui restent à examiner manuellement.

Aucune norme réelle ni donnée interne de l’entreprise n’a été utilisée pour ces validations.
