//! Engine core: geometry, placement, routing. Open source; no GPL code linked.

pub use kal_ir as ir;

pub mod geom;
pub mod import;
pub mod placement;

/// Logged with every run (with seed, KiCad version, ruleset hash) for determinism.
pub const ENGINE_VERSION: &str = env!("CARGO_PKG_VERSION");

#[cfg(test)]
mod tests {
    #[test]
    fn engine_version_is_set() {
        assert!(!super::ENGINE_VERSION.is_empty());
    }
}
