//! Placement view of a board (phase 2): footprint poses, body boxes and pads. Read-only.
//!
//! Footprint-local values are as KiCad stores them: relative to the footprint origin with the
//! footprint rotation removed (back-side footprints are stored already flipped).

use std::collections::BTreeMap;

use crate::board::{arg_of, distance, footprint, net_of, outline, point, SummaryError};
use crate::sexpr::{unquote, Document, Node};
use crate::units::Nm;

/// A box as (min x, min y, max x, max y).
pub type Bounds = [Nm; 4];

#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct Pad {
    pub number: String,
    /// Centre relative to the footprint origin, unrotated.
    pub at: (Nm, Nm),
    /// Net name; empty when unconnected.
    pub net: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct PlacedFootprint {
    pub reference: String,
    /// Copper side, `F.Cu` or `B.Cu`.
    pub layer: String,
    /// Origin in board coordinates.
    pub at: (Nm, Nm),
    /// Rotation in degrees exactly as written (`"0"` when absent), e.g. `"90"` or `"45.5"`.
    pub rotation: String,
    pub locked: bool,
    /// Body box relative to the origin, unrotated: the courtyard if there is one, else the
    /// pads. `None` for footprints with neither (logos, fiducial-free graphics).
    pub body: Option<Bounds>,
    pub pads: Vec<Pad>,
}

#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct Layout {
    /// Edge.Cuts bounding box, as in the board summary.
    pub outline: Option<Bounds>,
    pub footprints: Vec<PlacedFootprint>,
}

/// Extract the placement view of a parsed `.kicad_pcb`.
pub fn layout(doc: &Document) -> Result<Layout, SummaryError> {
    let Some(board) = doc.nodes.iter().find(|n| n.head() == Some("kicad_pcb")) else {
        return Err(SummaryError::NotABoard);
    };
    let mut names: BTreeMap<String, String> = BTreeMap::new();
    for net in board.children("net") {
        if let (Some(num), Some(name)) = (net.arg(1), net.arg(2)) {
            names.insert(num.to_string(), unquote(name));
        }
    }
    let footprints = board
        .items()
        .iter()
        .filter(|n| matches!(n.head(), Some("footprint" | "module")))
        .map(|fp| placed(fp, &names))
        .collect();
    Ok(Layout {
        outline: outline(board),
        footprints,
    })
}

fn placed(fp: &Node, names: &BTreeMap<String, String>) -> PlacedFootprint {
    let info = footprint(fp);
    let at_node = fp.child("at");
    let mut f = PlacedFootprint {
        reference: info.reference,
        layer: info.layer,
        at: at_node.and_then(point).unwrap_or((Nm::ZERO, Nm::ZERO)),
        rotation: at_node.and_then(|a| a.arg(3)).unwrap_or("0").to_string(),
        locked: is_locked(fp),
        ..PlacedFootprint::default()
    };
    let mut pad_box: Vec<(Nm, Nm)> = Vec::new();
    for pad in fp.children("pad") {
        let Some(at) = pad.child("at").and_then(point) else {
            continue;
        };
        if let Some((w, h)) = pad.child("size").and_then(point) {
            // Pad rotation is ignored: the larger side bounds the pad either way.
            let r = Nm(w.0.max(h.0).div_euclid(2));
            pad_box.push((at.0 - r, at.1 - r));
            pad_box.push((at.0 + r, at.1 + r));
        }
        f.pads.push(Pad {
            number: pad.arg(1).map(unquote).unwrap_or_default(),
            at,
            net: net_of(pad, names).unwrap_or_default(),
        });
    }
    let mut courtyard: Vec<(Nm, Nm)> = Vec::new();
    for item in fp.items() {
        let graphic = item.head().is_some_and(|h| h.starts_with("fp_"));
        if graphic && arg_of(item, "layer").ends_with(".CrtYd") {
            graphic_points(item, &mut courtyard);
        }
    }
    f.body = bounds(&courtyard).or_else(|| bounds(&pad_box));
    f
}

/// KiCad 6/7 write `(footprint "lib" locked ...)`, KiCad 8+ `(locked yes)`.
fn is_locked(fp: &Node) -> bool {
    let atom = |n: &Node| matches!(n, Node::Atom { text, .. } if text == "locked");
    let bare = fp.items().iter().skip(1).any(atom);
    let child = fp.child("locked").is_some_and(|l| l.arg(1) != Some("no"));
    bare || child
}

fn graphic_points(item: &Node, pts: &mut Vec<(Nm, Nm)>) {
    for key in ["start", "end", "mid"] {
        if let Some(p) = item.child(key).and_then(point) {
            pts.push(p);
        }
    }
    if item.head() == Some("fp_circle") {
        let centre = item.child("center").and_then(point);
        let rim = item.child("end").and_then(point);
        if let (Some((cx, cy)), Some((ex, ey))) = (centre, rim) {
            let r = distance(cx, cy, ex, ey);
            pts.push((cx - r, cy - r));
            pts.push((cx + r, cy + r));
        }
    }
    if let Some(poly) = item.child("pts") {
        for xy in poly.children("xy") {
            if let Some(p) = point(xy) {
                pts.push(p);
            }
        }
    }
}

fn bounds(pts: &[(Nm, Nm)]) -> Option<Bounds> {
    let (x, y) = *pts.first()?;
    let mut b = [x, y, x, y];
    for &(x, y) in pts {
        b[0] = b[0].min(x);
        b[1] = b[1].min(y);
        b[2] = b[2].max(x);
        b[3] = b[3].max(y);
    }
    Some(b)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sexpr::parse;

    const BOARD: &str = r#"(kicad_pcb (version 20240108) (generator "pcbnew")
  (net 0 "") (net 1 "GND") (net 2 "VCC")
  (gr_rect (start 0 0) (end 50 40) (layer "Edge.Cuts"))
  (footprint "R_0603" (layer "F.Cu") (at 10 20 90)
    (property "Reference" "R1")
    (fp_line (start -1.5 -0.7) (end 1.5 -0.7) (layer "F.CrtYd"))
    (fp_line (start 1.5 0.7) (end -1.5 0.7) (layer "F.CrtYd"))
    (pad "1" smd rect (at -0.8 0) (size 0.8 0.9) (layers "F.Cu") (net 1 "GND"))
    (pad "2" smd rect (at 0.8 0) (size 0.8 0.9) (layers "F.Cu") (net 2 "VCC")))
  (footprint "J" locked (layer "B.Cu") (at 30 5)
    (fp_text reference "J1" (at 0 0) (layer "B.SilkS"))
    (pad "1" thru_hole circle (at 0 0) (size 1.7 1.7) (layers "*.Cu") (net 1 "GND"))))
"#;

    #[test]
    fn footprints_poses_bodies_and_pads() {
        let l = layout(&parse(BOARD).expect("parses")).expect("board");
        let edge = [Nm(0), Nm(0), Nm::from_mm(50), Nm::from_mm(40)];
        assert_eq!(l.outline, Some(edge));
        let r1 = &l.footprints[0];
        assert_eq!((r1.reference.as_str(), r1.rotation.as_str()), ("R1", "90"));
        assert_eq!(r1.at, (Nm::from_mm(10), Nm::from_mm(20)));
        assert!(!r1.locked);
        let (x, y) = (Nm(1_500_000), Nm(700_000));
        assert_eq!(r1.body, Some([-x, -y, x, y]));
        assert_eq!(r1.pads[1].net, "VCC");
        assert_eq!(r1.pads[1].at, (Nm(800_000), Nm::ZERO));

        let j1 = &l.footprints[1];
        assert_eq!((j1.reference.as_str(), j1.layer.as_str()), ("J1", "B.Cu"));
        assert!(j1.locked);
        assert_eq!(j1.rotation, "0");
        // No courtyard: the pad box (1.7 mm round pad) is the body.
        let r = Nm(850_000);
        assert_eq!(j1.body, Some([-r, -r, r, r]));
    }

    #[test]
    fn not_a_board() {
        let doc = parse("(kicad_sch (version 1))").expect("parses");
        assert_eq!(layout(&doc), Err(SummaryError::NotABoard));
    }
}
