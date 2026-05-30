import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

_STATE_HEX_RE = re.compile(r"^-?[0-9A-F]$")


@dataclass
class ContractViolation:
    field: str
    value: Any
    rule: str
    message: str


@dataclass
class ValidationResult:
    valid: bool
    violations: list[ContractViolation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_violation(self, field: str, value: Any, rule: str, msg: str):
        self.valid = False
        self.violations.append(ContractViolation(field, value, rule, msg))

    def add_warning(self, msg: str):
        self.warnings.append(msg)


def validate_state_hex(value: Any, field: str) -> ContractViolation | None:
    if not isinstance(value, str):
        return ContractViolation(field, value, "STATE_BASE_CONTRACT §3.5", f"{field}={value} 不是字符串")
    if not _STATE_HEX_RE.match(value):
        return ContractViolation(
            field, value, "STATE_BASE_CONTRACT §3.5",
            f"{field}={value} 不符合 hex 格式 /^-?[0-9A-F]$/"
        )
    return None


def validate_ef_count(value: Any, field: str) -> ContractViolation | None:
    if not isinstance(value, int):
        return ContractViolation(field, value, "STATE_BASE_CONTRACT §2.2.8", f"{field}={value} 不是整数")
    if value < 0 or value > 3:
        return ContractViolation(
            field, value, "STATE_BASE_CONTRACT §2.2.8",
            f"{field}={value} 超出 [0, 3] 范围"
        )
    return None


def validate_state_score(value: Any, field: str) -> ContractViolation | None:
    if not isinstance(value, int):
        return ContractViolation(field, value, "STATE_BASE_CONTRACT §3.1", f"{field}={value} 不是整数")
    if value < -15 or value > 15:
        return ContractViolation(
            field, value, "STATE_BASE_CONTRACT §3.1",
            f"{field}={value} 超出 [-15, 15] 范围"
        )
    return None


def validate_slice_envelope(result: dict) -> ValidationResult:
    vr = ValidationResult(valid=True)

    required = ["slice_type", "slice_id", "generated_at", "contract_version",
                "source", "params", "data", "summary", "integrity"]
    for key in required:
        if key not in result:
            vr.add_violation("envelope", None, "contract_v1.json", f"缺失顶层字段 {key}")
        elif result[key] is None:
            vr.add_violation(key, None, "contract_v1.json", f"顶层字段 {key} 为 null")

    ct = result.get("contract_version")
    if ct != "1.0.0":
        vr.add_violation("contract_version", ct, "contract_v1.json",
                         f"合同版本应为 1.0.0，实际为 {ct}")

    vt = result.get("slice_type")
    valid_types = {"user", "strategy", "time", "industry", "cognitive"}
    if vt not in valid_types:
        vr.add_violation("slice_type", vt, "contract_v1.json",
                         f"无效切片类型: {vt}")

    data = result.get("data")
    if not isinstance(data, list):
        vr.add_violation("data", type(data).__name__, "contract_v1.json", "data 必须是数组")
        return vr

    summary = result.get("summary", {})
    expected_rows = summary.get("row_count", -1)
    if expected_rows >= 0 and len(data) != expected_rows:
        vr.add_violation("summary.row_count", expected_rows, "contract_v1.json",
                         f"summary.row_count={expected_rows} 但 data 实际行数={len(data)}")

    integrity = result.get("integrity", {})
    declared_checksum = integrity.get("checksum")
    if declared_checksum and isinstance(declared_checksum, str):
        actual = compute_slice_checksum(data)
        if actual != declared_checksum:
            vr.add_violation(
                "integrity.checksum", declared_checksum, "contract_v1.json",
                f"checksum 不匹配: 声明={declared_checksum[:16]}... 实际={actual[:16]}..."
            )

    integrity_rows = integrity.get("row_count", -1)
    if integrity_rows >= 0 and integrity_rows != len(data):
        vr.add_violation("integrity.row_count", integrity_rows, "contract_v1.json",
                         f"integrity.row_count={integrity_rows} 但 data 实际行数={len(data)}")

    return vr


def validate_state_row(row: dict, slice_type: str) -> list[ContractViolation]:
    violations: list[ContractViolation] = []

    stock_code = row.get("stock_code")
    if not stock_code or not isinstance(stock_code, str) or len(stock_code) < 4:
        violations.append(ContractViolation(
            "stock_code", stock_code, "STATE_BASE_CONTRACT §2.2.1",
            f"stock_code={stock_code} 无效（需 ≥4 位字符串）"
        ))

    state_date = row.get("state_date")
    if not state_date or not isinstance(state_date, str):
        violations.append(ContractViolation(
            "state_date", state_date, "STATE_BASE_CONTRACT §2.2.8",
            f"state_date={state_date} 无效或缺失"
        ))

    for hex_field in ("mn1_state_hex", "w1_state_hex", "d1_state_hex"):
        v = validate_state_hex(row.get(hex_field), hex_field)
        if v:
            violations.append(v)

    if "ef_count" in row:
        v = validate_ef_count(row["ef_count"], "ef_count")
        if v:
            violations.append(v)

    if "d1_close" in row:
        close = row["d1_close"]
        if isinstance(close, (int, float)) and close <= 0:
            violations.append(ContractViolation(
                "d1_close", close, "STATE_BASE_CONTRACT §5.1",
                f"d1_close={close} 必须为正值"
            ))

    for score_field in ("mn1_state_score", "w1_state_score", "d1_state_score"):
        if score_field in row:
            v = validate_state_score(row[score_field], score_field)
            if v:
                violations.append(v)

    if "ef_count" in row and all(f"{f}_state_score" in row for f in ("mn1", "w1", "d1")):
        ef = row["ef_count"]
        expected = sum(
            1 for f in ("mn1", "w1", "d1")
            if row.get(f"{f}_state_score") in (14, 15)
        )
        if ef != expected:
            violations.append(ContractViolation(
                "ef_count", ef, "STATE_BASE_CONTRACT §2.2.8",
                f"ef_count={ef} 但 state_score 实际 E/F 数={expected}"
            ))

    return violations


def validate_slice_data(data: list, slice_type: str) -> ValidationResult:
    vr = ValidationResult(valid=True)
    if not data:
        return vr

    for i, row in enumerate(data):
        if not isinstance(row, dict):
            vr.add_violation(f"data[{i}]", type(row).__name__, "contract_v1.json",
                             f"data[{i}] 不是 dict")
            continue
        violations = validate_state_row(row, slice_type)
        for v in violations:
            vr.add_violation(f"data[{i}].{v.field}", v.value, v.rule, v.message)

    return vr


def validate_slice_result(result: dict) -> ValidationResult:
    vr = validate_slice_envelope(result)
    if not vr.valid:
        return vr

    data = result.get("data", [])
    data_vr = validate_slice_data(data, result.get("slice_type", ""))
    vr.valid = vr.valid and data_vr.valid
    vr.violations.extend(data_vr.violations)
    vr.warnings.extend(data_vr.warnings)
    return vr


def compute_slice_checksum(data: list) -> str:
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def compute_cache_key(slice_type: str, params: dict, cache_date: str) -> str:
    raw = json.dumps({"slice_type": slice_type, "params": params, "cache_date": cache_date},
                     ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
