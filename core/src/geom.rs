//! Integer geometry for the engine (CLAUDE.md rule 3: no floats in the geometry core).
//!
//! Coordinates are `Nm`; areas and products are `i128` so `Nm * Nm` cannot overflow for any
//! board KiCad can represent.

use crate::ir::Nm;

/// A point in board coordinates (KiCad: x right, y down).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Default)]
pub struct Point {
    pub x: Nm,
    pub y: Nm,
}

impl Point {
    pub const ORIGIN: Point = Point {
        x: Nm::ZERO,
        y: Nm::ZERO,
    };

    pub const fn new(x: Nm, y: Nm) -> Point {
        Point { x, y }
    }

    pub fn offset(self, by: Point) -> Point {
        Point::new(self.x + by.x, self.y + by.y)
    }
}

/// Rotation in quarter turns. Arbitrary angles are not used by the placer.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Default)]
pub enum Rotation {
    #[default]
    R0,
    R90,
    R180,
    R270,
}

impl Rotation {
    pub const ALL: [Rotation; 4] = [Rotation::R0, Rotation::R90, Rotation::R180, Rotation::R270];

    /// Rotate a point about the origin, counter-clockwise as seen on screen (KiCad convention,
    /// y axis pointing down).
    pub fn apply(self, p: Point) -> Point {
        match self {
            Rotation::R0 => p,
            Rotation::R90 => Point::new(p.y, -p.x),
            Rotation::R180 => Point::new(-p.x, -p.y),
            Rotation::R270 => Point::new(-p.y, p.x),
        }
    }
}

/// An axis-aligned rectangle, `min` inclusive, `max` exclusive. Empty when `max <= min`
/// on either axis.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Default)]
pub struct Rect {
    pub min: Point,
    pub max: Point,
}

impl Rect {
    /// The rectangle spanned by two corners in any order.
    pub fn from_corners(a: Point, b: Point) -> Rect {
        Rect {
            min: Point::new(a.x.min(b.x), a.y.min(b.y)),
            max: Point::new(a.x.max(b.x), a.y.max(b.y)),
        }
    }

    pub fn width(&self) -> Nm {
        self.max.x - self.min.x
    }

    pub fn height(&self) -> Nm {
        self.max.y - self.min.y
    }

    pub fn is_empty(&self) -> bool {
        self.width() <= Nm::ZERO || self.height() <= Nm::ZERO
    }

    pub fn area(&self) -> i128 {
        if self.is_empty() {
            return 0;
        }
        i128::from(self.width().0) * i128::from(self.height().0)
    }

    pub fn translate(&self, by: Point) -> Rect {
        Rect {
            min: self.min.offset(by),
            max: self.max.offset(by),
        }
    }

    pub fn rotate(&self, r: Rotation) -> Rect {
        Rect::from_corners(r.apply(self.min), r.apply(self.max))
    }

    /// Grown by `d` on every side (shrunk for negative `d`).
    pub fn inflate(&self, d: Nm) -> Rect {
        Rect {
            min: Point::new(self.min.x - d, self.min.y - d),
            max: Point::new(self.max.x + d, self.max.y + d),
        }
    }

    pub fn intersection(&self, other: &Rect) -> Rect {
        Rect {
            min: Point::new(self.min.x.max(other.min.x), self.min.y.max(other.min.y)),
            max: Point::new(self.max.x.min(other.max.x), self.max.y.min(other.max.y)),
        }
    }

    /// Area shared with `other`; touching edges do not overlap.
    pub fn overlap_area(&self, other: &Rect) -> i128 {
        self.intersection(other).area()
    }

    pub fn contains_rect(&self, other: &Rect) -> bool {
        other.min.x >= self.min.x
            && other.min.y >= self.min.y
            && other.max.x <= self.max.x
            && other.max.y <= self.max.y
    }

    pub fn center(&self) -> Point {
        Point::new(
            Nm((self.min.x.0 + self.max.x.0).div_euclid(2)),
            Nm((self.min.y.0 + self.max.y.0).div_euclid(2)),
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rect(x0: i64, y0: i64, x1: i64, y1: i64) -> Rect {
        Rect::from_corners(
            Point::new(Nm::from_mm(x0), Nm::from_mm(y0)),
            Point::new(Nm::from_mm(x1), Nm::from_mm(y1)),
        )
    }

    #[test]
    fn area_and_overlap() {
        let a = rect(0, 0, 4, 2);
        assert_eq!(a.area(), 8 * 1_000_000_000_000);
        assert_eq!(a.overlap_area(&rect(2, 1, 6, 5)), 2 * 1_000_000_000_000);
        assert_eq!(a.overlap_area(&rect(4, 0, 6, 2)), 0, "touching edges");
        assert!(rect(0, 0, 0, 3).is_empty());
    }

    #[test]
    fn rotation_quarter_turns() {
        let p = Point::new(Nm(3), Nm(1));
        assert_eq!(Rotation::R90.apply(p), Point::new(Nm(1), Nm(-3)));
        for r in Rotation::ALL {
            let back = Rotation::ALL.iter().fold(p, |q, _| r.apply(q));
            assert_eq!(back, p, "four turns of {r:?}");
        }
        let r = rect(0, 0, 4, 2).rotate(Rotation::R90);
        assert_eq!((r.width(), r.height()), (Nm::from_mm(2), Nm::from_mm(4)));
    }

    #[test]
    fn containment_and_inflate() {
        let outline = rect(0, 0, 10, 10);
        assert!(outline.contains_rect(&rect(1, 1, 9, 9)));
        assert!(!outline.contains_rect(&rect(1, 1, 9, 9).inflate(Nm::from_mm(2))));
        let center = Point::new(Nm::from_mm(2), Nm::from_mm(1));
        assert_eq!(rect(0, 0, 4, 2).center(), center);
    }
}
