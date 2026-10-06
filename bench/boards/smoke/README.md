# smoke

Minimal 2-layer board for the CI DRC smoke test. Hand-written, no project file (KiCad defaults apply).

Two parallel F.Cu tracks on nets `A` and `B`, 0.25 mm wide, 0.30 mm apart center to center:
edge gap 0.05 mm < default clearance 0.2 mm, so DRC must report a `clearance` error.
Dangling-track warnings are expected too. CI asserts exit 1 and a `clearance` entry.
