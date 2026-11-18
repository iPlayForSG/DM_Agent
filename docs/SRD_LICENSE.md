# SRD material attribution

The original SRD-derived spell material used to build `backend/data/spell_catalog_2024.json` comes from the System Reference Document 5.2 (SRD 5.2) by Wizards of the Coast LLC, available at [D&D Beyond](https://www.dndbeyond.com/srd), licensed under the [Creative Commons Attribution 4.0 International License](https://creativecommons.org/licenses/by/4.0/legalcode).

Changes: converted marked SRD entries to JSON and retained source metadata. Chinese names, descriptions, casting information, tables, and scaling text are now taken from the user-provided local 2024 Player's Handbook spell corpus. The single runtime catalogue includes that Chinese text, including entries outside the SRD. The former local spell table has been merged offline; runtime loading no longer overlays a second catalogue. The `text_source`, `text_language`, and `translation_source` fields identify this separately supplied material; `srd52` records original entry membership and does not license or identify an official Chinese translation.

Extraction inputs are the local 5e.tools `spells-xphb.json`, spell class lookup, and the user-provided `核心规则/玩家手册2024/法术详述` corpus. This notice applies to SRD-derived material; it does not relicense the separately supplied Chinese corpus, change the application-code license, or claim rights to other rulebook material.
