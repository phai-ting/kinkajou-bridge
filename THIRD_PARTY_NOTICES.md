# Third-party notices — Kinkajou Bridge

Kinkajou Bridge includes or links to open-source components. This file summarizes
those components and their licenses. Full license texts for the packages listed
below are in the [`third_party_licenses/`](third_party_licenses/) directory
(and are shipped with Windows builds next to `KinkajouBridge.exe`).

Project Kinkajou / Kinkajou Bridge itself is copyright Phai Ting and licensed under
the MIT License — see [`LICENSE`](LICENSE). Third-party components keep their
own licenses as listed below.

## Direct runtime dependencies

| Component | License | Copyright / notice (summary) | Upstream |
| --- | --- | --- | --- |
| FastAPI | MIT | Sebastián Ramírez / FastAPI contributors | https://github.com/fastapi/fastapi |
| Starlette | BSD-3-Clause | Encode OSS Ltd | https://github.com/Kludex/starlette |
| Uvicorn | BSD-3-Clause | Encode OSS Ltd | https://github.com/Kludex/uvicorn |
| websockets | BSD-3-Clause | Aymeric Augustin and contributors | https://github.com/python-websockets/websockets |
| Pydantic | MIT | Samuel Colvin and other contributors | https://github.com/pydantic/pydantic |
| pydantic-settings | MIT | Samuel Colvin and other contributors | https://github.com/pydantic/pydantic-settings |
| pydantic-core | MIT | Samuel Colvin and other contributors | https://github.com/pydantic/pydantic-core |
| HTTPX | BSD-3-Clause | Encode OSS Ltd | https://github.com/encode/httpx |
| httpcore | BSD-3-Clause | Encode OSS Ltd | https://github.com/encode/httpcore |
| anyio | MIT | Alex Grönholm and contributors | https://github.com/agronholm/anyio |
| Click | BSD-3-Clause | Pallets | https://github.com/pallets/click |
| h11 | MIT | Nathaniel J. Smith and other contributors | https://github.com/python-hyper/h11 |
| idna | BSD-3-Clause | Kim Davies and contributors | https://github.com/kjd/idna |
| certifi | MPL-2.0 | Certifi / Mozilla CA bundle (see license file) | https://github.com/certifi/python-certifi |
| curl_cffi | MIT | lexiforest / curl_cffi contributors | https://github.com/lexiforest/curl_cffi |
| aiomqtt | BSD-3-Clause | SBT Instruments and contributors | https://github.com/empicano/aiomqtt |
| annotated-types | MIT | annotated-types contributors | https://github.com/annotated-types/annotated-types |
| typing_extensions | PSF-2.0 | Python Software Foundation and contributors | https://github.com/python/typing_extensions |
| Pillow | HPND-derived (PIL) | Secret Labs AB / Fredrik Lundh and contributors (see license) | https://github.com/python-pillow/Pillow |
| **pystray** | **LGPLv3** | Moses Palmér and contributors | https://github.com/moses-palmer/pystray |

Optional Windows dependency:

| Component | License | Notes |
| --- | --- | --- |
| pywin32 | PSF-style / BSD-derived (see package) | Used when the `windows` extra is installed |

Transitive dependencies of the above packages may also be present in wheels or
frozen builds. Where a package ships its own license file, that file in
`third_party_licenses/` is authoritative.

## Special notes

### pystray (LGPLv3)

Bridge uses [pystray](https://github.com/moses-palmer/pystray) for the system tray
icon on desktop builds. pystray is licensed under the **GNU Lesser General Public
License v3**. The LGPL and GPL texts are included as
`third_party_licenses/pystray_COPYING.LGPL` and
`third_party_licenses/pystray_COPYING`.

You may replace the pystray library with a compatible modified version under the
terms of the LGPL. Source for the version Bridge depends on is available from the
upstream repository above and via the project’s Python dependency lockfile.

### certifi (MPL-2.0)

The CA bundle in certifi is subject to the Mozilla Public License 2.0. See
`third_party_licenses/certifi.txt`.

### Pillow

Pillow’s license is the historical PIL license (permissive). See
`third_party_licenses/pillow.txt` for the full text and contributor notices.

## Packaged Windows builds

The PyInstaller one-folder layout includes this notice file and
`third_party_licenses/` beside the executable so redistributors can meet
attribution requirements without opening the source tree.
