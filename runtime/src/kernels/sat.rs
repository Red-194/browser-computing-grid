use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize)]
pub struct SatInput {
    pub num_variables: u32,
    pub clauses: Vec<Vec<i32>>,
    pub fixed_assignments: Vec<i32>,
}

#[derive(Serialize, Deserialize)]
pub struct SatOutput {
    pub satisfiable: bool,
    pub model: Option<Vec<i32>>,
}

pub fn run(input: SatInput) -> SatOutput {
    let mut assignment = vec![0_i8; input.num_variables as usize + 1];

    for literal in input.fixed_assignments {
        if !set_literal(&mut assignment, literal) {
            return SatOutput { satisfiable: false, model: None };
        }
    }

    if !valid_formula(&input.clauses, input.num_variables) || !dpll(&input.clauses, &mut assignment) {
        return SatOutput { satisfiable: false, model: None };
    }

    let model = (1..=input.num_variables as usize)
        .map(|variable| if assignment[variable] < 0 { -(variable as i32) } else { variable as i32 })
        .collect();

    SatOutput { satisfiable: true, model: Some(model) }
}

fn valid_formula(clauses: &[Vec<i32>], num_variables: u32) -> bool {
    clauses.iter().flatten().all(|literal| {
        *literal != 0 && literal.unsigned_abs() <= num_variables
    })
}

fn set_literal(assignment: &mut [i8], literal: i32) -> bool {
    if literal == 0 || literal.unsigned_abs() as usize >= assignment.len() {
        return false;
    }

    let value = if literal > 0 { 1 } else { -1 };
    let slot = &mut assignment[literal.unsigned_abs() as usize];
    if *slot != 0 && *slot != value {
        return false;
    }
    *slot = value;
    true
}

fn literal_value(assignment: &[i8], literal: i32) -> i8 {
    let value = assignment[literal.unsigned_abs() as usize];
    if literal > 0 { value } else { -value }
}

fn propagate(clauses: &[Vec<i32>], assignment: &mut [i8]) -> bool {
    loop {
        let mut changed = false;

        for clause in clauses {
            let mut unassigned = 0;
            let mut unit_literal = 0;
            let mut satisfied = false;

            for &literal in clause {
                match literal_value(assignment, literal) {
                    1 => { satisfied = true; break; }
                    0 => { unassigned += 1; unit_literal = literal; }
                    _ => {}
                }
            }

            if satisfied {
                continue;
            }
            if unassigned == 0 {
                return false;
            }
            if unassigned == 1 {
                let before = assignment[unit_literal.unsigned_abs() as usize];
                if !set_literal(assignment, unit_literal) {
                    return false;
                }
                changed |= before == 0;
            }
        }

        if !changed {
            return true;
        }
    }
}

fn dpll(clauses: &[Vec<i32>], assignment: &mut Vec<i8>) -> bool {
    if !propagate(clauses, assignment) {
        return false;
    }

    let Some(variable) = assignment.iter().skip(1).position(|value| *value == 0).map(|index| index + 1) else {
        return true;
    };

    let snapshot = assignment.clone();
    assignment[variable] = 1;
    if dpll(clauses, assignment) {
        return true;
    }

    *assignment = snapshot.clone();
    assignment[variable] = -1;
    if dpll(clauses, assignment) {
        return true;
    }

    *assignment = snapshot;
    false
}
