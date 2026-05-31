import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "_work" / "dead_assert_probe"
BIN = ROOT / "target" / "debug" / "circom.exe"
P = 21888242871839275222246405745257275088548364400416034343698204186575808495617

SRC = """pragma circom 2.2.3;
template Main() {
    signal output out;
    signal x;
    x <== 0;
    x === 1;
    out <== 7;
}
component main = Main();
"""


def compile_case(opt):
    case_dir = WORK / opt
    out_dir = case_dir / "out"
    if case_dir.exists():
        shutil.rmtree(case_dir)
    out_dir.mkdir(parents=True)
    src = case_dir / "case.circom"
    src.write_text(SRC, encoding="ascii")
    cmd = [
        str(BIN),
        str(src),
        f"--{opt}",
        "--json",
        "--sym",
        "--r1cs",
        "--simplification_substitution",
        "-o",
        str(out_dir),
    ]
    run = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    if run.returncode != 0:
        raise SystemExit(run.stderr + run.stdout)
    return out_dir


def parse_constraints(path):
    data = json.loads(path.read_text(encoding="ascii"))
    return data["constraints"]


def parse_lin(obj):
    return {int(k): int(v) % P for k, v in obj.items()}


def eval_lin(expr, assignment):
    acc = 0
    for sig, coeff in expr.items():
        value = 1 if sig == 0 else assignment.get(sig)
        if value is None:
            return None
        acc = (acc + coeff * int(value)) % P
    return acc


def constraints_hold(raw_constraints, assignment):
    for a, b, c in raw_constraints:
        av = eval_lin(parse_lin(a), assignment)
        bv = eval_lin(parse_lin(b), assignment)
        cv = eval_lin(parse_lin(c), assignment)
        if av is None or bv is None or cv is None:
            return False
        if (av * bv - cv) % P != 0:
            return False
    return True


def main():
    compiled = {}
    for opt in ["O0", "O2"]:
        out_dir = compile_case(opt)
        constraints = parse_constraints(out_dir / "case_constraints.json")
        compiled[opt] = constraints
        print(f"{opt} constraints: {len(constraints)}")
        print((out_dir / "case.sym").read_text(encoding="ascii").strip())
        print(json.dumps(constraints, indent=2))

    o0_sat = any(constraints_hold(compiled["O0"], {1: 7, 2: x}) for x in range(2))
    o2_sat = constraints_hold(compiled["O2"], {1: 7})
    print(f"O0 accepts out=7: {o0_sat}")
    print(f"O2 accepts out=7: {o2_sat}")
    if o0_sat or not o2_sat:
        raise SystemExit("unexpected result")


if __name__ == "__main__":
    main()
