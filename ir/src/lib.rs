//! Board IR: footprints, pads, nets, netclasses, rules, stackup.
//! Filled by both KiCad paths (S-expression and IPC); independent of KiCad version.

pub mod board;
pub mod sexpr;
pub mod units;

pub use units::Nm;
