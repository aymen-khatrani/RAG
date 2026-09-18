# Pipeline locale de préparation des PDF de freinage

Ce projet prépare tes documents pour des tests d’extraction et de recherche. Il ne décide pas de l’applicabilité d’une norme ni de la conformité d’un train. Aucun texte de norme réelle n’est fourni.

## Démarrage rapide sur Windows Pro

Extraire **tout le ZIP** dans un dossier local autorisé, par exemple `C:\Travail\pipeline_freinage`. Ne pas ouvrir le notebook à l’intérieur du ZIP. Le fichier `pipeline_local.py` doit rester à côté du notebook.

Installer Python 3.11 ou 3.12 **64 bits** selon les règles de l’entreprise. Les commandes suivantes sont pour l’invite de commandes Windows **cmd.exe**, ouverte dans le dossier du projet. L’installation ne nécessite pas d’activer un script PowerShell.

```bat
py -3.12 -m venv .venv
```

Si seule la version 3.11 est installée, remplacer `-3.12` par `-3.11`. Si le lanceur `py` est absent, utiliser le chemin du Python approuvé.

### Installation sans accès à Internet

Demander à la DSI un dossier `wheelhouse` contenant les bibliothèques et leurs dépendances pour **Windows et la même version de Python**. Sur une machine Windows connectée autorisée, sans aucun document confidentiel, la préparation peut se faire avec :

```bat
py -3.12 -m pip download --only-binary=:all: --dest wheelhouse -r requirements.txt
```

Transférer `wheelhouse` par le moyen autorisé. Sur le poste fermé, installer uniquement depuis ces fichiers :

```bat
.venv\Scripts\python.exe -m pip install --no-index --find-links=wheelhouse --disable-pip-version-check -r requirements.txt
```

`--no-index` empêche pip de chercher sur un dépôt externe. Les wheels ne sont pas inclus dans ce ZIP. Si l’entreprise dispose d’un dépôt interne approuvé, la DSI peut fournir son mode d’installation. Le code de traitement ne requiert aucune connexion après installation.

### Configurer et démarrer Jupyter

Enregistrer le noyau dans l’environnement local et désactiver les annonces, ainsi que le gestionnaire d’extensions susceptible d’interroger un catalogue :

```bat
.venv\Scripts\python.exe -m ipykernel install --sys-prefix --name python3 --display-name "Python local freinage"
.venv\Scripts\jupyter.exe labextension disable "@jupyterlab/apputils-extension:announcements"
.venv\Scripts\jupyter.exe labextension disable "@jupyterlab/extensionmanager-extension"
```

Puis double-cliquer sur `demarrer_jupyter.cmd`. Le serveur écoute sur `127.0.0.1` et conserve son authentification par jeton. Le navigateur et le noyau communiquent localement : ce n’est pas un connecteur extérieur. Le lanceur désactive aussi la vérification de mises à jour côté serveur. Les extensions ajoutées par l’entreprise et le navigateur restent sous le contrôle de la DSI ; ce projet n’est pas un pare-feu.

Ouvrir `Pipeline_freinage_local.ipynb`, choisir le noyau local, puis **Run → Run All Cells**. La démonstration est activée par défaut.

## Passer à tes PDF

1. Vérifier la démonstration fictive de 4 pages : texte, tableau, dessin et page image.
2. Copier les PDF dans `data/input` ; les sous-dossiers sont acceptés.
3. Dans l’étape 2 du notebook, régler `MODE_DEMO = False` et garder `MAX_PAGES = 100`.
4. Lancer le notebook et ouvrir `rapport_qualite.html` dans le dossier indiqué.
5. Comparer des résultats au PDF, surtout tableaux, notes, unités et clauses.
6. Régler `MAX_PAGES = None` pour tout traiter, ou `5000` pour plafonner le lot à 5 000 pages. Relancer à partir de la configuration.

La limite globale s’applique aussi aux pages déjà en cache. Elle prend les premières pages des fichiers triés, pas un échantillon aléatoire. Les fichiers différés sont dans l’inventaire. Un document partiellement sélectionné est marqué `partial`.

## Ce que contient le dossier

| Fichier ou dossier | Rôle |
|---|---|
| `Pipeline_freinage_local.ipynb` | Guide exécutable de 14 étapes |
| `pipeline_local.py` | Fonctions d’extraction, cache, préparation, index et exports |
| `demarrer_jupyter.cmd` | Démarrage Windows sur la boucle locale |
| `requirements.txt` | Dépendances de l’utilisateur |
| `data/demo` | PDF fictif de démonstration |
| `data/input` | Tes PDF, à ajouter localement |
| `data/metadata_template.csv` | Références et éditions à renseigner manuellement |
| `tests` | Tests techniques et générateur de données fictives |
| `VALIDATION.md` | Vérifications réalisées et limites connues |

## Pipeline et choix de traitement

**Inventaire.** Recherche récursive des `.pdf`, insensible à la casse. SHA-256 identifie chaque contenu. Les copies exactes sont dédupliquées ; les éditions différentes restent distinctes. Aucun accès à une GED ou un lien présent dans un PDF.

**Extraction.** `pdfplumber` lit la couche texte et la géométrie. Le texte est stocké par page ; la position PDF commence à 1. La pagination imprimée n’est pas devinée. Le parseur peut mal restituer l’ordre de lecture des colonnes ; ce cas demande une revue.

**Nettoyage.** Normalisation Unicode NFC et espaces, avec conservation des retours de ligne. Ni suppression automatique d’en-têtes, ni correction des mots coupés, ni reformulation. `raw_text` reste disponible. Les lignes de début/fin répétées au moins trois fois sont listées pour revue, sans les retirer.

**Tableaux.** Détection des bordures par défaut. Un tableau candidat doit avoir au moins deux lignes et deux colonnes. Les cellules, dimensions et coordonnées sont conservées. Les cellules fusionnées et notes peuvent être mal restituées ; aucune fusion multipage automatique. La stratégie alternative `text` peut surdétecter des tableaux. Les pages dépassant le seuil configurable d’objets vectoriels sont signalées et leur extraction de tableaux est ignorée pour limiter le coût.

**Graphiques et scans.** Images et objets vectoriels sont comptés et signalés, sans compréhension. Une page avec peu de texte demande une revue : elle n’est pas automatiquement déclarée scannée. Pas d’OCR, même local, dans cette version. `render_page` permet une prévisualisation à la demande.

**Clauses.** Expressions régulières pour titres numérotés et annexes. Le contexte peut se propager à la page suivante, sauf après une page en erreur ou très pauvre en texte. Cela reste une heuristique, avec faux positifs possibles dans les tableaux et sommaires non détectés.

**Fragments.** Taille maximale configurable en caractères, avec coupure préférée à une fin de ligne ou à un espace. Pas de chevauchement ni de passage entre deux pages. Les offsets renvoient à `clean_text`. Une obligation peut être répartie entre fragments : lire le contexte.

**Obligations.** Repérage lexical FR/EN et contexte de lignes, sans analyse grammaticale ou juridique. Les obligations exprimées autrement peuvent être manquées. Tous les résultats restent `candidat_non_valide`.

**Recherche.** SQLite FTS5 avec mots-clés, accents normalisés, mode tous les mots ou au moins un mot, filtre par document. Repli `LIKE` si FTS5 n’est pas disponible. Aucune recherche sémantique, traduction, embedding ou score de confiance.

## Résultats et provenance

Les résultats se trouvent dans `output/corpus/runs/<identifiant>/` ou `output/demo/runs/<identifiant>/`.

| Sortie | Contenu |
|---|---|
| `manifest.json` | Paramètres, versions des parseurs, empreintes, sources et état d’exécution |
| `inventory.csv` | Tous les fichiers trouvés, erreurs, doublons et sélection |
| `pages.jsonl` | Texte brut/nettoyé, pages, flags et tableaux |
| `chunks.jsonl` | Fragments, offsets, clauses et références candidates |
| `tables.jsonl` / `tables.csv` | Cellules brutes et inventaire des tableaux |
| `tables/<empreinte>/...csv` | Un fichier CSV par tableau |
| `obligations_candidates.jsonl` / `.csv` | Blocs à examiner et colonne de commentaire |
| `review_pages.csv` | Pages ayant des signaux ou erreurs |
| `repeated_margins.csv` | Premières et dernières lignes répétées |
| `search.sqlite` | Index local du lot courant |
| `summary.json` | Compteurs de traitement |
| `rapport_qualite.html` | Rapport autonome, sans ressource web |
| `execution.log` | Progression et erreurs |

Les CSV utilisent UTF-8 avec BOM et `;` pour Excel. Les valeurs susceptibles d’être interprétées comme formules sont préfixées par une apostrophe ; JSONL conserve les valeurs extraites. Ne pas interpréter un nombre de tableaux ou de candidats comme une mesure de complétude normative.

## Reprise, cache et versions

Le cache se trouve dans `output/.../cache/<signature>/<sha256>/page_000001.json`. Chaque page est écrite dans un fichier temporaire puis renommée. Une interruption conserve les pages terminées. Les pages en erreur sont retentées par défaut. Un cache corrompu est recalculé.

La signature intègre la version du code, les versions de pdfplumber et pdfminer et les options d’extraction. Si tu modifies les fonctions d’extraction, **incrémenter `VERSION` dans `pipeline_local.py`** ou utiliser un autre dossier output. Changer uniquement `max_chunk_chars` ou les métadonnées reconstruit les exports à partir du cache.

Chaque exécution crée ses propres exports et son propre index. Les résultats de documents retirés ne restent pas dans le nouvel index ; ils restent dans les anciens dossiers pour la traçabilité. `latest_run.json` est mis à jour uniquement après une exécution terminée. Une exécution terminée peut contenir des erreurs documentaires : lire `summary.json`.

Un verrou `pipeline.lock` empêche deux écritures concurrentes dans le même dossier output. Après un arrêt normal ou Ctrl+C, il est retiré. Après un arrêt brutal, vérifier dans Jupyter et le Gestionnaire des tâches qu’aucun traitement ne tourne, puis supprimer ce fichier pour reprendre. Ne pas le retirer pendant une exécution active.

Le cache et les exports ne sont pas chiffrés par ce programme et contiennent du texte documentaire. Choisir un dossier local approuvé, appliquer les droits Windows et la politique de sauvegarde de l’entreprise. Éviter un emplacement OneDrive ou synchronisé si les données doivent rester sur le poste. Les sorties affichées et enregistrées dans le notebook peuvent aussi contenir des extraits.

## Diagnostic rapide

| Symptôme | Action |
|---|---|
| `ModuleNotFoundError` | Vérifier le noyau Jupyter et l’installation dans `.venv` |
| Aucun PDF | Vérifier MODE_DEMO, INPUT_DIR et l’extraction du ZIP |
| Tables absentes | Comparer au PDF ; essayer `text` sur un petit lot distinct |
| Page sans texte | Regarder la page : scan, couverture ou schéma possible ; pas d’OCR ici |
| Recherche vide | Essayer un seul mot, une variante FR/EN et examiner le texte extrait |
| Traitement très lent | Essayer 10 pages ; identifier les pages graphiques complexes ; ne pas extrapoler un PDF simple |
| PDF verrouillé ou cassé | Consulter inventory.csv ; obtenir une copie lisible autorisée |
| Windows refuse le chemin | Extraire près de la racine, par exemple `C:\Travail\freinage`, pour limiter la longueur |

## Tests facultatifs

Les tests ne sont pas nécessaires pour utiliser le notebook. Pour les exécuter, installer `requirements-tests.txt` depuis les wheels approuvés, puis :

```bat
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Ils vérifient notamment reprise après interruption, absence d’appels réseau du moteur, provenance, tableaux, négations, index du lot courant et caches invalides.

## Références techniques publiques

Les liens suivants servent uniquement de documentation ; le code ne les ouvre jamais.

- [pdfplumber — extraction et limites](https://github.com/jsvine/pdfplumber)
- [pip download — préparer les packages](https://pip.pypa.io/en/stable/cli/pip_download/)
- [JupyterLab — annonces et mises à jour](https://jupyterlab.readthedocs.io/en/stable/user/announcements.html)

Version du projet : 1.0.0 — 17 septembre 2026.
# RAG
