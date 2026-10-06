//! Integer nanometers, matching KiCad's internal unit. No floats in the geometry core.

use std::ops::{Add, Neg, Sub};

/// A length in integer nanometers.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Default)]
pub struct Nm(pub i64);

impl Nm {
    pub const ZERO: Nm = Nm(0);

    pub const fn from_um(um: i64) -> Nm {
        Nm(um * 1_000)
    }

    pub const fn from_mm(mm: i64) -> Nm {
        Nm(mm * 1_000_000)
    }
}

impl Add for Nm {
    type Output = Nm;
    fn add(self, rhs: Nm) -> Nm {
        Nm(self.0 + rhs.0)
    }
}

impl Sub for Nm {
    type Output = Nm;
    fn sub(self, rhs: Nm) -> Nm {
        Nm(self.0 - rhs.0)
    }
}

impl Neg for Nm {
    type Output = Nm;
    fn neg(self) -> Nm {
        Nm(-self.0)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unit_constructors() {
        assert_eq!(Nm::from_mm(1), Nm(1_000_000));
        assert_eq!(Nm::from_um(250), Nm(250_000));
    }

    #[test]
    fn arithmetic() {
        assert_eq!(Nm::from_mm(2) - Nm::from_um(500), Nm(1_500_000));
        assert_eq!(-Nm(5) + Nm(5), Nm::ZERO);
    }
}
