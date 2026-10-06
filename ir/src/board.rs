//! Board summary: a compact description of a `.kicad_pcb` for the LLM design review
//! (phase 1). Read-only. Lengths are integer nanometres in KiCad board coordinates.

use std::collections::BTreeMap;

use crate::sexpr::{unquote, Document, Node};
use crate::units::Nm;

/// Identifies the JSON layout written by [`BoardSummary::to_json`].
pub const SUMMARY_SCHEMA: &str = "kal-board-summary/1";

/// One footprint as the review needs it (no geometry).
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct Footprint {
    pub reference: String,
    pub value: String,
    pub lib_id: String,
    pub layer: String,
    pub pads: usize,
}

/// Counts and names extracted from a board file.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct BoardSummary {
    pub version: String,
    pub generator: String,
    pub thickness: Option<Nm>,
    pub copper_layers: Vec<String>,
    pub nets: Vec<String>,
    pub footprints: Vec<Footprint>,
    pub segments: usize,
    pub arcs: usize,
    pub vias: usize,
    pub zones: usize,
    /// Straight-segment copper length per net; arcs are counted but not measured yet.
    pub segment_length: BTreeMap<String, Nm>,
    /// Bounding box (min x, min y, max x, max y) of the Edge.Cuts points; circles use their
    /// full extent, arcs only their start, mid and end points.
    pub outline: Option<[Nm; 4]>,
}

/// Why a document could not be summarized.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SummaryError {
    /// There is no top-level `(kicad_pcb ...)` list.
    NotABoard,
}

impl std::fmt::Display for SummaryError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            SummaryError::NotABoard => write!(f, "not a kicad_pcb file"),
        }
    }
}

impl std::error::Error for SummaryError {}

/// Summarize a parsed `.kicad_pcb` (KiCad 5 and newer formats).
pub fn summarize(doc: &Document) -> Result<BoardSummary, SummaryError> {
    let Some(board) = doc.nodes.iter().find(|n| n.head() == Some("kicad_pcb")) else {
        return Err(SummaryError::NotABoard);
    };
    let mut s = BoardSummary {
        version: arg_of(board, "version"),
        generator: arg_of(board, "generator"),
        ..BoardSummary::default()
    };
    if let Some(general) = board.child("general") {
        s.thickness = mm_arg(general.child("thickness"));
    }
    if let Some(layers) = board.child("layers") {
        for layer in layers.items() {
            if let Some(name) = layer.arg(1).map(unquote) {
                if name.ends_with(".Cu") {
                    s.copper_layers.push(name);
                }
            }
        }
    }

    let mut net_names: BTreeMap<String, String> = BTreeMap::new();
    for net in board.children("net") {
        if let (Some(num), Some(name)) = (net.arg(1), net.arg(2)) {
            let name = unquote(name);
            if !name.is_empty() {
                s.nets.push(name.clone());
            }
            net_names.insert(num.to_string(), name);
        }
    }

    for item in board.items() {
        match item.head() {
            Some("footprint" | "module") => s.footprints.push(footprint(item)),
            Some("segment") => {
                s.segments += 1;
                let len = segment_length(item);
                if let (Some(len), Some(net)) = (len, net_of(item, &net_names)) {
                    if !net.is_empty() {
                        *s.segment_length.entry(net).or_insert(Nm::ZERO) += len;
                    }
                }
            }
            Some("arc") => s.arcs += 1,
            Some("via") => s.vias += 1,
            Some("zone") => s.zones += 1,
            _ => {}
        }
    }
    s.outline = outline(board);
    Ok(s)
}

fn arg_of(node: &Node, head: &str) -> String {
    match node.child(head).and_then(|c| c.arg(1)) {
        Some(text) => unquote(text),
        None => String::new(),
    }
}

fn mm_arg(node: Option<&Node>) -> Option<Nm> {
    Nm::parse_mm(node?.arg(1)?)
}

fn point(node: &Node) -> Option<(Nm, Nm)> {
    Some((Nm::parse_mm(node.arg(1)?)?, Nm::parse_mm(node.arg(2)?)?))
}

fn distance(x0: Nm, y0: Nm, x1: Nm, y1: Nm) -> Nm {
    let dx = i128::from(x1.0) - i128::from(x0.0);
    let dy = i128::from(y1.0) - i128::from(y0.0);
    let len = (dx * dx + dy * dy).isqrt();
    Nm(i64::try_from(len).unwrap_or(i64::MAX))
}

fn segment_length(seg: &Node) -> Option<Nm> {
    let (x0, y0) = point(seg.child("start")?)?;
    let (x1, y1) = point(seg.child("end")?)?;
    Some(distance(x0, y0, x1, y1))
}

/// Net name of a track: KiCad <= 9 writes the net number, newer files may write the name.
fn net_of(item: &Node, names: &BTreeMap<String, String>) -> Option<String> {
    let raw = item.child("net")?.arg(1)?;
    if raw.starts_with('"') {
        return Some(unquote(raw));
    }
    names.get(raw).cloned()
}

fn footprint(fp: &Node) -> Footprint {
    let mut f = Footprint {
        lib_id: fp.arg(1).map(unquote).unwrap_or_default(),
        layer: arg_of(fp, "layer"),
        pads: fp.children("pad").count(),
        ..Footprint::default()
    };
    // KiCad 6+: (property "Reference" "R1"); KiCad 5: (fp_text reference R1).
    for p in fp.children("property") {
        let value = p.arg(2).map(unquote).unwrap_or_default();
        match p.arg(1).map(unquote).as_deref() {
            Some("Reference") => f.reference = value,
            Some("Value") => f.value = value,
            _ => {}
        }
    }
    for t in fp.children("fp_text") {
        let value = t.arg(2).map(unquote).unwrap_or_default();
        match t.arg(1) {
            Some("reference") if f.reference.is_empty() => f.reference = value,
            Some("value") if f.value.is_empty() => f.value = value,
            _ => {}
        }
    }
    f
}

fn outline(board: &Node) -> Option<[Nm; 4]> {
    let mut pts: Vec<(Nm, Nm)> = Vec::new();
    for item in board.items() {
        let is_graphic = item.head().is_some_and(|h| h.starts_with("gr_"));
        if is_graphic && arg_of(item, "layer") == "Edge.Cuts" {
            edge_points(item, &mut pts);
        }
    }
    let (x, y) = *pts.first()?;
    let mut b = [x, y, x, y];
    for &(x, y) in &pts {
        b[0] = b[0].min(x);
        b[1] = b[1].min(y);
        b[2] = b[2].max(x);
        b[3] = b[3].max(y);
    }
    Some(b)
}

fn edge_points(item: &Node, pts: &mut Vec<(Nm, Nm)>) {
    for key in ["start", "end", "mid", "center"] {
        if let Some(p) = item.child(key).and_then(point) {
            pts.push(p);
        }
    }
    if item.head() == Some("gr_circle") {
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

fn ref_prefix(reference: &str) -> String {
    reference.chars().take_while(|c| !c.is_ascii_digit()).collect()
}

fn json_str(s: &str) -> String {
    let mut out = String::with_capacity(s.len() + 2);
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push('"');
    out
}

fn json_array(items: &[String]) -> String {
    format!("[{}]", items.join(", "))
}

fn json_object(fields: &[(&str, String)]) -> String {
    let mut body = Vec::with_capacity(fields.len());
    for (key, value) in fields {
        body.push(format!("{}: {value}", json_str(key)));
    }
    format!("{{{}}}", body.join(", "))
}

impl BoardSummary {
    /// JSON with a fixed key order (schema [`SUMMARY_SCHEMA`]), one top-level key per line.
    pub fn to_json(&self) -> String {
        let mut pads = 0;
        let mut prefixes: BTreeMap<String, usize> = BTreeMap::new();
        let mut footprints = Vec::with_capacity(self.footprints.len());
        for f in &self.footprints {
            pads += f.pads;
            *prefixes.entry(ref_prefix(&f.reference)).or_default() += 1;
            footprints.push(json_object(&[
                ("ref", json_str(&f.reference)),
                ("value", json_str(&f.value)),
                ("lib", json_str(&f.lib_id)),
                ("layer", json_str(&f.layer)),
                ("pads", f.pads.to_string()),
            ]));
        }
        let mut by_prefix = Vec::with_capacity(prefixes.len());
        for (prefix, n) in &prefixes {
            by_prefix.push((prefix.as_str(), n.to_string()));
        }
        let mut lengths = Vec::with_capacity(self.segment_length.len());
        for (net, len) in &self.segment_length {
            lengths.push((net.as_str(), len.0.to_string()));
        }
        let mut nets = Vec::with_capacity(self.nets.len());
        for n in &self.nets {
            nets.push(json_str(n));
        }
        let mut layers = Vec::with_capacity(self.copper_layers.len());
        for l in &self.copper_layers {
            layers.push(json_str(l));
        }
        let thickness = match self.thickness {
            Some(t) => t.0.to_string(),
            None => "null".to_string(),
        };
        let outline = match self.outline {
            Some(b) => json_array(&b.map(|n| n.0.to_string())),
            None => "null".to_string(),
        };
        let counts = json_object(&[
            ("nets", self.nets.len().to_string()),
            ("footprints", self.footprints.len().to_string()),
            ("pads", pads.to_string()),
            ("segments", self.segments.to_string()),
            ("arcs", self.arcs.to_string()),
            ("vias", self.vias.to_string()),
            ("zones", self.zones.to_string()),
        ]);
        let fields = [
            ("schema", json_str(SUMMARY_SCHEMA)),
            ("version", json_str(&self.version)),
            ("generator", json_str(&self.generator)),
            ("thickness_nm", thickness),
            ("copper_layers", json_array(&layers)),
            ("outline_nm", outline),
            ("counts", counts),
            ("footprints_by_prefix", json_object(&by_prefix)),
            ("nets", json_array(&nets)),
            ("segment_length_nm", json_object(&lengths)),
            ("footprints", format!("[\n    {}\n  ]", footprints.join(",\n    "))),
        ];
        let mut lines = Vec::with_capacity(fields.len());
        for (key, value) in &fields {
            lines.push(format!("{}: {value}", json_str(key)));
        }
        format!("{{\n  {}\n}}\n", lines.join(",\n  "))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sexpr::parse;

    const BOARD: &str = r#"(kicad_pcb (version 20240108) (generator "pcbnew")
  (general (thickness 1.6))
  (layers (0 "F.Cu" signal) (2 "In1.Cu" signal) (31 "B.Cu" signal) (44 "Edge.Cuts" user))
  (net 0 "") (net 1 "GND") (net 2 "/DDR/DQ0")
  (footprint "Capacitor_SMD:C_0402" (layer "F.Cu")
    (property "Reference" "C1") (property "Value" "100n")
    (pad "1" smd rect) (pad "2" smd rect))
  (module R_0603 (layer B.Cu)
    (fp_text reference R7 (at 0 0)) (fp_text value 10k (at 0 1))
    (pad 1 smd rect))
  (gr_rect (start 0 0) (end 50 40) (layer "Edge.Cuts"))
  (gr_circle (center 60 20) (end 65 20) (layer "Edge.Cuts"))
  (gr_line (start 0 0) (end 99 99) (layer "F.SilkS"))
  (segment (start 0 0) (end 3 4) (width 0.2) (layer "F.Cu") (net 1))
  (segment (start 3 4) (end 3 10) (width 0.2) (layer "F.Cu") (net 1))
  (segment (start 1 1) (end 2 1) (width 0.2) (layer "F.Cu") (net "/DDR/DQ0"))
  (arc (start 0 0) (mid 1 1) (end 2 0) (net 1))
  (via (at 1 1) (net 1))
  (zone (net 1))
)"#;

    fn summary() -> BoardSummary {
        summarize(&parse(BOARD).unwrap()).unwrap()
    }

    #[test]
    fn summarizes_board() {
        let s = summary();
        assert_eq!(s.version, "20240108");
        assert_eq!(s.generator, "pcbnew");
        assert_eq!(s.thickness, Some(Nm::from_um(1600)));
        assert_eq!(s.copper_layers, ["F.Cu", "In1.Cu", "B.Cu"]);
        assert_eq!(s.nets, ["GND", "/DDR/DQ0"]);
        assert_eq!((s.segments, s.arcs, s.vias, s.zones), (3, 1, 1, 1));
        assert_eq!(s.segment_length["GND"], Nm::from_mm(11));
        assert_eq!(s.segment_length["/DDR/DQ0"], Nm::from_mm(1));
        let outline = [Nm::ZERO, Nm::ZERO, Nm::from_mm(65), Nm::from_mm(40)];
        assert_eq!(s.outline, Some(outline));
    }

    #[test]
    fn reads_new_and_legacy_footprints() {
        let c1 = Footprint {
            reference: "C1".into(),
            value: "100n".into(),
            lib_id: "Capacitor_SMD:C_0402".into(),
            layer: "F.Cu".into(),
            pads: 2,
        };
        let r7 = Footprint {
            reference: "R7".into(),
            value: "10k".into(),
            lib_id: "R_0603".into(),
            layer: "B.Cu".into(),
            pads: 1,
        };
        assert_eq!(summary().footprints, [c1, r7]);
    }

    #[test]
    fn json_has_fixed_layout() {
        let json = summary().to_json();
        assert!(json.starts_with("{\n  \"schema\": \"kal-board-summary/1\",\n"));
        assert!(json.contains("\"thickness_nm\": 1600000,"));
        assert!(json.contains("\"outline_nm\": [0, 0, 65000000, 40000000],"));
        assert!(json.contains("\"footprints_by_prefix\": {\"C\": 1, \"R\": 1},"));
        let lengths = "\"segment_length_nm\": {\"/DDR/DQ0\": 1000000, \"GND\": 11000000},";
        assert!(json.contains(lengths));
        assert!(json.contains("{\"ref\": \"R7\", \"value\": \"10k\", \"lib\": \"R_0603\","));
        assert!(json.ends_with("\"pads\": 1}\n  ]\n}\n"));
    }

    #[test]
    fn json_strings_are_escaped() {
        assert_eq!(json_str("a\"b\\\n\u{1}"), "\"a\\\"b\\\\\\n\\u0001\"");
        assert_eq!(
            summarize(&parse("(kicad_sch)").unwrap()),
            Err(SummaryError::NotABoard)
        );
    }
}
