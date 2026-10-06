//! Lossless S-expression tree for KiCad files (`.kicad_pcb`, `.kicad_sch`, ...).
//!
//! Atoms keep their exact source text, so numbers are never converted to floats, and every node
//! keeps the whitespace in front of it: [`parse`] followed by [`Document::write`] reproduces the
//! input byte for byte. [`Document::write_canonical`] drops the original layout and writes one
//! list per line, for files we generate.

use std::fmt;

/// One node of the tree.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Node {
    /// A symbol, number or quoted string, exactly as written (quotes and escapes included).
    Atom { ws: String, text: String },
    /// `( items )`; `end` is the whitespace before the closing paren. `implicit` is true when
    /// the source had no '(' (a known KiCad writer bug, see `opens_implicit_list`).
    List {
        ws: String,
        items: Vec<Node>,
        end: String,
        implicit: bool,
    },
}

/// A parsed file: top-level nodes plus the whitespace after the last one.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Document {
    pub nodes: Vec<Node>,
    pub trailing: String,
}

/// Why parsing failed, with the byte offset and 1-based line where it was detected.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ParseError {
    pub kind: ParseErrorKind,
    pub byte: usize,
    pub line: usize,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ParseErrorKind {
    UnexpectedClose,
    UnclosedList,
    UnterminatedString,
}

impl ParseError {
    fn at(src: &str, byte: usize, kind: ParseErrorKind) -> ParseError {
        let line = src.as_bytes()[..byte]
            .iter()
            .filter(|&&b| b == b'\n')
            .count()
            + 1;
        ParseError { kind, byte, line }
    }
}

impl fmt::Display for ParseError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let what = match self.kind {
            ParseErrorKind::UnexpectedClose => "unexpected ')'",
            ParseErrorKind::UnclosedList => "unclosed '('",
            ParseErrorKind::UnterminatedString => "unterminated string",
        };
        write!(f, "{what} at line {} (byte {})", self.line, self.byte)
    }
}

impl std::error::Error for ParseError {}

struct Frame {
    open: usize,
    ws: String,
    items: Vec<Node>,
    implicit: bool,
}

fn is_ws(b: u8) -> bool {
    matches!(b, b' ' | b'\t' | b'\n' | b'\r')
}

fn is_atom_end(b: u8) -> bool {
    is_ws(b) || matches!(b, b'(' | b')' | b'"')
}

fn push(stack: &mut [Frame], nodes: &mut Vec<Node>, node: Node) {
    match stack.last_mut() {
        Some(frame) => frame.items.push(node),
        None => nodes.push(node),
    }
}

fn list_head(node: &Node) -> Option<&str> {
    match node {
        Node::List { items, .. } => match items.first() {
            Some(Node::Atom { text, .. }) => Some(text.as_str()),
            _ => None,
        },
        Node::Atom { .. } => None,
    }
}

/// KiCad 8/9 wrote teardrop settings as `(curved_edges no)filter_ratio 0.9)`, without the '('
/// before `filter_ratio`. KiCad reads such files, so exactly this case opens a list whose '('
/// is missing.
fn opens_implicit_list(stack: &[Frame], text: &str) -> bool {
    let Some(frame) = stack.last() else {
        return false;
    };
    let parent = match frame.items.first() {
        Some(Node::Atom { text, .. }) => text.as_str(),
        _ => "",
    };
    let previous = frame.items.last().and_then(list_head);
    text == "filter_ratio" && parent == "teardrops" && previous == Some("curved_edges")
}

/// Parse a whole file. Iterative, so deeply nested input cannot overflow the stack.
pub fn parse(src: &str) -> Result<Document, ParseError> {
    let bytes = src.as_bytes();
    let mut stack: Vec<Frame> = Vec::new();
    let mut nodes: Vec<Node> = Vec::new();
    let mut i = 0;
    loop {
        let ws_start = i;
        while i < bytes.len() && is_ws(bytes[i]) {
            i += 1;
        }
        let ws = src[ws_start..i].to_string();
        if i == bytes.len() {
            if let Some(frame) = stack.last() {
                return Err(ParseError::at(
                    src,
                    frame.open,
                    ParseErrorKind::UnclosedList,
                ));
            }
            let trailing = ws;
            return Ok(Document { nodes, trailing });
        }
        match bytes[i] {
            b'(' => {
                stack.push(Frame {
                    open: i,
                    ws,
                    items: Vec::new(),
                    implicit: false,
                });
                i += 1;
            }
            b')' => {
                let Some(frame) = stack.pop() else {
                    return Err(ParseError::at(src, i, ParseErrorKind::UnexpectedClose));
                };
                i += 1;
                let list = Node::List {
                    ws: frame.ws,
                    items: frame.items,
                    end: ws,
                    implicit: frame.implicit,
                };
                push(&mut stack, &mut nodes, list);
            }
            b'"' => {
                let start = i;
                i += 1;
                loop {
                    match bytes.get(i) {
                        Some(b'"') => break,
                        Some(b'\\') => i += 2,
                        Some(_) => i += 1,
                        None => {
                            let kind = ParseErrorKind::UnterminatedString;
                            return Err(ParseError::at(src, start, kind));
                        }
                    }
                }
                i += 1;
                let text = src[start..i].to_string();
                push(&mut stack, &mut nodes, Node::Atom { ws, text });
            }
            _ => {
                let start = i;
                while i < bytes.len() && !is_atom_end(bytes[i]) {
                    i += 1;
                }
                let text = src[start..i].to_string();
                if opens_implicit_list(&stack, &text) {
                    let atom = Node::Atom {
                        ws: String::new(),
                        text,
                    };
                    stack.push(Frame {
                        open: start,
                        ws,
                        items: vec![atom],
                        implicit: true,
                    });
                } else {
                    push(&mut stack, &mut nodes, Node::Atom { ws, text });
                }
            }
        }
    }
}

/// The value of an atom: quoted strings lose their quotes and escapes, symbols are unchanged.
pub fn unquote(text: &str) -> String {
    let Some(inner) = text.strip_prefix('"').and_then(|t| t.strip_suffix('"')) else {
        return text.to_string();
    };
    let mut out = String::with_capacity(inner.len());
    let mut escaped = false;
    for c in inner.chars() {
        if escaped {
            out.push(if c == 'n' { '\n' } else { c });
            escaped = false;
        } else if c == '\\' {
            escaped = true;
        } else {
            out.push(c);
        }
    }
    out
}

impl Document {
    /// Write back with the original layout; byte-identical to the parsed input.
    pub fn write(&self) -> String {
        let mut out = String::new();
        for node in &self.nodes {
            node.write_into(&mut out);
        }
        out.push_str(&self.trailing);
        out
    }

    /// Write with canonical layout: one list per line, tab-indented, trailing newline.
    /// Lists whose '(' was missing in the source get it back.
    pub fn write_canonical(&self) -> String {
        let mut out = String::new();
        for node in &self.nodes {
            node.canonical_into(&mut out, 0);
            out.push('\n');
        }
        out
    }

    /// Same atoms in the same structure, ignoring whitespace.
    pub fn same_tree(&self, other: &Document) -> bool {
        self.nodes.len() == other.nodes.len()
            && self
                .nodes
                .iter()
                .zip(&other.nodes)
                .all(|(a, b)| a.same_tree(b))
    }
}

impl Node {
    /// Items of a list; empty for an atom.
    pub fn items(&self) -> &[Node] {
        match self {
            Node::List { items, .. } => items,
            Node::Atom { .. } => &[],
        }
    }

    /// First atom of a list, e.g. `net` for `(net 1 "A")`.
    pub fn head(&self) -> Option<&str> {
        self.arg(0)
    }

    /// Atom text at position `i` of a list (0 is the head), exactly as written.
    pub fn arg(&self, i: usize) -> Option<&str> {
        match self.items().get(i) {
            Some(Node::Atom { text, .. }) => Some(text.as_str()),
            _ => None,
        }
    }

    /// First child list whose head is `head`.
    pub fn child(&self, head: &str) -> Option<&Node> {
        self.items().iter().find(|n| n.head() == Some(head))
    }

    /// All child lists whose head is `head`.
    pub fn children<'a>(&'a self, head: &'a str) -> impl Iterator<Item = &'a Node> + 'a {
        let items = self.items().iter();
        items.filter(move |n| n.head() == Some(head))
    }

    /// Same atoms in the same structure, ignoring whitespace.
    pub fn same_tree(&self, other: &Node) -> bool {
        match (self, other) {
            (Node::Atom { text: a, .. }, Node::Atom { text: b, .. }) => a == b,
            (Node::List { items: a, .. }, Node::List { items: b, .. }) => {
                a.len() == b.len() && a.iter().zip(b).all(|(x, y)| x.same_tree(y))
            }
            _ => false,
        }
    }

    fn write_into(&self, out: &mut String) {
        match self {
            Node::Atom { ws, text } => {
                out.push_str(ws);
                out.push_str(text);
            }
            Node::List {
                ws,
                items,
                end,
                implicit,
            } => {
                out.push_str(ws);
                if !*implicit {
                    out.push('(');
                }
                for item in items {
                    item.write_into(out);
                }
                out.push_str(end);
                out.push(')');
            }
        }
    }

    fn canonical_into(&self, out: &mut String, depth: usize) {
        match self {
            Node::Atom { text, .. } => out.push_str(text),
            Node::List { items, .. } => {
                out.push('(');
                // Leading atoms stay on the '(' line; from the first child list on, one per line.
                let mut broken = false;
                for (k, item) in items.iter().enumerate() {
                    broken |= matches!(item, Node::List { .. });
                    if broken {
                        newline(out, depth + 1);
                    } else if k > 0 {
                        out.push(' ');
                    }
                    item.canonical_into(out, depth + 1);
                }
                if broken {
                    newline(out, depth);
                }
                out.push(')');
            }
        }
    }
}

fn newline(out: &mut String, depth: usize) {
    out.push('\n');
    for _ in 0..depth {
        out.push('\t');
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const SAMPLE: &str = r#"(kicad_pcb
	(version 20240108)
	(net 1 "A \"quoted\" (x)")
  (gr_text "Ä ü"   (at 0.1500000001 -2))
	(empty ())
)
"#;

    fn items(node: &Node) -> &[Node] {
        match node {
            Node::List { items, .. } => items,
            Node::Atom { .. } => panic!("expected a list"),
        }
    }

    fn text(node: &Node) -> &str {
        match node {
            Node::Atom { text, .. } => text,
            Node::List { .. } => panic!("expected an atom"),
        }
    }

    #[test]
    fn write_is_byte_identical() {
        assert_eq!(parse(SAMPLE).unwrap().write(), SAMPLE);
        let crlf = SAMPLE.replace('\n', "\r\n");
        assert_eq!(parse(&crlf).unwrap().write(), crlf);
        assert_eq!(parse("").unwrap().write(), "");
    }

    #[test]
    fn atoms_keep_source_text() {
        let doc = parse(SAMPLE).unwrap();
        let board = items(&doc.nodes[0]);
        assert_eq!(text(&board[0]), "kicad_pcb");
        assert_eq!(text(&items(&board[2])[2]), r#""A \"quoted\" (x)""#);
        let at = items(&items(&board[3])[2]);
        assert_eq!(text(&at[1]), "0.1500000001");
    }

    #[test]
    fn accessors_and_unquote() {
        let doc = parse(SAMPLE).unwrap();
        let board = &doc.nodes[0];
        assert_eq!(board.head(), Some("kicad_pcb"));
        let version = board.child("version").and_then(|v| v.arg(1));
        assert_eq!(version, Some("20240108"));
        assert_eq!(board.children("net").count(), 1);
        assert_eq!(board.items()[0].head(), None);
        let name = board.child("net").and_then(|n| n.arg(2)).map(unquote);
        assert_eq!(name.as_deref(), Some("A \"quoted\" (x)"));
        assert_eq!(unquote("plain"), "plain");
        assert_eq!(unquote(r#""a\nb""#), "a\nb");
    }

    #[test]
    fn canonical_keeps_tree() {
        let doc = parse(SAMPLE).unwrap();
        let canonical = doc.write_canonical();
        assert!(parse(&canonical).unwrap().same_tree(&doc));
        assert!(canonical.starts_with("(kicad_pcb\n\t(version 20240108)\n"));
        assert!(canonical.contains("\t(empty\n\t\t()\n\t)\n)\n"));
    }

    #[test]
    fn same_tree_ignores_layout_only() {
        let a = parse("(a (b 1) \"s\")").unwrap();
        let b = parse("(a\n\t(b 1)\n\t\"s\"\n)").unwrap();
        let c = parse("(a (b 2) \"s\")").unwrap();
        assert!(a.same_tree(&b));
        assert!(!a.same_tree(&c));
    }

    #[test]
    fn errors_report_line() {
        let err = parse("(a\n(b))\n)").unwrap_err();
        assert_eq!((err.kind, err.line), (ParseErrorKind::UnexpectedClose, 3));
        let err = parse("(a\n(b)").unwrap_err();
        assert_eq!((err.kind, err.line), (ParseErrorKind::UnclosedList, 1));
        let err = parse("(a \"x\\\")").unwrap_err();
        assert_eq!(err.kind, ParseErrorKind::UnterminatedString);
    }

    #[test]
    fn accepts_kicad_teardrop_filter_ratio_bug() {
        // As written by KiCad 8/9: the '(' before filter_ratio is missing.
        let src = "(pad (teardrops (curved_edges no)filter_ratio 0.9) (enabled yes)))";
        let doc = parse(src).unwrap();
        assert_eq!(doc.write(), src);
        let teardrops = &items(&doc.nodes[0])[1];
        let ratio = &items(teardrops)[2];
        assert_eq!(text(&items(ratio)[0]), "filter_ratio");
        let canonical = doc.write_canonical();
        assert!(canonical.contains("\t\t(filter_ratio 0.9)\n"));
        assert!(parse(&canonical).unwrap().same_tree(&doc));
        // Anywhere else a stray ')' is still an error.
        let err = parse("(pad (x no)filter_ratio 0.9))").unwrap_err();
        assert_eq!(err.kind, ParseErrorKind::UnexpectedClose);
    }
}
