//! Score a board's placement and the baseline placer's (schema kal-place/1). Read-only: the
//! board file is never written.
//!
//! Usage: kal-place <board.kicad_pcb>
//! Exit: 0 ok, 1 the placer found no placement (reported in the JSON), 2 usage, IO, parse or
//! import error.

use std::process::ExitCode;

use kal_core::import::{import, Imported};
use kal_core::ir::{layout, sexpr, Nm};
use kal_core::placement::{evaluate, Cost, Placer, ShelfPlacer};
use kal_core::ENGINE_VERSION;

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let [path] = args.as_slice() else {
        eprintln!("usage: kal-place <board.kicad_pcb>");
        return ExitCode::from(2);
    };
    match run(path) {
        Ok((json, placed)) => {
            println!("{json}");
            if placed {
                ExitCode::SUCCESS
            } else {
                ExitCode::from(1)
            }
        }
        Err(msg) => {
            eprintln!("kal-place: {path}: {msg}");
            ExitCode::from(2)
        }
    }
}

fn run(path: &str) -> Result<(String, bool), String> {
    let src = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
    let doc = sexpr::parse(&src).map_err(|e| e.to_string())?;
    let board = layout::layout(&doc).map_err(|e| e.to_string())?;
    // Courtyards already carry the assembly margin, so bodies may touch.
    let imported = import(&board, Nm::ZERO).map_err(|e| e.to_string())?;
    let Imported { problem, current, .. } = &imported;
    let placer = ShelfPlacer;
    let seed = 0;
    let (result, placed) = match placer.place(problem, seed) {
        Ok(placement) => (cost_json(&evaluate(problem, &placement)), true),
        Err(e) => {
            let err = json_str(&e.to_string());
            (format!("{{\"error\": {err}}}"), false)
        }
    };
    let fixed = problem.parts.iter().filter(|p| p.fixed.is_some()).count();
    let lines = [
        "\"schema\": \"kal-place/1\"".to_string(),
        format!("\"engine\": {}", json_str(ENGINE_VERSION)),
        format!("\"parts\": {}", problem.parts.len()),
        format!("\"fixed\": {fixed}"),
        format!("\"nets\": {}", problem.nets.len()),
        format!("\"off_grid\": {}", imported.off_grid.len()),
        format!("\"skipped\": {}", imported.skipped.len()),
        format!("\"current\": {}", cost_json(&evaluate(problem, current))),
        format!("\"placer\": {}", json_str(placer.name())),
        format!("\"seed\": {seed}"),
        format!("\"result\": {result}"),
    ];
    Ok((format!("{{\n  {}\n}}", lines.join(",\n  ")), placed))
}

fn cost_json(c: &Cost) -> String {
    format!(
        "{{\"wirelength_nm\": {}, \"overlap_nm2\": {}, \"outside_nm2\": {}, \"legal\": {}}}",
        c.wirelength,
        c.overlap,
        c.outside,
        c.is_legal()
    )
}

fn json_str(s: &str) -> String {
    let mut out = String::from("\"");
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push('"');
    out
}
