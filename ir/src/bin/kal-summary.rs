//! Print a JSON summary of a `.kicad_pcb` for the design review (schema kal-board-summary/1).
//!
//! Usage: kal-summary <board.kicad_pcb>
//! Exit: 0 ok, 2 usage, IO, parse or not-a-board error.

use std::process::ExitCode;

use kal_ir::{board, sexpr};

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let [path] = args.as_slice() else {
        eprintln!("usage: kal-summary <board.kicad_pcb>");
        return ExitCode::from(2);
    };
    match run(path) {
        Ok(json) => {
            print!("{json}");
            ExitCode::SUCCESS
        }
        Err(msg) => {
            eprintln!("kal-summary: {path}: {msg}");
            ExitCode::from(2)
        }
    }
}

fn run(path: &str) -> Result<String, String> {
    let src = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
    let doc = sexpr::parse(&src).map_err(|e| e.to_string())?;
    let summary = board::summarize(&doc).map_err(|e| e.to_string())?;
    Ok(summary.to_json())
}
