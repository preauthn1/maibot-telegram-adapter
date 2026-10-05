"""Phase 4：标准库传输适配器；官方 Darwinian 仅在外部 worker 导入。

这里的 dataclass 是 JSON IPC 值对象，不是官方 engine 的替代实现。
代码仅限白名单 AST 的合成 reproduce(value) 任务，不执行生产模块。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol, Sequence
import ast
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile

MAX_SOURCE_BYTES = 8192
TRAIN_CASES = (0, 1, -1, "mai", "", [1, 2])
HOLDOUT_CASES = (3, 7, "holdout", [3, 5])


@dataclass(frozen=True)
class FailureCase:
    data_point_id: str
    input_value: object
    expected_output: object
    actual_output: object
    failure_type: str = "reproduction_mismatch"


@dataclass(frozen=True)
class EvaluationResult:
    score: float
    trainable_failure_cases: tuple[FailureCase, ...]
    holdout_failure_cases: tuple[FailureCase, ...]
    is_viable: bool
    outcomes: tuple[bool, ...]


@dataclass(frozen=True)
class CodeOrganism:
    """仅用于 IPC；外部 worker 会实例化官方 Organism 子类。"""
    source_text: str
    id: str = "baseline"
    parent_id: str | None = None
    from_change_summary: str = ""


class Mutator(Protocol):
    def mutate(self, organism: CodeOrganism, failure_cases: Sequence[FailureCase],
               learning_log_entries: Sequence[dict], sandbox: Path) -> CodeOrganism: ...


@dataclass(frozen=True)
class Problem:
    """本地问题描述；不提供选择/繁殖算法。"""
    initial_organism: CodeOrganism
    evaluator: "Evaluator"
    mutators: tuple[Mutator, ...]


@dataclass(frozen=True)
class CodeEvolutionResult:
    status: str
    sandbox: Path | None
    candidate: Path | None
    reason: str
    command: tuple[str, ...] = ()
    artifact_paths: tuple[Path, ...] = ()


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_code_text(text: str) -> list[str]:
    """Fail-closed 白名单：一个纯同步函数、单参数、无导入/调用/属性/循环。"""
    if not text.strip() or len(text.encode("utf-8")) > MAX_SOURCE_BYTES:
        return ["empty or oversized source"]
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError) as exc:
        return [f"source parse failure: {exc}"]
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        return ["only one top-level function is permitted"]
    function = tree.body[0]
    args = function.args
    if (function.name != "reproduce" or len(args.args) != 1 or args.args[0].arg != "value"
            or args.posonlyargs or args.kwonlyargs or args.defaults or args.kw_defaults
            or args.vararg or args.kwarg or function.decorator_list or function.returns
            or args.args[0].annotation or function.type_comment):
        return ["signature must be exactly reproduce(value), without decorators/annotations/defaults"]
    # 不允许新增 AST 类型；不允许调用、下标、幂、乘法或递归，以限制资源放大。
    allowed = (ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Return, ast.If,
               ast.IfExp, ast.Compare, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
               ast.Name, ast.Load, ast.Constant, ast.List, ast.Tuple, ast.Dict,
               ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not, ast.USub, ast.UAdd)
    nodes = list(ast.walk(tree))
    errors = []
    if len(nodes) > 128:
        errors.append("AST node budget exceeded")
    for node in nodes:
        if not isinstance(node, allowed):
            errors.append(f"forbidden AST node: {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id != "value":
            errors.append(f"forbidden name: {node.id}")
        if isinstance(node, ast.Constant) and not isinstance(node.value, (str, int, float, bool, type(None))):
            errors.append("unsupported literal")
    return sorted(set(errors))


def validate_code_candidate_text(baseline: str, candidate: str) -> list[str]:
    errors = validate_code_text(baseline) + validate_code_text(candidate)
    if errors:
        return sorted(set(errors))
    # 白名单已经冻结完整签名、顶层结构与 registry（注册调用一律禁止）。
    base_args = ast.dump(ast.parse(baseline).body[0].args, include_attributes=False)
    new_args = ast.dump(ast.parse(candidate).body[0].args, include_attributes=False)
    return [] if base_args == new_args else ["function signature changed"]


def validate_code_candidate(baseline: Path, candidate: Path) -> list[str]:
    try:
        if candidate.is_symlink() or baseline.is_symlink():
            return ["symlink source rejected"]
        return validate_code_candidate_text(read_source(baseline), read_source(candidate))
    except (OSError, ValueError, UnicodeError) as exc:
        return [f"source read failure: {exc}"]


def read_source(path: Path) -> str:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError("missing, symlink or oversized source")
    return path.read_text(encoding="utf-8")


def bounded_process(command: Sequence[str], cwd: Path, timeout: int,
                    env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """新进程组、超时杀整组、日志落磁盘，避免无限 stdout 占主进程内存。"""
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(list(command), cwd=cwd, env=env, stdout=stdout, stderr=stderr,
                                   start_new_session=True)
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise
        def tail(handle) -> str:
            handle.seek(0, os.SEEK_END)
            handle.seek(max(0, handle.tell() - 8192))
            return handle.read().decode("utf-8", errors="replace")
        return subprocess.CompletedProcess(list(command), process.returncode, tail(stdout), tail(stderr))


class Evaluator:
    """一次子进程评估十个固定合成样例；最多 2 秒、CPU 1 秒、内存 128 MiB。"""
    def evaluate(self, organism: CodeOrganism) -> EvaluationResult:
        errors = validate_code_text(organism.source_text)
        if errors:
            return EvaluationResult(0.0, (), (), False, ())
        values = list(TRAIN_CASES + HOLDOUT_CASES)
        with tempfile.TemporaryDirectory(prefix="maibot-repro-") as temp_dir:
            root = Path(temp_dir)
            (root / "source.py").write_text(organism.source_text, encoding="utf-8")
            (root / "inputs.json").write_text(json.dumps(values), encoding="utf-8")
            # 候选先过 AST 门；-I 不依赖工作目录导入，读取绝对路径。
            harness = '''import json, resource, sys
resource.setrlimit(resource.RLIMIT_CPU, (1, 1))
resource.setrlimit(resource.RLIMIT_AS, (128*1024*1024, 128*1024*1024))
resource.setrlimit(resource.RLIMIT_FSIZE, (32768, 32768))
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
namespace = {"__builtins__": {}}
exec(compile(open(sys.argv[1], encoding="utf-8").read(), "candidate", "exec"), namespace)
outputs = []
for value in json.load(open(sys.argv[2])):
    try:
        outputs.append({"ok": True, "value": namespace["reproduce"](value)})
    except Exception as exc:
        outputs.append({"ok": False, "error": type(exc).__name__})
json.dump(outputs, open(sys.argv[3], "w"))
'''
            command = [sys.executable, "-I", "-c", harness, str(root / "source.py"),
                       str(root / "inputs.json"), str(root / "outputs.json")]
            try:
                proc = bounded_process(command, root, 2)
                output_file = root / "outputs.json"
                if proc.returncode or not output_file.is_file() or output_file.stat().st_size > 32768:
                    raise ValueError("bounded reproduction failed")
                outputs = json.loads(output_file.read_text())
                if not isinstance(outputs, list) or len(outputs) != len(values):
                    raise ValueError("invalid output count")
            except (OSError, ValueError, subprocess.TimeoutExpired):
                return EvaluationResult(0.0, (), (), False, ())
        failures = []
        outcomes = []
        for i, (value, output) in enumerate(zip(values, outputs)):
            hit = (output.get("ok") is True and type(output.get("value")) is type(value)
                   and output.get("value") == value)
            outcomes.append(hit)
            if not hit:
                prefix = "trainable" if i < len(TRAIN_CASES) else "holdout"
                failures.append(FailureCase(f"{prefix}_{i}", value, value, output))
        train = tuple(f for f in failures if f.data_point_id.startswith("trainable"))
        holdout = tuple(f for f in failures if f.data_point_id.startswith("holdout"))
        # 选择只使用训练得分；holdout 不传给 mutator 或 learning log。
        score = sum(outcomes[:len(TRAIN_CASES)]) / len(TRAIN_CASES)
        return EvaluationResult(score, train, holdout, True, tuple(outcomes))


class ExternalCommandMutator:
    """用户显式批准的可信外部 argv；没有 shell，也没有默认生产命令。"""
    def __init__(self, command_template: Sequence[str], timeout: int = 10) -> None:
        self.command_template = tuple(command_template)
        required = {"{source}", "{candidate}", "{failure_cases}", "{learning_log}", "{sandbox}"}
        if (not self.command_template or not all(isinstance(x, str) and x for x in self.command_template)
                or not required.issubset(set(self.command_template))):
            raise ValueError("explicit argv must contain all five standalone sandbox placeholders")
        if not 1 <= timeout <= 60:
            raise ValueError("mutator timeout must be 1..60")
        self.timeout = timeout

    def mutate(self, organism: CodeOrganism, failure_cases: Sequence[FailureCase],
               learning_log_entries: Sequence[dict], sandbox: Path) -> CodeOrganism:
        sandbox.mkdir(parents=True, exist_ok=False)
        files = {"source": sandbox / "parent.py", "candidate": sandbox / "candidate.py",
                 "failure_cases": sandbox / "failure-cases.json", "learning_log": sandbox / "learning-log.json"}
        files["source"].write_text(organism.source_text, encoding="utf-8")
        write_json(files["failure_cases"], [asdict(f) for f in failure_cases])
        write_json(files["learning_log"], list(learning_log_entries))
        replacements = {"{" + key + "}": str(path) for key, path in files.items()}
        replacements["{sandbox}"] = str(sandbox)
        argv = [replacements.get(token, token) for token in self.command_template]
        proc = bounded_process(argv, sandbox, self.timeout, clean_env(sandbox))
        write_json(sandbox / "command-result.json", {"command": argv, "returncode": proc.returncode,
                                                   "stdout": proc.stdout, "stderr": proc.stderr})
        if proc.returncode:
            raise RuntimeError("mutator command failed")
        text = read_source(files["candidate"])
        errors = validate_code_candidate_text(organism.source_text, text)
        if errors:
            raise ValueError("; ".join(errors))
        return CodeOrganism(text, digest(text), organism.id, "explicit external command mutation")


def clean_env(sandbox: Path) -> dict[str, str]:
    return {"PATH": os.environ.get("PATH", os.defpath), "HOME": str(sandbox),
            "LANG": "C.UTF-8", "PYTHONNOUSERSITE": "1"}


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def run_darwinian(source: Path, *, external_python: Path, mutator_command: Sequence[str],
                  output_root: Path, num_iterations: int = 1, timeout: int = 120) -> CodeEvolutionResult:
    """调用独立 worker 注册官方 Problem，再执行官方 __main__。无自造演化循环。"""
    output_root = output_root.resolve()
    source = source.resolve()
    if output_root == source.parent or output_root in source.parents:
        return CodeEvolutionResult("blocked", None, None, "output must not contain the source")
    output_root.mkdir(parents=True, exist_ok=True)
    sandbox = Path(tempfile.mkdtemp(prefix="darwinian-git-", dir=output_root))
    report = sandbox / "run-report.json"
    artifacts = (report, sandbox / "lineage.jsonl", sandbox / "learning-log.jsonl")
    command: list[str] = []
    def finish(status: str, reason: str, candidate: Path | None = None, **extra) -> CodeEvolutionResult:
        for path in artifacts[1:]:
            if not path.exists():
                path.write_text("", encoding="utf-8")
        write_json(report, {"status": status, "reason": reason, "sandbox": str(sandbox),
                            "candidate": str(candidate) if candidate else None, "command": command,
                            "deployment": "not_applied", **extra})
        return CodeEvolutionResult(status, sandbox, candidate, reason, tuple(command), artifacts)
    try:
        if not 1 <= num_iterations <= 3 or not 1 <= timeout <= 300:
            return finish("blocked", "budget invalid (iterations 1..3, timeout 1..300)")
        text = read_source(source)
        if validate_code_text(text):
            return finish("rejected", "; ".join(validate_code_text(text)))
        ExternalCommandMutator(mutator_command)  # 提前检查 argv 协议。
        if not external_python.is_file() or not os.access(external_python, os.X_OK):
            return finish("blocked", "external Darwinian interpreter unavailable")
        preflight = bounded_process([str(external_python), "-m", "darwinian_evolver", "--help"],
                                    sandbox, 20, clean_env(sandbox))
        (sandbox / "cli-help.txt").write_text(preflight.stdout + preflight.stderr, encoding="utf-8")
        if preflight.returncode or not all(flag in preflight.stdout for flag in
                                           ("--num_iterations", "--output_dir", "--mutator_concurrency")):
            return finish("blocked", "official Darwinian package/CLI unavailable or incompatible")
        # 不克隆工作树、配置、数据库、密钥；仅三个标准库自有文件和合成源码。
        (sandbox / "baseline.py").write_text(text, encoding="utf-8")
        shutil.copy2(Path(__file__), sandbox / "adapter.py")
        worker = Path(__file__).resolve().parents[2] / "scripts" / "maibot_darwinian_worker.py"
        shutil.copy2(worker, sandbox / "worker.py")
        write_json(sandbox / "problem.json", {"mutator_command": list(mutator_command)})
        for argv in (["git", "init", "--quiet"], ["git", "add", "baseline.py", "adapter.py", "worker.py", "problem.json"],
                     ["git", "-c", "user.name=MaiBot Phase4", "-c", "user.email=phase4@localhost",
                      "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "synthetic baseline"]):
            proc = bounded_process(argv, sandbox, 10, clean_env(sandbox))
            if proc.returncode:
                return finish("blocked", "isolated git initialization failed")
        command = [str(external_python), str(sandbox / "worker.py"), "maibot_synthetic",
                   "--num_iterations", str(num_iterations), "--output_dir", str(sandbox / "engine"),
                   "--mutator_concurrency", "1", "--evaluator_concurrency", "1",
                   "--num_parents_per_iteration", "1", "--learning_log", "ancestors"]
        proc = bounded_process(command, sandbox, timeout, clean_env(sandbox))
        write_json(sandbox / "external-result.json", {"returncode": proc.returncode,
                                                    "stdout": proc.stdout, "stderr": proc.stderr})
        if proc.returncode:
            return finish("blocked", "official engine/worker failed; inspect external-result.json")
        results = sandbox / "engine" / "results.jsonl"
        if not results.is_file() or not results.stat().st_size:
            return finish("blocked", "official engine produced no results.jsonl")
        baseline = Evaluator().evaluate(CodeOrganism(text))
        if not baseline.is_viable:
            return finish("rejected", "baseline reproduction failed")
        # 只消费纯文本候选；永不反序列化官方 pickle。父谱系由 worker 官方对象产生。
        accepted = []
        for candidate in sorted((sandbox / "candidates").glob("*.py")):
            candidate_text = read_source(candidate)
            if validate_code_candidate_text(text, candidate_text):
                continue
            score = Evaluator().evaluate(CodeOrganism(candidate_text))
            no_regression = (score.is_viable and len(score.outcomes) == len(baseline.outcomes)
                             and all(new >= old for old, new in zip(baseline.outcomes, score.outcomes)))
            gain = (sum(score.outcomes[len(TRAIN_CASES):]) > sum(baseline.outcomes[len(TRAIN_CASES):]))
            if no_regression and gain:
                accepted.append((sum(score.outcomes), candidate, score))
        if not accepted:
            return finish("retain_baseline", "engine ran; no strict holdout gain with per-case non-regression",
                          baseline=asdict(baseline), engine_results=str(results))
        _, best, evaluation = max(accepted, key=lambda item: item[0])
        artifact = sandbox / "candidate.py"
        shutil.copy2(best, artifact)
        return finish("candidate", "official engine candidate; synthetic gain only; human review required", artifact,
                      baseline=asdict(baseline), evaluation=asdict(evaluation), candidate_sha256=digest(read_source(artifact)),
                      engine_results=str(results))
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        return finish("blocked", f"{type(exc).__name__}: {exc}")


def run_external_evolution(source: Path, *, command: Sequence[str], timeout: int = 300,
                           output_root: Path = Path("data/self-evolution/code-candidates")) -> CodeEvolutionResult:
    """保留旧接口但拒绝无 Problem 的任意命令，避免误报旧假成功路径。"""
    return CodeEvolutionResult("blocked", None, None,
                               "legacy arbitrary-command adapter disabled; use run_darwinian with explicit mutator argv",
                               tuple(command))
