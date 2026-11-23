# Uma Run: sprite mode

A top-down, sprite-stacked pixel version of **Uma Run: Temple of Mambo**. Play it on GitHub Pages, or locally with
`python3 -m http.server` and http://localhost:8000.

**Controls:** left/right (or swipe) to change lane and to take corners in the turn window; up, Space, tap or swipe up to
jump; down or swipe down to slide; P or Esc to pause.

Everything you see is a sprite stack: each object is a strip of flat top-down slices (`strips/*.png`) drawn bottom to
top, rotated with the camera and lifted one pixel per slice. The scenery and obstacles were rebuilt from the original
game's builder code; `tools/` has the scripts that make every strip (Python 3, NumPy, Pillow).
