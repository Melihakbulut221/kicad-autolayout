//! Placement: problem model, cost and placers (phase 2).
//!
//! A `Problem` is engine-side and KiCad-independent: parts with an unrotated body box and pin
//! offsets, nets as lists of pins, a board outline and one clearance between bodies. Placers
//! return a `Placement` (one pose per part) or a typed `PlaceError`; they never panic on bad
//! input. `evaluate` scores any placement the same way, so placers can be compared.
//!
//! `ShelfPlacer` is the deterministic baseline (rows by height); the constrained (CP-SAT) and
//! global (simulated annealing) placers from CLAUDE.md plug in behind the same `Placer` trait.

use crate::geom::{Point, Rect, Rotation};
use crate::ir::Nm;

/// Board side a part is mounted on. Bodies on opposite sides do not collide.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Default)]
pub enum Side {
    #[default]
    Front,
    Back,
}

/// Where a part sits: its origin and rotation.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Default)]
pub struct Pose {
    pub at: Point,
    pub rotation: Rotation,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Part {
    pub reference: String,
    /// Courtyard (or body) box relative to the footprint origin, unrotated.
    pub body: Rect,
    /// Pin offsets from the footprint origin, unrotated. `PinRef::pin` indexes this list.
    pub pins: Vec<Point>,
    pub side: Side,
    /// Parts that must not move (connectors, mounting holes, user-locked parts).
    pub fixed: Option<Pose>,
}

/// One pin of one part.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct PinRef {
    pub part: usize,
    pub pin: usize,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Net {
    pub name: String,
    pub pins: Vec<PinRef>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Problem {
    pub outline: Rect,
    /// Minimum gap between the bodies of two parts on the same side.
    pub clearance: Nm,
    pub parts: Vec<Part>,
    pub nets: Vec<Net>,
}

/// One pose per part, in `Problem::parts` order.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Placement {
    pub poses: Vec<Pose>,
}

/// Why a problem could not be placed.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PlaceError {
    /// A net names a part or pin that does not exist.
    BadPinRef { net: String, pin: PinRef },
    /// A fixed part's body is not inside the outline.
    FixedOutside { reference: String },
    /// The placer found no legal position for this part.
    DoesNotFit { reference: String },
}

impl std::fmt::Display for PlaceError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            PlaceError::BadPinRef { net, pin } => {
                write!(f, "net {net}: no pin {} on part {}", pin.pin, pin.part)
            }
            PlaceError::FixedOutside { reference } => {
                write!(f, "fixed part {reference} is outside the board outline")
            }
            PlaceError::DoesNotFit { reference } => write!(f, "no room for {reference}"),
        }
    }
}

impl std::error::Error for PlaceError {}

impl Problem {
    /// Check references and fixed parts before placing.
    pub fn validate(&self) -> Result<(), PlaceError> {
        for net in &self.nets {
            for &pin in &net.pins {
                let part = self.parts.get(pin.part);
                if !part.is_some_and(|p| pin.pin < p.pins.len()) {
                    let net = net.name.clone();
                    return Err(PlaceError::BadPinRef { net, pin });
                }
            }
        }
        for (i, part) in self.parts.iter().enumerate() {
            if let Some(pose) = part.fixed {
                if !self.outline.contains_rect(&self.body_at(i, pose)) {
                    let reference = part.reference.clone();
                    return Err(PlaceError::FixedOutside { reference });
                }
            }
        }
        Ok(())
    }

    /// The body box of part `i` at `pose`.
    pub fn body_at(&self, i: usize, pose: Pose) -> Rect {
        let body = self.parts[i].body.rotate(pose.rotation);
        body.translate(pose.at)
    }

    /// Board position of a pin at `pose`.
    pub fn pin_at(&self, pin: PinRef, pose: Pose) -> Point {
        let local = self.parts[pin.part].pins[pin.pin];
        pose.rotation.apply(local).offset(pose.at)
    }
}

/// Placement score. Lower is better; legal means no overlap and nothing outside the outline.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct Cost {
    /// Sum over nets of the half-perimeter of the pins' bounding box, in nm.
    pub wirelength: i128,
    /// Sum over same-side part pairs of body overlap (bodies grown by the clearance), in nm².
    pub overlap: i128,
    /// Body area outside the outline, in nm².
    pub outside: i128,
}

impl Cost {
    pub fn is_legal(&self) -> bool {
        self.overlap == 0 && self.outside == 0
    }
}

/// Score a placement. Pairwise overlap is O(n²): fine for the phase 3 target (<= 150 parts);
/// an R-tree replaces it when boards grow.
pub fn evaluate(problem: &Problem, placement: &Placement) -> Cost {
    let poses = &placement.poses;
    let mut cost = Cost::default();
    for net in &problem.nets {
        let mut pins = net.pins.iter().map(|&p| problem.pin_at(p, poses[p.part]));
        if let Some(first) = pins.next() {
            let (mut lo, mut hi) = (first, first);
            for p in pins {
                lo = Point::new(lo.x.min(p.x), lo.y.min(p.y));
                hi = Point::new(hi.x.max(p.x), hi.y.max(p.y));
            }
            cost.wirelength += i128::from((hi.x - lo.x).0) + i128::from((hi.y - lo.y).0);
        }
    }
    let bodies: Vec<Rect> = (0..problem.parts.len())
        .map(|i| problem.body_at(i, poses[i]))
        .collect();
    for (i, a) in bodies.iter().enumerate() {
        cost.outside += a.area() - a.intersection(&problem.outline).area();
        let grown = a.inflate(problem.clearance);
        for (j, b) in bodies.iter().enumerate().skip(i + 1) {
            if problem.parts[i].side == problem.parts[j].side {
                cost.overlap += grown.overlap_area(b);
            }
        }
    }
    cost
}

/// A placement algorithm. `seed` makes randomized placers reproducible (CLAUDE.md rule 7).
pub trait Placer {
    fn name(&self) -> &'static str;
    fn place(&self, problem: &Problem, seed: u64) -> Result<Placement, PlaceError>;
}

/// Deterministic baseline: fixed parts stay, the others are packed left to right in rows
/// (tallest first, then by reference), skipping fixed bodies. Ignores nets; it gives every
/// other placer a legal starting point and a wirelength to beat.
pub struct ShelfPlacer;

impl Placer for ShelfPlacer {
    fn name(&self) -> &'static str {
        "shelf"
    }

    fn place(&self, problem: &Problem, _seed: u64) -> Result<Placement, PlaceError> {
        problem.validate()?;
        let gap = problem.clearance;
        let outline = problem.outline;
        let mut poses = vec![Pose::default(); problem.parts.len()];
        let mut taken: Vec<Rect> = Vec::new();
        for (i, part) in problem.parts.iter().enumerate() {
            if let Some(pose) = part.fixed {
                poses[i] = pose;
                taken.push(problem.body_at(i, pose));
            }
        }
        let mut order: Vec<usize> = (0..problem.parts.len())
            .filter(|&i| problem.parts[i].fixed.is_none())
            .collect();
        order.sort_by_key(|&i| {
            let p = &problem.parts[i];
            (std::cmp::Reverse(p.body.height()), p.reference.clone())
        });

        let (mut x, mut y, mut row) = (outline.min.x, outline.min.y, Nm::ZERO);
        for i in order {
            let body = problem.parts[i].body;
            let (w, h) = (body.width(), body.height());
            let does_not_fit = || PlaceError::DoesNotFit {
                reference: problem.parts[i].reference.clone(),
            };
            loop {
                if x + w > outline.max.x {
                    (x, y, row) = (outline.min.x, y + row + gap, Nm::ZERO);
                    if w > outline.width() {
                        return Err(does_not_fit());
                    }
                }
                if y + h > outline.max.y {
                    return Err(does_not_fit());
                }
                let slot = Rect::from_corners(Point::new(x, y), Point::new(x + w, y + h));
                match taken.iter().find(|t| blocks(t, &slot, gap)) {
                    Some(t) => x = t.max.x + gap,
                    None => {
                        let at = Point::new(x - body.min.x, y - body.min.y);
                        poses[i] = Pose {
                            at,
                            rotation: Rotation::R0,
                        };
                        taken.push(slot);
                        (x, row) = (x + w + gap, row.max(h));
                        break;
                    }
                }
            }
        }
        Ok(Placement { poses })
    }
}

/// True when `slot` comes closer than `gap` to `taken`.
fn blocks(taken: &Rect, slot: &Rect, gap: Nm) -> bool {
    taken.inflate(gap).overlap_area(slot) > 0
}

#[cfg(test)]
mod tests {
    use super::*;

    fn mm(v: i64) -> Nm {
        Nm::from_mm(v)
    }

    fn pt(x: i64, y: i64) -> Point {
        Point::new(mm(x), mm(y))
    }

    fn pose(x: i64, y: i64) -> Pose {
        Pose {
            at: pt(x, y),
            rotation: Rotation::R0,
        }
    }

    fn placed(poses: Vec<Pose>) -> Placement {
        Placement { poses }
    }

    /// A part with a centered body `w` x `h` mm and pins at the left and right edge.
    fn part(reference: &str, w: i64, h: i64) -> Part {
        let (hw, hh) = (Nm(mm(w).0 / 2), Nm(mm(h).0 / 2));
        Part {
            reference: reference.to_string(),
            body: Rect::from_corners(Point::new(-hw, -hh), Point::new(hw, hh)),
            pins: vec![Point::new(-hw, Nm::ZERO), Point::new(hw, Nm::ZERO)],
            side: Side::Front,
            fixed: None,
        }
    }

    fn problem(parts: Vec<Part>) -> Problem {
        let nets = vec![Net {
            name: "N1".to_string(),
            pins: vec![PinRef { part: 0, pin: 1 }, PinRef { part: 1, pin: 0 }],
        }];
        Problem {
            outline: Rect::from_corners(pt(0, 0), pt(20, 10)),
            clearance: Nm::from_um(250),
            parts,
            nets,
        }
    }

    #[test]
    fn evaluate_wirelength_overlap_outside() {
        let p = problem(vec![part("R1", 2, 1), part("R2", 2, 1)]);
        // R1 pin 1 at (6, 5), R2 pin 0 at (9, 7): half-perimeter 3 + 2 mm.
        let cost = evaluate(&p, &placed(vec![pose(5, 5), pose(10, 7)]));
        assert_eq!(cost.wirelength, i128::from(mm(5).0));
        assert!(cost.is_legal());
        let cost = evaluate(&p, &placed(vec![pose(5, 5), pose(5, 5)]));
        assert!(cost.overlap > 0);
        let cost = evaluate(&p, &placed(vec![pose(0, 5), pose(10, 5)]));
        assert_eq!(cost.outside, i128::from(mm(1).0) * i128::from(mm(1).0));
    }

    #[test]
    fn opposite_sides_do_not_collide() {
        let mut back = part("R2", 2, 1);
        back.side = Side::Back;
        let p = problem(vec![part("R1", 2, 1), back]);
        let cost = evaluate(&p, &placed(vec![pose(5, 5), pose(5, 5)]));
        assert!(cost.is_legal());
    }

    #[test]
    fn shelf_placer_is_legal_and_keeps_fixed_parts() {
        // J1 covers the top-left corner, so the first row has to skip it.
        let mut j1 = part("J1", 4, 4);
        j1.fixed = Some(pose(3, 2));
        let mut parts = vec![part("R1", 2, 1), part("R2", 2, 1), j1];
        parts.extend((3..9).map(|i| part(&format!("C{i}"), 1, 1)));
        let p = problem(parts);
        let result = ShelfPlacer.place(&p, 0).expect("fits");
        let cost = evaluate(&p, &result);
        assert!(cost.is_legal(), "{cost:?}");
        assert_eq!(result.poses[2], pose(3, 2));
        let again = ShelfPlacer.place(&p, 1).expect("fits");
        assert_eq!(result, again, "deterministic");
    }

    #[test]
    fn shelf_placer_reports_errors() {
        let p = problem(vec![part("R1", 2, 1), part("U1", 30, 2)]);
        let expected = PlaceError::DoesNotFit {
            reference: "U1".to_string(),
        };
        assert_eq!(ShelfPlacer.place(&p, 0), Err(expected));

        let mut p = problem(vec![part("R1", 2, 1), part("R2", 2, 1)]);
        p.nets[0].pins.push(PinRef { part: 1, pin: 9 });
        assert!(matches!(p.validate(), Err(PlaceError::BadPinRef { .. })));

        let mut j1 = part("J1", 4, 4);
        j1.fixed = Some(pose(0, 0));
        let p = problem(vec![part("R1", 2, 1), j1]);
        assert!(matches!(p.validate(), Err(PlaceError::FixedOutside { .. })));
    }
}
