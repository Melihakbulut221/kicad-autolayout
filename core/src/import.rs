//! Build a placement `Problem` from a board's `Layout` (`kal_ir::layout`).
//!
//! Every footprint with a body becomes a part at its current pose, so the file's own placement
//! can be scored next to a placer's. Locked footprints are fixed. Footprints whose rotation is
//! not a quarter turn are fixed too, with a conservative square body (the box rotated through
//! any angle stays inside it) and their pins collapsed to the origin: rotating them exactly
//! needs trigonometry, which the integer core does not do.

use std::collections::BTreeMap;

use crate::geom::{Point, Rect, Rotation};
use crate::ir::layout::{Bounds, Layout, Pad};
use crate::ir::Nm;
use crate::placement::{Net, Part, PinRef, Placement, Pose, Problem, Side};

/// A problem plus the placement found in the file.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Imported {
    pub problem: Problem,
    /// The file's placement (usually the human reference).
    pub current: Placement,
    /// Parts fixed because their rotation is not a quarter turn.
    pub off_grid: Vec<String>,
    /// Footprints without courtyard or pads, left out.
    pub skipped: Vec<String>,
}

/// Why a layout could not become a problem.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ImportError {
    /// No Edge.Cuts geometry, so there is nothing to place into.
    NoOutline,
}

impl std::fmt::Display for ImportError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ImportError::NoOutline => write!(f, "board has no Edge.Cuts outline"),
        }
    }
}

impl std::error::Error for ImportError {}

/// Convert a layout. Nets with fewer than two pins are dropped (they add no wirelength).
pub fn import(layout: &Layout, clearance: Nm) -> Result<Imported, ImportError> {
    let outline = rect(layout.outline.ok_or(ImportError::NoOutline)?);
    let mut parts = Vec::new();
    let mut poses = Vec::new();
    let mut off_grid = Vec::new();
    let mut skipped = Vec::new();
    let mut nets: BTreeMap<&str, Vec<PinRef>> = BTreeMap::new();
    for fp in &layout.footprints {
        let Some(bounds) = fp.body else {
            skipped.push(fp.reference.clone());
            continue;
        };
        let (rotation, body, pins) = match quarter_turn(&fp.rotation) {
            Some(r) => {
                let pins = fp.pads.iter().map(pad_point).collect();
                (r, rect(bounds), pins)
            }
            None => {
                off_grid.push(fp.reference.clone());
                let body = enclosing_square(rect(bounds));
                (Rotation::R0, body, vec![Point::ORIGIN; fp.pads.len()])
            }
        };
        let part = parts.len();
        for (pin, pad) in fp.pads.iter().enumerate() {
            if !pad.net.is_empty() {
                let entry = nets.entry(pad.net.as_str()).or_default();
                entry.push(PinRef { part, pin });
            }
        }
        let pose = Pose {
            at: Point::new(fp.at.0, fp.at.1),
            rotation,
        };
        let fixed = fp.locked || off_grid.last() == Some(&fp.reference);
        let side = if fp.layer.starts_with("B.") {
            Side::Back
        } else {
            Side::Front
        };
        parts.push(Part {
            reference: fp.reference.clone(),
            body,
            pins,
            side,
            fixed: fixed.then_some(pose),
        });
        poses.push(pose);
    }
    let nets = nets
        .into_iter()
        .filter(|(_, pins)| pins.len() >= 2)
        .map(|(name, pins)| Net {
            name: name.to_string(),
            pins,
        })
        .collect();
    let problem = Problem {
        outline,
        clearance,
        parts,
        nets,
    };
    Ok(Imported {
        problem,
        current: Placement { poses },
        off_grid,
        skipped,
    })
}

fn pad_point(pad: &Pad) -> Point {
    Point::new(pad.at.0, pad.at.1)
}

fn rect(b: Bounds) -> Rect {
    Rect::from_corners(Point::new(b[0], b[1]), Point::new(b[2], b[3]))
}

/// KiCad degrees ("90", "-90.0", "450") as a quarter turn; `None` for any other angle.
pub fn quarter_turn(degrees: &str) -> Option<Rotation> {
    // Nm::parse_mm reads a decimal exactly; here the unit is micro-degrees.
    let micro = Nm::parse_mm(degrees)?.0.rem_euclid(360_000_000);
    match micro {
        0 => Some(Rotation::R0),
        90_000_000 => Some(Rotation::R90),
        180_000_000 => Some(Rotation::R180),
        270_000_000 => Some(Rotation::R270),
        _ => None,
    }
}

/// The square around the origin that holds `body` rotated by any angle.
fn enclosing_square(body: Rect) -> Rect {
    let corners = [
        body.min,
        body.max,
        Point::new(body.min.x, body.max.y),
        Point::new(body.max.x, body.min.y),
    ];
    let r2 = corners
        .iter()
        .map(|c| i128::from(c.x.0).pow(2) + i128::from(c.y.0).pow(2))
        .max()
        .unwrap_or(0);
    let r = Nm(i64::try_from(r2.isqrt() + 1).unwrap_or(i64::MAX));
    Rect::from_corners(Point::new(-r, -r), Point::new(r, r))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ir::layout::PlacedFootprint;

    fn fp(reference: &str, rotation: &str, nets: [&str; 2]) -> PlacedFootprint {
        let mm = Nm::from_mm;
        let pad = |x: i64, net: &str| Pad {
            number: x.to_string(),
            at: (mm(x), Nm::ZERO),
            net: net.to_string(),
        };
        PlacedFootprint {
            reference: reference.to_string(),
            layer: "F.Cu".to_string(),
            at: (mm(10), mm(10)),
            rotation: rotation.to_string(),
            body: Some([mm(-2), mm(-1), mm(2), mm(1)]),
            pads: vec![pad(-1, nets[0]), pad(1, nets[1])],
            ..PlacedFootprint::default()
        }
    }

    #[test]
    fn quarter_turns() {
        assert_eq!(quarter_turn("0"), Some(Rotation::R0));
        assert_eq!(quarter_turn("90"), Some(Rotation::R90));
        assert_eq!(quarter_turn("-90.0"), Some(Rotation::R270));
        assert_eq!(quarter_turn("450"), Some(Rotation::R90));
        assert_eq!(quarter_turn("45.5"), None);
        assert_eq!(quarter_turn("x"), None);
    }

    #[test]
    fn imports_parts_nets_and_current_placement() {
        let mut j1 = fp("J1", "0", ["GND", ""]);
        j1.locked = true;
        j1.layer = "B.Cu".to_string();
        let layout = Layout {
            outline: Some([Nm::ZERO, Nm::ZERO, Nm::from_mm(50), Nm::from_mm(40)]),
            footprints: vec![
                fp("R1", "90", ["GND", "VCC"]),
                fp("D1", "45", ["VCC", "LED"]),
                j1,
                PlacedFootprint::default(),
            ],
        };
        let imported = import(&layout, Nm::ZERO).expect("imports");
        let p = &imported.problem;
        assert_eq!(p.parts.len(), 3);
        assert_eq!(imported.off_grid, vec!["D1".to_string()]);
        assert_eq!(imported.skipped, vec![String::new()]);
        // LED has one pin only and is dropped.
        let names: Vec<&str> = p.nets.iter().map(|n| n.name.as_str()).collect();
        assert_eq!(names, ["GND", "VCC"]);
        assert_eq!(imported.current.poses[0].rotation, Rotation::R90);
        assert!(p.parts[0].fixed.is_none());
        assert!(p.parts[1].fixed.is_some() && p.parts[2].fixed.is_some());
        assert_eq!(p.parts[2].side, Side::Back);
        // sqrt(2² + 1²) mm rounded up: the 45° part gets a 2.236 mm half-width square.
        assert_eq!(p.parts[1].body.max.x, Nm(2_236_068));
        assert!(p.validate().is_ok());
    }

    #[test]
    fn no_outline() {
        let layout = Layout::default();
        assert_eq!(import(&layout, Nm::ZERO), Err(ImportError::NoOutline));
    }
}
