# repository-template
Dieses Repo dient als Beispiel und Template für unsere Open Source Repos, und zeigt auf, was wir alles von unseren Repos erwarten. Es basiert auf den [Empfehlungen des Open Source Branches](https://docs.puzzle.ch/user-guides/github-user-guide/index.html).

## Sprache

Für öffentliche Projekte sollte immer Englisch genutzt werden. Wir können in unserer Doku für uns selbst Deutsch nutzen,
es ist aber einfacher, wenn von Anfang an alles in Englisch gehalten wird, und nicht gemischt wird bzw irgendwann übersetzt
werden muss.

## Github-Settings

### Branch Protection
Setzt dies mindestens so, dass nur in `main` gemerged werden kann, wenn ein PR erstellt wurde und dieser mindestens 1 Approval hat - und
dass auch Admins dies nicht bypassen dürfen. Wenn ihr direkt aus Github deployed, dann kann es sich auch lohnen, merges nur zuzulassen,
wenn die Deployments und/oder CI Pipelines erfolgreich waren.

## Dateien

* README - was macht dieses Repo, wie kann man es selber verwenden? Kann gesplittet werden, wenn es zu lang wird.
* LICENSE - alle Repos müssen sauber lizenziert sein. Der [OSS-Guide in Docs](https://docs.puzzle.ch/user-guides/oss-user-guide/index.html#_lizenztypen) hat Tips, und die Branch-Members können auch helfen.
* CODEOWNERS - wer ist Ansprechpartner? Wenn hier niemand eingetragen ist, oder nur noch Leute, die nicht bei Puzzle sind, dann wird's archiviert...
* Code of Conduct, hier muss noch eine Email Adresse von Verantwortlichen hinterlegt werden

Techlabs bilden hier eine Ausnahme. Für diese muss nur ein ReadMe mit letztem Aktualisierungsdatum und eine Lizenz hinterlegt werden.

## Weitergedacht

Wenn eine Community aufgebaut wird, kann eine Anleitung für Contributions (in CONTRIBUTING.md) und Security Policy bzw. Security-Kontakt (in SECURITY.md) hilfreich sein.

OpenSSF Badges u.ä.
