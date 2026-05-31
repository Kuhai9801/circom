import itertools
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "_work" / "relations"
BIN = ROOT / "target" / "debug" / ("circom.exe")
P = 21888242871839275222246405745257275088548364400416034343698204186575808495617


def mod(x):
    return x % P


def write_case(name, body):
    case_dir = WORK / name
    out_dir = case_dir / "out"
    if case_dir.exists():
        shutil.rmtree(case_dir)
    out_dir.mkdir(parents=True)
    src = case_dir / "case.circom"
    src.write_text(body, encoding="ascii")
    cmd = [
        str(BIN),
        str(src),
        "--O2",
        "--json",
        "--sym",
        "--r1cs",
        "--simplification_substitution",
        "-o",
        str(out_dir),
    ]
    run = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    return case_dir, out_dir, run


def parse_sym(path):
    by_name = {}
    all_signals = []
    for line in path.read_text(encoding="ascii").splitlines():
        if not line.strip():
            continue
        s, w, c, name = line.split(",", 3)
        row = (int(s), int(w), int(c), name)
        by_name[name] = row
        all_signals.append(row)
    return by_name, all_signals


def parse_constraints(path):
    data = json.loads(path.read_text(encoding="ascii"))
    constraints = []
    for a, b, c in data["constraints"]:
        constraints.append((parse_lin(a), parse_lin(b), parse_lin(c)))
    return constraints


def parse_lin(obj):
    return {int(k): int(v) % P for k, v in obj.items()}


def eval_lin(expr, assignment):
    total = 0
    for sig, coeff in expr.items():
        val = 1 if sig == 0 else assignment.get(sig)
        if val is None:
            return None
        total = (total + coeff * val) % P
    return total


def constraints_hold(constraints, assignment):
    for a, b, c in constraints:
        av = eval_lin(a, assignment)
        bv = eval_lin(b, assignment)
        cv = eval_lin(c, assignment)
        if av is None or bv is None or cv is None:
            return None
        if (av * bv - cv) % P != 0:
            return False
    return True


def relation_allows_wrong(out_dir, expect):
    by_name, all_signals = parse_sym(out_dir / "case.sym")
    constraints = parse_constraints(out_dir / "case_constraints.json")
    named = {name.removeprefix("main."): s for name, (s, _, _, _) in by_name.items()}
    public = [named["out"], named["a"], named["b"]]
    private = [s for s, w, _, name in all_signals if s not in public and w != -1]
    small = range(0, 8)
    for a, b in itertools.product(small, repeat=2):
        good = mod(expect(a, b))
        for out in small:
            if out == good:
                continue
            base = {named["a"]: a, named["b"]: b, named["out"]: out}
            for vals in itertools.product(small, repeat=len(private)):
                assignment = dict(base)
                assignment.update(dict(zip(private, vals)))
                ok = constraints_hold(constraints, assignment)
                if ok:
                    return {
                        "a": a,
                        "b": b,
                        "out": out,
                        "expected": good,
                        "private": dict(zip(private, vals)),
                        "constraints": len(constraints),
                    }
    return None


CASES = [
    (
        "mul_add",
        """
pragma circom 2.2.3;
template Main() {
    signal input a;
    signal input b;
    signal output out;
    signal t;
    t <== a * b;
    out <== t + a;
}
component main { public [a, b] } = Main();
""",
        lambda a, b: a * b + a,
    ),
    (
        "square_product",
        """
pragma circom 2.2.3;
template Main() {
    signal input a;
    signal input b;
    signal output out;
    signal x;
    signal y;
    x <== a + b;
    y <== x * x;
    out <== y - a;
}
component main { public [a, b] } = Main();
""",
        lambda a, b: (a + b) * (a + b) - a,
    ),
    (
        "two_products",
        """
pragma circom 2.2.3;
template Main() {
    signal input a;
    signal input b;
    signal output out;
    signal x;
    signal y;
    x <== a * b;
    y <== (a + 1) * (b + 2);
    out <== x + y;
}
component main { public [a, b] } = Main();
""",
        lambda a, b: a * b + (a + 1) * (b + 2),
    ),
    (
        "selected_product",
        """
pragma circom 2.2.3;
template Main() {
    signal input a;
    signal input b;
    signal output out;
    signal s;
    s <== a * (a - 1);
    out <== s * b + a;
}
component main { public [a, b] } = Main();
""",
        lambda a, b: a * (a - 1) * b + a,
    ),
    (
        "linear_alias_chain",
        """
pragma circom 2.2.3;
template Main() {
    signal input a;
    signal input b;
    signal output out;
    signal x;
    signal y;
    signal z;
    x <== a + 2 * b + 3;
    y <== x + a;
    z <== y - b;
    out <== z * (a + 1);
}
component main { public [a, b] } = Main();
""",
        lambda a, b: (2 * a + b + 3) * (a + 1),
    ),
    (
        "component_alias",
        """
pragma circom 2.2.3;
template Inner() {
    signal input x;
    signal input y;
    signal output z;
    z <== x * y + x;
}
template Main() {
    signal input a;
    signal input b;
    signal output out;
    component c = Inner();
    c.x <== a + 1;
    c.y <== b + 2;
    out <== c.z + b;
}
component main { public [a, b] } = Main();
""",
        lambda a, b: (a + 1) * (b + 2) + (a + 1) + b,
    ),
    (
        "array_accumulate",
        """
pragma circom 2.2.3;
template Main() {
    signal input a;
    signal input b;
    signal output out;
    signal x[3];
    x[0] <== a + b;
    x[1] <== x[0] * a;
    x[2] <== x[1] + b;
    out <== x[2] * x[0];
}
component main { public [a, b] } = Main();
""",
        lambda a, b: ((a + b) * a + b) * (a + b),
    ),
]


def main():
    failures = []
    for name, src, expect in CASES:
        _, out_dir, run = write_case(name, src)
        if run.returncode != 0:
            failures.append((name, "compile-failed", run.stderr + run.stdout))
            continue
        wrong = relation_allows_wrong(out_dir, expect)
        if wrong:
            failures.append((name, "wrong-output-accepted", wrong))
        else:
            print(f"{name}: no wrong public output accepted in small search")
    if failures:
        print(json.dumps(failures, indent=2, sort_keys=True))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
