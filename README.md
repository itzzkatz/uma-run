# Uma Run: sprite mode

A top-down pixel version of **Uma Run: Temple of Mambo**. Play it on GitHub Pages, or locally with
`python3 -m http.server` and http://localhost:8000.

**Controls:** left/right (or swipe) to change lane and to take corners in the turn window; up, Space, tap or swipe up to
jump; down or swipe down to slide; P or Esc to pause.

The runner, monkeys, obstacles and carrots are sprite stacks: each is a strip of flat top-down slices (`strips/*.png`)
drawn bottom to top, rotated with the camera and lifted one pixel per slice.

The scenery (trees, pillars, arches, gates, end walls, spikes, vents, pines, ice and the floating islands) is made of
**pixel splats** from [ink-studio](https://github.com/siliconjungle/shapeshift-labs-ink-studio). Each scenery piece is
rebuilt from the original game's parts as an ink-studio sculpture and rendered from 32 directions at the game's camera
(0.30 m per pixel, the same pitch as the stacks). The game draws the view nearest each prop's angle
(`splats/*.png`, `splats.json`), then outlines it and adds a shadow at load.

## Rebuilding the art

`tools/` has the scripts (Python 3 with NumPy and Pillow; Node 22 for the splats):

- `build_game.py`: the sprite-stack strips.
- `export_parts.py`: writes every scenery piece's parts to `tools/splat/parts/`.
- `splat/bake.js`: sculpts each piece in ink-studio and renders its 32-direction atlas
  (`INK_STUDIO=/path/to/shapeshift-labs-ink-studio node tools/splat/bake.js [key ...]`).
- `splat/pack.py`: packs the atlases into `splats/` and `splats.json` (`python3 tools/splat/pack.py .`).

## Uma Run 3D, pixel-splat edition (`3d/`)

The original 3D game with only the art changed: same chase camera, same running direction, same gameplay, characters,
UI, music and saves. The runner and the chasers keep their original full-resolution anime look. The world renders at
about 230 pixels on the short side and is scaled up with hard pixel edges.
A post pass draws 1 px ink outlines. Every non-character surface is shaded like the ink-studio pixel splats: a
4-tone hue-shifted ramp per colour with world-locked splat speckle. The background (sky bands, clouds, the ground
below and the floating islands) is restyled to match. Play it at `/3d/`.

`tools/pixel3d/make_pixel.py` makes `3d/index.html` from the original game file
(`python3 tools/pixel3d/make_pixel.py uma-run.html 3d/index.html`). `3d/vendor/` is three.js r170 (MIT).
