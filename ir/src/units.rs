//! Integer nanometers, matching KiCad's internal unit. No floats in the geometry core.

use std::ops::{Add, AddAssign, Neg, Sub};

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

    /// Parse a millimetre number as KiCad writes it ("1.6", "-2", ".5") without floats.
    /// `None` for anything finer than 1 nm, exponents, signs other than a leading '-',
    /// overflow or non-numbers.
    pub fn parse_mm(text: &str) -> Option<Nm> {
        let (negative, digits) = match text.strip_prefix('-') {
            Some(rest) => (true, rest),
            None => (false, text),
        };
        let (whole, frac) = digits.split_once('.').unwrap_or((digits, ""));
        if !is_digits(whole) || !is_digits(frac) || whole.len() + frac.len() == 0 {
            return None;
        }
        let frac = frac.trim_end_matches('0');
        if frac.len() > 6 {
            return None;
        }
        let scale = 10_i64.pow(6 - frac.len() as u32);
        let whole_nm = digits_value(whole)?.checked_mul(1_000_000)?;
        let nm = whole_nm.checked_add(digits_value(frac)? * scale)?;
        Some(Nm(if negative { -nm } else { nm }))
    }
}

fn is_digits(s: &str) -> bool {
    s.bytes().all(|b| b.is_ascii_digit())
}

fn digits_value(s: &str) -> Option<i64> {
    if s.is_empty() {
        return Some(0);
    }
    s.parse().ok()
}

impl Add for Nm {
    type Output = Nm;
    fn add(self, rhs: Nm) -> Nm {
        Nm(self.0 + rhs.0)
    }
}

impl AddAssign for Nm {
    fn add_assign(&mut self, rhs: Nm) {
        self.0 += rhs.0;
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
        let mut total = Nm(1);
        total += Nm(2);
        assert_eq!(total, Nm(3));
    }

    #[test]
    fn parse_mm_is_exact() {
        assert_eq!(Nm::parse_mm("1.6"), Some(Nm(1_600_000)));
        assert_eq!(Nm::parse_mm("-2"), Some(Nm(-2_000_000)));
        assert_eq!(Nm::parse_mm(".5"), Some(Nm(500_000)));
        assert_eq!(Nm::parse_mm("0.000001"), Some(Nm(1)));
        assert_eq!(Nm::parse_mm("1.50000000"), Some(Nm(1_500_000)));
        for bad in ["", "-", ".", "+1", "1e3", "1.2.3", "abc"] {
            assert_eq!(Nm::parse_mm(bad), None, "{bad}");
        }
        assert_eq!(Nm::parse_mm("0.0000001"), None);
        assert_eq!(Nm::parse_mm("99999999999999"), None);
    }
}
