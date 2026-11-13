# Third-party components

The standalone HTML embeds the following unmodified runtime/library distributions. They are also retained as locked build inputs. Copyright and license texts extracted from distributions are in `licenses/`; Pyodide's license is in `PYODIDE-LICENSE`. Python standard-library distribution notices are retained in the packaged standard-library archive and any extracted license files.

| Component | Version | License / upstream |
|---|---|---|
| Pyodide | 0.29.0 | MPL-2.0; https://github.com/pyodide/pyodide |
| CPython (Pyodide runtime) | 3.13.2 | Python Software Foundation; https://www.python.org/ |
| pypdf | 6.10.0 | BSD-3-Clause; https://github.com/py-pdf/pypdf |
| pdfplumber | 0.11.9 | MIT; https://github.com/jsvine/pdfplumber |
| pdfminer.six | 20251230 | MIT; https://github.com/pdfminer/pdfminer.six |
| xlrd | 2.0.1 | BSD; https://github.com/python-excel/xlrd |
| openpyxl | 3.1.5 | MIT; https://openpyxl.readthedocs.io/ |
| et_xmlfile | 2.0.0 | MIT; https://foss.heptapod.net/openpyxl/et_xmlfile |
| charset-normalizer | 3.4.3 | MIT; https://github.com/jawah/charset_normalizer |
| cryptography | 46.0.1 | Apache-2.0 OR BSD-3-Clause; https://github.com/pyca/cryptography |
| cffi | 1.17.1 | MIT; https://cffi.readthedocs.io/ |
| pycparser | 2.22 | BSD-3-Clause; https://github.com/eliben/pycparser |
| six | 1.17.0 | MIT; https://github.com/benjaminp/six |
| OpenSSL (Pyodide package) | 1.1.1w | OpenSSL/SSLeay; https://www.openssl.org/ |

Pyodide/CDN package bytes and pure Python wheels are pinned by SHA256 in `dependencies.lock.json`. This project does not modify those libraries. pdfplumber is used for textual/geometric extraction; image rendering and its optional image dependencies are not used by this tool.

The single-file release is distributed with these notices and license texts in the ZIP/source package. Preserve them when redistributing. No license grant for uploaded business documents is implied.
