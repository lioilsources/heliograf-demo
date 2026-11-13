# heliograf.org: demo migrace na GitHub Pages

Náhled náhrady heliograf.org na GitHub Pages. **Není to ostrý web**, originál je na https://heliograf.org/.
Stránky mají `noindex`.

- Kanály Lasco C3 (1024 px) a Lasco 512, posledních 7 dní, snímek každé 3 hodiny.
- Snímky se stahují z NASA (SOHO LASCO REPROCESSING) při každém nasazení a jednou denně (`deploy.yml`).
  Do repa se necommitují; ostrá verze je bude držet v Cloudflare R2 s celým archivem od 2023.
- Staré adresy `/Hg/lasco/?YYMMDD_HHMM` fungují (relativně k tomuto webu).
- Jde nainstalovat do telefonu („Přidat na plochu“), naposledy prohlížené snímky fungují offline.

Ovládání: šipky ← → snímek, ↑ ↓ den, na mobilu přejetí prstem, klepnutí skryje lištu, dvěma prsty zoom.
