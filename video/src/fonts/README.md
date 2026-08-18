# Vendored fonts

Latin-subset `woff2` files, pinned here so a render never depends on network
egress or on the render browser trusting the CDN's TLS chain.

| File | Family | Weights | License |
| --- | --- | --- | --- |
| `inter-variable.woff2` | [Inter](https://github.com/rsms/inter) | 300–700 (variable) | SIL Open Font License 1.1 |
| `ibm-plex-mono-400.woff2` | [IBM Plex Mono](https://github.com/IBM/plex) | 400 | SIL Open Font License 1.1 |
| `ibm-plex-mono-500.woff2` | IBM Plex Mono | 500 | SIL Open Font License 1.1 |
| `ibm-plex-mono-600.woff2` | IBM Plex Mono | 600 | SIL Open Font License 1.1 |

Both families are licensed under the SIL Open Font License 1.1, which permits
redistribution of the font files as part of this project. Full license text:
<https://openfontlicense.org/>.

To refresh them, re-download the `latin` subset faces referenced by:

```
https://fonts.googleapis.com/css2?family=Inter:wght@300..700&family=IBM+Plex+Mono:wght@400;500;600&display=swap
```

(request it with a modern browser `User-Agent` so Google serves `woff2`).
