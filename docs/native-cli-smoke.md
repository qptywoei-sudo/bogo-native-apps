# Full native CLI synthetic file QA

`scripts/smoke_craft.py` runs real, already built native CLIs from the immutable
source versions in `manifests/full-native-apps.json`. It does not build an app,
start a GUI, attach to an existing server, download a model, or use user media.
Every input is generated inside a fresh output directory.

```sh
python3 scripts/smoke_craft.py --app photo --plan
python3 scripts/smoke_craft.py --app photo --cli /absolute/path/to/photocraft-cli --output /absolute/path/to/new-photo-qa
```

On Windows, supply the absolute native `.exe` path. Run one app at a time with
its matching version and its own empty output directory. Retain the same font
and runtime resource environment as the full native build/package. A relative
CLI path, wrong CLI version, or nonempty output directory is rejected.

| App | Actual native operations | Independent output assertions |
| --- | --- | --- |
| Photo | PNG → PCraft → PNG; create two layers; paint; reopen and add another layer | Every original RGBA pixel retained; named layers and canvas retained; visible green stroke pixels |
| Vector | Create ellipse and fill; save native; reopen and add rectangle; export SVG, PNG, PDF; reimport SVG | Editable SVG geometry/fills retained across saves; raster dimensions and visible blue artwork; PDF page structure |
| Film | Create sequence and matte; place and razor; save/reopen and change matte; render; encode MP4; probe exported media | Two contiguous six-frame clips; source continuity and 12-frame total; exact rendered blue pixel; MP4 video/sample data and native decoder reopening |
| Light | Render generated tone ramp; change exposure and size; persist library edits; reopen; export JPEG and original plus XMP | Pixel brightness and dimensions; persisted exposure value; unchanged original bytes; real JPEG and editable sidecar |
| PDF | Generate two-page PDF; edit rotation/metadata; save/reopen; extract text; render; extract/combine/split; create/save native document | Saved title/author/text/page order and counts; rotation and render dimensions; nonblank graphics; PDF cross-reference and real page dictionaries |
| Effect | Create composition/solid; animate two position keys; save/reopen and render midpoint | Retained two keys; actual midpoint evaluation; visible blue rendered pixels |
| Design | Create text layout; save native; export IDML, EPUB, PDF, PNG; reopen native and IDML | Editable story text retained; ZIP structures and serialized text; PDF pages; nonblank text raster |
| UI | Create named frames; save/reopen; export scaled PNG and SVG; convert native → JSON → native | Both frame names retained; expected scale and actual red pixels; valid vector XML |
| Sound | Generate real PCM tone; import and save session; reopen and reduce mix gain; bounce; reopen again; FLAC roundtrip | Source loaded and gain retained; rate/duration; actual waveform RMS at −6 dB; retained samples after lossless conversion |
| CAD | Create line/circle; save DXF; reopen and add ellipse; calculate distance/area; export SVG, PNG, PDF | Independent DXF group coordinates/dimensions; distance 5, area 6, perimeter 12; valid vector XML and nonblank geometry raster |

Each command records its arguments, exit code, elapsed time, stdout and stderr.
`report.json` binds the result to the actual CLI SHA-256, pinned source contract,
checks, and SHA-256/bytes of generated artifacts. Any command, content, version,
or format assertion failure exits nonzero and produces a failed report. A plan
has `status: "not_run"`; it is never an application success result.

The independent parsers check PNG CRC/deflate/pixels (all five filters), PCM and
float WAVE samples, ASCII DXF group pairs, and PDF cross-reference/page objects
(including Flate object streams). They explicitly reject unsupported encodings.
These checks supplement the actual native file reopening; they do not establish
complete compatibility with commercial editing applications.

`tests/test_smoke_craft.py` verifies parser oracles, invalid files, plan/source
identity, preservation of an existing output directory, and rejection/reporting
of a real executable with the wrong version. These utility tests do not claim
that any native app scenario has run. Native scenario execution remains pending
until the matching full native binaries are supplied. This initial handoff does
not add the smoke runner to the build workflow or skip any original app tests.
