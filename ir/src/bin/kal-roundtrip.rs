//! Round-trip a KiCad S-expression file through the kal-ir tree.
//!
//! Usage: kal-roundtrip <in> <out> [--canonical]
//! Default: write back with the original layout and require byte-identical output.
//! `--canonical`: write with canonical layout and require the same tree after re-parsing.
//! Exit: 0 ok, 1 round-trip mismatch, 2 usage, IO or parse error.

use std::fs;
use std::process::ExitCode;

use kal_ir::sexpr;

fn usage() -> ExitCode {
    eprintln!("usage: kal-roundtrip <in> <out> [--canonical]");
    ExitCode::from(2)
}

fn main() -> ExitCode {
    let mut canonical = false;
    let mut paths = Vec::new();
    for arg in std::env::args().skip(1) {
        match arg.as_str() {
            "--canonical" => canonical = true,
            _ if arg.starts_with("--") => return usage(),
            _ => paths.push(arg),
        }
    }
    let [input, output] = paths.as_slice() else {
        return usage();
    };
    match run(input, output, canonical) {
        Ok(true) => ExitCode::SUCCESS,
        Ok(false) => {
            eprintln!("kal-roundtrip: {input}: round-trip mismatch");
            ExitCode::from(1)
        }
        Err(msg) => {
            eprintln!("kal-roundtrip: {input}: {msg}");
            ExitCode::from(2)
        }
    }
}

/// Returns whether the round-trip matched; Err for IO or parse failures.
fn run(input: &str, output: &str, canonical: bool) -> Result<bool, String> {
    let src = fs::read_to_string(input).map_err(|e| e.to_string())?;
    let doc = sexpr::parse(&src).map_err(|e| e.to_string())?;
    let written = if canonical {
        doc.write_canonical()
    } else {
        doc.write()
    };
    fs::write(output, &written).map_err(|e| format!("{output}: {e}"))?;
    if !canonical {
        return Ok(written == src);
    }
    Ok(sexpr::parse(&written).is_ok_and(|re| re.same_tree(&doc)))
}
