# DVD disc art template (Affinity Photo)

`DVD-disc-template.psd` — 4096 x 4096 px square = 116 mm (2 x 58 mm outer radius), about 897 dpi.
Opens in Affinity Photo with named layers (File > Save As .aftemplate once if you want a native template):

- GUIDES group (hide before exporting): centre cross, 15 mm spindle hole, clamp edge r=16.5 mm,
  safe area r=55 mm, files bands (inner 24-28 mm / outer 54-58 mm), recording area edges r=24 / r=58 mm,
  red tint over everything that is NOT written.
- ART: empty layer for your artwork.
- BACKGROUND black: hide it for a transparent background.

Export a flat PNG with the GUIDES group hidden, then add it as a layer in Disc Image Studio
(set the layer to fit the recording area; the square maps to 2 x outer radius).

Regenerate or edit with `make_dvd_template.py` (needs psd-tools + pillow).
