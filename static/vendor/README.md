# Vendored front-end libraries

Served locally so the panel works without internet access (closed networks). Do not link CDNs instead —
`tests/test_offline.py` fails on any external URL in `templates/` or `static/`.

| Library | Version | Source (npm) | Kept | License |
|---|---|---|---|---|
| Font Awesome Free | 6.5.1 | `@fortawesome/fontawesome-free` | `css/all.min.css`, `webfonts/*.woff2` | `fontawesome/LICENSE.txt` (icons CC BY 4.0, fonts SIL OFL 1.1, code MIT) |
| Monaco Editor | 0.44.0 | `monaco-editor` | `min/vs` → `monaco/vs` | `monaco/LICENSE` (MIT) |
| xterm.js | 5.3.0 | `xterm` | `lib/xterm.js`, `css/xterm.css` | `xterm/LICENSE` (MIT) |
| xterm-addon-fit | 0.8.0 | `xterm-addon-fit` | `lib/xterm-addon-fit.js` | `xterm/LICENSE` (MIT) |

Update: download `https://registry.npmjs.org/<pkg>/-/<name>-<version>.tgz`, copy the files listed above,
bump the version here and run `python3 -m unittest tests.test_offline -q`.
